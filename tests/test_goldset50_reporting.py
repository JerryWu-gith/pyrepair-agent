"""Hand-derived repeated-evaluation counts, including partial-run exclusions."""

import copy
import importlib
import importlib.util
from types import SimpleNamespace


def api():
    name = "benchmarks.evaluation.goldset_reporting"
    assert importlib.util.find_spec(name) is not None, "goldset reporting missing"
    return importlib.import_module(name)


def example():
    cases = [
        SimpleNamespace(id="s", source_kind="synthetic", split="dev", origin={}),
        SimpleNamespace(
            id="o",
            source_kind="opensource",
            split="holdout",
            origin={"repository": "owner/project"},
        ),
    ]
    rows = []
    for case in cases:
        for trial in (1, 2, 3):
            for method in ("single-shot", "full-agent"):
                passed = (method == "full-agent" and (case.id == "s" or trial < 3)) or (
                    method == "single-shot" and case.id == "s" and trial == 1
                )
                rows.append(
                    {
                        "slot": f"{case.id}--{trial}--{method}",
                        "case_id": case.id,
                        "method": method,
                        "trial": trial,
                        "source_kind": case.source_kind,
                        "status": "core_passed" if passed else "failed",
                        "core_passed": passed,
                        "duration_seconds": 2.0,
                    }
                )
    return cases, {
        "planned": 12,
        "finished": 12,
        "performance_measured": True,
        "rows": rows,
        "usage": {"responses": 9},
    }


def test_report_averages_all_repeats_and_keeps_holdout_separate(tmp_path):
    cases, raw = example()
    result = api().summarize_goldset(cases, raw, tmp_path)
    groups = {(g["group"], g["method"]): g for g in result["groups"]}
    assert groups["all", "full-agent"]["accepted"] == 5
    assert groups["all", "full-agent"]["planned"] == 6
    assert groups["all", "full-agent"]["success_rate"] == 5 / 6
    assert groups["opensource-holdout", "full-agent"]["success_rate"] == 2 / 3
    assert groups["all", "single-shot"]["success_rate"] == 1 / 6
    assert groups["all", "full-agent"]["three_of_three_tasks"] == 1
    task = next(r for r in result["tasks"] if (r["case_id"], r["method"]) == ("o", "full-agent"))
    assert task["accepted_repeats"] == 2 and task["repeat_average_rate"] == 2 / 3
    assert task["grading_seconds_known"] == 0
    assert result["usage"] == {"responses": 9}


def test_partial_or_owned_fake_run_is_not_reported_as_full_performance(tmp_path):
    cases, raw = example()
    raw["rows"][-1].update(status="unrun", core_passed=None, duration_seconds=None)
    raw["finished"] = 11
    result = api().summarize_goldset(cases, raw, tmp_path)
    assert result["complete"] is False
    all_agent = next(
        r for r in result["groups"] if (r["group"], r["method"]) == ("all", "full-agent")
    )
    assert all_agent["success_rate"] is None and all_agent["unrun"] == 1
    owned = copy.deepcopy(raw)
    owned["performance_measured"] = False
    result = api().summarize_goldset(cases, owned, tmp_path)
    assert all(r["success_rate"] is None for r in result["groups"])
