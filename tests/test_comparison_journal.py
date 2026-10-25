import json

import pytest

from benchmarks.evaluation.comparison_pack import paired_slots
from benchmarks.evaluation.experiment import digest


def owned_pack(count=1, trials=1):
    ids = [f"case_{i:02d}" for i in range(count)]
    identity = {
        "authorization": "offline-only",
        "slots": paired_slots(ids, trials),
        "cases": [{"id": c, "source_kind": "synthetic"} for c in ids],
    }
    return {"identity": identity, "identity_hash": digest(identity)}


def candidate(slot, folder):
    return {
        "status": "candidate",
        "patch": "owned candidate",
        "internal_success": True,
        "duration_seconds": 1.0,
    }


def test_120_simulated_slots_cannot_be_presented_as_real_performance(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots
    from benchmarks.evaluation.comparison_reporting import summarize_comparison

    pack = owned_pack(20, 3)
    records = run_slots(
        pack, tmp_path / "run", candidate, lambda *args: {"status": "passed"}, simulation=True
    )
    summary = summarize_comparison(pack, records, simulation=True)
    assert len(records) == 120
    assert summary["planned"] == summary["finished"] == 120
    assert summary["real_model_trials"] == 0
    assert all(group["success_rate"] is None for group in summary["groups"])


def test_ordinary_failure_continues_but_technical_failure_pauses(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots
    from benchmarks.evaluation.comparison_reporting import summarize_comparison

    pack = owned_pack(2, 1)

    def grade(slot, result, folder):
        return {
            "status": "hidden_failed" if slot["method"] == "single-shot" else "environment_error"
        }

    records = run_slots(pack, tmp_path / "run", candidate, grade)
    assert len(records) == 2
    assert [r["status"] for r in records] == ["failed", "technical_error"]
    summary = summarize_comparison(pack, records)
    assert summary["planned"] == 4
    assert summary["unrun"] == 2
    # The Agent's grader crashed: this is unknown acceptance, not a business rejection.
    assert sum(g["internal_success_rejected"] for g in summary["groups"]) == 0

    def forbidden(*args):
        pytest.fail("paused/terminal slots must not invoke another model")

    assert run_slots(pack, tmp_path / "run", forbidden, forbidden) == records


def test_grader_interruption_reuses_candidate_without_executor(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots

    pack = owned_pack()

    def interrupt(*args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_slots(pack, tmp_path / "run", candidate, interrupt)

    def executor(slot, folder):
        if slot["method"] == "single-shot":
            pytest.fail("completed candidate must not consume a second response")
        return candidate(slot, folder)

    records = run_slots(pack, tmp_path / "run", executor, lambda *args: {"status": "passed"})
    assert len(records) == 2
    assert all(r["passed"] for r in records)


def test_started_without_candidate_is_not_silently_reexecuted(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots

    pack = owned_pack()

    def interrupt(*args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_slots(pack, tmp_path / "run", interrupt, interrupt)

    def forbidden(*args):
        pytest.fail("must not refill the interrupted slot")

    records = run_slots(pack, tmp_path / "run", forbidden, forbidden)
    assert len(records) == 1
    assert records[0]["status"] == "technical_error"
    assert records[0]["error_type"] == "interrupted_without_candidate"


def test_candidate_saved_just_before_crash_is_recovered_locally(tmp_path):
    from benchmarks.evaluation.comparison_budget import write_new
    from benchmarks.evaluation.comparison_journal import run_slots

    pack = owned_pack()

    def crash(slot, folder):
        write_new(folder / "candidate.json", candidate(slot, folder))
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_slots(pack, tmp_path / "run", crash, lambda *args: {"status": "passed"})
    records = run_slots(pack, tmp_path / "run", candidate, lambda *args: {"status": "passed"})
    assert len(records) == 2
    assert len(list((tmp_path / "run/s0000").glob("candidate.json"))) == 1


def test_tampered_candidate_is_rejected_on_resume(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots

    pack = owned_pack()

    def interrupt(*args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_slots(pack, tmp_path / "run", candidate, interrupt)
    path = tmp_path / "run/s0000/candidate.json"
    changed = json.loads(path.read_text("utf-8"))
    changed["patch"] = "tampered"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate"):
        run_slots(pack, tmp_path / "run", candidate, interrupt)


def test_simulation_flag_cannot_be_changed_on_resume(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots

    pack = owned_pack()
    run_slots(
        pack, tmp_path / "run", candidate, lambda *args: {"status": "passed"}, simulation=True
    )
    with pytest.raises(ValueError, match="identity"):
        run_slots(pack, tmp_path / "run", candidate, lambda *args: {"status": "passed"})


def test_single_shot_saved_response_is_parsed_locally_without_second_call(tmp_path):
    from dataclasses import asdict

    from benchmarks.evaluation.comparison_budget import write_new
    from benchmarks.evaluation.comparison_journal import run_slots
    from pyrepair.models import ModelTurn
    from tests.test_comparison_methods import PATCH

    pack = owned_pack()

    def respond_then_interrupt(slot, folder):
        write_new(
            folder / "responses/response-000001.json",
            asdict(ModelTurn(PATCH, None, (), 9, 3, "stop")),
        )
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_slots(
            pack, tmp_path / "run", respond_then_interrupt, lambda *args: {"status": "passed"}
        )

    def executor(slot, folder):
        assert slot["method"] != "single-shot"
        return candidate(slot, folder)

    records = run_slots(pack, tmp_path / "run", executor, lambda *args: {"status": "passed"})
    assert len(records) == 2
    assert json.loads((tmp_path / "run/s0000/candidate.json").read_text("utf-8"))["patch"] == PATCH


def test_internal_agent_success_rejected_counts_only_actual_failed_acceptance(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots
    from benchmarks.evaluation.comparison_reporting import summarize_comparison

    pack = owned_pack(2, 1)

    def grade(slot, result, folder):
        return {"status": "hidden_failed" if slot["method"] == "full-agent" else "passed"}

    records = run_slots(pack, tmp_path / "run", candidate, grade)
    summary = summarize_comparison(pack, records)
    assert sum(g["internal_success_rejected"] for g in summary["groups"]) == 2


def test_terminal_record_cannot_override_independent_saved_grade(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots

    pack = owned_pack()
    root = tmp_path / "run"
    run_slots(pack, root, candidate, lambda *args: {"status": "hidden_failed"})
    journal = root / "journal.jsonl"
    events = [json.loads(line) for line in journal.read_text("utf-8").splitlines()]
    terminal = next(e for e in events if e["event"] == "terminal")
    terminal["data"].update(status="passed", passed=True, grade={"status": "passed"})
    journal.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact"):
        run_slots(pack, root, candidate, lambda *args: {"status": "passed"})


def test_journal_cannot_reorder_frozen_slots_even_if_each_transition_is_valid(tmp_path):
    from benchmarks.evaluation.comparison_journal import run_slots

    pack = owned_pack()
    root = tmp_path / "run"
    run_slots(pack, root, candidate, lambda *args: {"status": "passed"})
    journal = root / "journal.jsonl"
    events = [json.loads(line) for line in journal.read_text("utf-8").splitlines()]
    first = pack["identity"]["slots"][0]["slot"]
    swapped = [e for e in events if e["slot"] != first] + [e for e in events if e["slot"] == first]
    journal.write_text("".join(json.dumps(e) + "\n" for e in swapped), encoding="utf-8")
    with pytest.raises(ValueError, match="order"):
        run_slots(pack, root, candidate, lambda *args: {"status": "passed"})


def test_report_contains_paired_differences_and_explicit_unknown_role_usage(tmp_path):
    from benchmarks.evaluation.comparison_budget import CallBudget, GuardedClient, read_usage
    from benchmarks.evaluation.comparison_journal import run_slots
    from benchmarks.evaluation.comparison_reporting import render_comparison, summarize_comparison
    from tests.test_comparison_budget import Reply

    pack = owned_pack()
    records = run_slots(
        pack,
        tmp_path / "run",
        candidate,
        lambda slot, *args: {
            "status": "hidden_failed" if slot["method"] == "single-shot" else "passed"
        },
    )
    budget = CallBudget(tmp_path / "budget", 2)
    GuardedClient(Reply(), budget, "case_00--1--full-agent", "repair", 36, tmp_path / "r").complete(
        [], []
    )
    budget.reserve("case_00--1--full-agent", "review", 36)
    summary = summarize_comparison(pack, records, usage=read_usage(tmp_path / "budget"))
    assert summary["paired_cases"][0]["agent_minus_single_accepted"] == 1
    assert summary["paired_cases"][0]["trials"][0]["delta"] == 1
    assert summary["usage"]["roles"]["repair"]["prompt_tokens"] == 10
    assert summary["usage"]["roles"]["review"]["prompt_tokens"] is None
    assert summary["usage"]["reserved_calls"] == 2
    assert summary["usage"]["responses"] == 1
    assert "review" in render_comparison(summary)
