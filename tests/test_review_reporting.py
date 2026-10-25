import json

import pytest

from benchmarks.evaluation.review_evaluation import run_review, schedule
from pyrepair.models import ModelTurn
from tests.fakes import FakeLLM
from tests.test_review_evaluation import APPROVE, make_prepared


def fixture_results():
    rows = schedule(["positive", "negative"], 3)
    manifest = {"schedule": rows, "labels": {"positive": True, "negative": False}, "repeats": 3}
    results = {}
    for row in rows:
        status = "valid"
        approved = True
        if row["candidate"] == "positive" and row["repeat"] == 1 and row["arm"] == "A":
            approved = False
        if row["candidate"] == "negative" and row["repeat"] == 2 and row["arm"] == "A":
            approved = False
        if row["candidate"] == "negative" and row["repeat"] == 3:
            status = "parse_error" if row["arm"] == "A" else "api_error"
        results[row["id"]] = {
            "status": status,
            "parsed": {"approved": approved},
            "usage_known": status != "api_error",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "seconds": 1,
        }
    return manifest, results


def test_error_denominators_flips_and_paired_differences():
    from benchmarks.evaluation.review_reporting import summarize_review

    manifest, results = fixture_results()
    summary = summarize_review(manifest, results, set(results))
    a, b = summary["arms"]["A"], summary["arms"]["B"]
    assert a["false_reject"] == {"numerator": 1, "denominator": 3}
    assert a["false_accept"] == {"numerator": 1, "denominator": 2}
    assert b["false_reject"] == {"numerator": 0, "denominator": 3}
    assert b["false_accept"] == {"numerator": 2, "denominator": 2}
    assert a["correct"] == b["correct"] == {"numerator": 3, "denominator": 6}
    assert a["valid"] == b["valid"] == {"numerator": 5, "denominator": 6}
    assert a["flips"] == {"numerator": 1, "denominator": 1}
    assert b["flips"] == {"numerator": 0, "denominator": 1}
    assert a["incomplete_groups"] == b["incomplete_groups"] == 1
    assert a["parse_errors"] == b["api_errors"] == 1
    assert a["cost_complete"] is True and b["cost_complete"] is False
    assert summary["paired"] == {
        "b_fixes_a": 1,
        "b_breaks_a": 1,
        "both_correct": 2,
        "both_wrong": 1,
        "missing": 1,
    }


def test_pending_requests_not_reclassified_as_correct_or_zero_cost():
    from benchmarks.evaluation.review_reporting import summarize_review

    manifest, results = fixture_results()
    last = manifest["schedule"][-2:]
    results.pop(last[0]["id"])
    results.pop(last[1]["id"])
    started = set(results) | {last[0]["id"]}
    summary = summarize_review(manifest, results, started)
    first, second = (summary["arms"][row["arm"]] for row in last)
    assert first["pending_started"] == 1 and first["cost_complete"] is False
    assert second["not_started"] == 1
    assert first["correct"]["denominator"] == second["correct"]["denominator"] == 6
    assert summary["started_requests"] == 11


def test_report_rebuild_and_corruption_rejection(tmp_path):
    from benchmarks.evaluation.review_reporting import write_report

    prepared = make_prepared(tmp_path)
    client = FakeLLM([ModelTurn(APPROVE, None, (), 0, 0)] * 12)
    out = run_review(
        prepared,
        tmp_path / "run",
        live=True,
        model="deepseek-flash",
        repeats=1,
        request_cap=12,
        client_factory=lambda **kw: client,
    )
    one = write_report(out)
    assert one == write_report(out)
    assert all(not a["cost_complete"] for a in one["arms"].values())
    assert len(client.requests) == 12
    result = out / "requests/0001/result.json"
    data = json.loads(result.read_text(encoding="utf-8"))
    data["parsed"]["approved"] = False
    result.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        write_report(out)


def test_valid_rejection_using_parser_fallback_words_is_still_valid():
    from benchmarks.evaluation.review_evaluation import _valid_parsed
    from pyrepair.review_agent import _parse_review

    content = json.dumps(
        {
            "approved": False,
            "risk": "high",
            "findings": ["invalid_review_json"],
            "reason": "Review 输出无法安全解析",
        }
    )
    assert _valid_parsed(content, _parse_review(content))
    assert not _valid_parsed("not JSON", _parse_review("not JSON"))


def test_report_warns_when_missing_pairs_cannot_support_comparison(tmp_path):
    from benchmarks.evaluation.review_reporting import write_report

    prepared = make_prepared(tmp_path)

    class InterruptedClient:
        def complete(self, messages, tools):
            raise KeyboardInterrupt

    out = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt):
        run_review(
            prepared,
            out,
            live=True,
            model="deepseek-flash",
            repeats=1,
            request_cap=12,
            client_factory=lambda **kw: InterruptedClient(),
        )
    summary = write_report(out)
    assert summary["paired"]["missing"] == 6
    assert "证据不足" in (out / "report.md").read_text(encoding="utf-8")
