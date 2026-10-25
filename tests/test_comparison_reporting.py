"""Reports describe the selected schedule, never the parent pack's unused trials."""

import pytest

from benchmarks.evaluation.comparison_reporting import render_comparison, summarize_comparison
from tests.test_comparison_journal import owned_pack


def test_smoke_report_uses_selected_pair_not_parent_three_trial_configuration():
    pack = owned_pack(1, 3)
    pack["identity"]["config"] = {"trials": 3}
    pack["identity"]["slots"] = pack["identity"]["slots"][:2]

    summary = summarize_comparison(pack, [], execution_mode="smoke")
    report = render_comparison(summary)

    assert summary["planned"] == summary["unrun"] == 2
    assert summary["finished"] == 0
    assert summary["kind"].startswith("SMOKE")
    assert "1 task(s)" in report
    assert "scheduled trials per task: 1" in report
    assert "not a formal repeated evaluation" in report
    assert "three repeats" not in report


def test_formal_report_describes_planned_trials_without_claiming_completion():
    summary = summarize_comparison(owned_pack(20, 3), [], execution_mode="formal")
    report = render_comparison(summary)

    assert summary["planned"] == summary["unrun"] == 120
    assert summary["finished"] == 0
    assert "20 task(s)" in report
    assert "scheduled trials per task: 3" in report
    assert "Planned 120; finished 0; unrun 120" in report
    assert not summary["kind"].startswith("SMOKE")


@pytest.mark.parametrize("trials", [2, 5])
def test_default_reporting_does_not_assume_three_repeats(trials):
    summary = summarize_comparison(owned_pack(1, trials), [])

    assert f"scheduled trials per task: {trials}" in render_comparison(summary)
    assert "three repeats" not in summary["limitations"]


def test_simulation_keeps_unmeasured_results_with_smoke_scope():
    summary = summarize_comparison(owned_pack(), [], simulation=True, execution_mode="smoke")

    assert summary["kind"].startswith("SIMULATION")
    assert summary["real_model_trials"] == 0
    assert all(group["success_rate"] is None for group in summary["groups"])
    assert "scheduled trials per task: 1" in render_comparison(summary)


def test_invalid_reporting_execution_mode_is_rejected():
    with pytest.raises(ValueError, match="execution mode"):
        summarize_comparison(owned_pack(), [], execution_mode="unexpected")
