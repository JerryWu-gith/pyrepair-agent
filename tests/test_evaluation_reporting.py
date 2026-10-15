from copy import deepcopy


def record(case, trial, passed, *, grade="passed", status="success", complete=True):
    return {
        "case_id": case,
        "trial_index": trial,
        "passed": passed,
        "suite": "regression",
        "split": "dev",
        "agent": {
            "status": status,
            "attempts": 1,
            "duration_seconds": 2,
            "usage": {
                "repair": {"prompt_tokens": 10, "completion_tokens": 2},
                "review": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        },
        "grade": {"status": grade},
        "cost_complete": complete,
        "interrupted_usage": [],
    }


def config():
    return {
        "experiment_id": "test",
        "identity": {
            "trials": 3,
            "model": "example",
            "cases": [
                {"id": "a", "suite": "regression", "split": "dev"},
                {"id": "b", "suite": "regression", "split": "dev"},
            ],
        },
    }


def test_incomplete_experiment_does_not_claim_final_or_stable_rate():
    from benchmarks.evaluation.reporting import summarize

    rows = [
        record("a", 1, True),
        record("a", 2, True),
        record("b", 1, False, grade="hidden_failed"),
        record("b", 2, False, status="error", grade="not_run", complete=False),
    ]
    result = summarize(config(), rows)
    assert result["planned"] == 6
    assert result["completed"] == 4
    assert result["successes"] == 2
    assert result["current_pass_rate"] == 0.5
    assert result["final_pass_rate"] is None
    assert result["stable_cases"] == 0
    assert result["first_attempt_pass_rate"] == 0.5
    assert result["false_positives"] == 1
    assert result["false_positive_denominator"] == 3
    assert result["tokens"]["repair"]["prompt_tokens"] is None
    assert result["known_tokens"]["repair"]["prompt_tokens"] == 40


def test_complete_experiment_reports_all_trials_not_best_only():
    from benchmarks.evaluation.reporting import render_report, summarize

    rows = [record("a", i, True) for i in (1, 2, 3)]
    rows += [
        record("b", 1, True),
        record("b", 2, False, grade="hidden_failed"),
        record("b", 3, False, grade="grader_error"),
    ]
    summary = summarize(config(), rows)
    assert summary["final_pass_rate"] == 4 / 6
    assert summary["stable_cases"] == 1
    assert summary["solved_at_least_once"] == 2
    assert summary["false_positive_denominator"] == 5
    assert summary["false_positives"] == 1
    assert summary["tokens"]["repair"]["prompt_tokens"] == 60
    text = render_report(config(), rows)
    assert "hidden_failed" in text and "grader_error" in text


def test_single_trial_never_claims_repeated_stability():
    from benchmarks.evaluation.reporting import summarize

    experiment = deepcopy(config())
    experiment["identity"]["trials"] = 1
    result = summarize(experiment, [record("a", 1, True), record("b", 1, True)])
    assert result["stable_cases"] is None
