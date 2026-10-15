import json
from dataclasses import replace

import pytest

from tests.evaluation_helpers import make_case, patch


@pytest.fixture
def case(tmp_path):
    from benchmarks.evaluation.cases import load_cases

    return load_cases(make_case(tmp_path / "bank"))[0]


def test_gold_patch_passes_in_clean_copy_and_original_is_unchanged(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    before = (case.buggy / "src/app.py").read_bytes()
    result = grade_patch(case, case.gold_patch.read_text(), tmp_path / "grade")
    assert result["status"] == "passed"
    assert result["visible"]["passed"] is True
    assert result["hidden"]["passed"] is True
    assert (case.buggy / "src/app.py").read_bytes() == before
    assert json.loads((tmp_path / "grade/grade.json").read_text())["status"] == "passed"
    assert (tmp_path / "grade/hidden.log").is_file()


def test_constant_patch_is_rejected_by_hidden_tests(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    result = grade_patch(case, case.wrong_patch.read_text(), tmp_path / "grade")
    assert result["status"] == "hidden_failed"
    assert result["visible"]["passed"] is True
    assert result["hidden"]["passed"] is False


@pytest.mark.parametrize(
    "text",
    [
        "--- a/../escape.py\n+++ b/../escape.py\n@@ -1 +1 @@\n-x\n+y\n",
        "--- a/tests/test_app.py\n+++ b/tests/test_app.py\n@@ -1 +1 @@\n-x\n+y\n",
        "diff --git a/src/app.py b/src/renamed.py\nsimilarity index 100%\nrename from src/app.py\n",
        "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-wrong context\n+pass\n",
        "GIT binary patch\nliteral 1\n",
    ],
)
def test_unsafe_or_inapplicable_patch_never_runs_tests(case, tmp_path, text):
    from benchmarks.evaluation.grading import grade_patch

    result = grade_patch(case, text, tmp_path / "grade")
    assert result["status"] == "patch_rejected"
    assert result["visible"] is None


def test_empty_patch_has_explicit_status(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    assert grade_patch(case, "", tmp_path / "grade")["status"] == "no_patch"


@pytest.mark.parametrize(
    "body",
    [
        (
            "import pytest\npytestmark = pytest.mark.skip(reason='bypass')\n"
            "def test_other(): pass\ndef test_zero(): pass\n"
        ),
        (
            "import pytest\n@pytest.mark.xfail\ndef test_other(): assert False\n"
            "def test_zero(): pass\n"
        ),
        "def test_unrelated(): pass\n",
        "# nothing collected\n",
    ],
)
def test_skipped_xfailed_missing_and_empty_tests_cannot_pass(case, tmp_path, body):
    from benchmarks.evaluation.grading import grade_patch

    (case.private / "hidden_tests/test_hidden.py").write_text(body)
    result = grade_patch(case, case.gold_patch.read_text(), tmp_path / "grade")
    assert result["status"] == "hidden_failed"


def test_candidate_import_error_is_test_failure_not_environment_error(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    old = (case.buggy / "src/app.py").read_text()
    result = grade_patch(
        case, patch(old, "import definitely_nonexistent_dependency\n"), tmp_path / "grade"
    )
    assert result["status"] == "visible_failed"


def test_grader_does_not_pass_model_credentials_to_candidate(case, tmp_path, monkeypatch):
    from benchmarks.evaluation.grading import grade_patch

    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-canary")
    monkeypatch.setenv("OPENAI_API_KEY", "another-canary")
    hidden = case.private / "hidden_tests/test_hidden.py"
    hidden.write_text(
        hidden.read_text() + "\ndef test_no_credentials():\n"
        "    import os\n"
        "    assert 'DEEPSEEK_API_KEY' not in os.environ\n"
        "    assert 'OPENAI_API_KEY' not in os.environ\n"
    )
    assert grade_patch(case, case.gold_patch.read_text(), tmp_path / "grade")["status"] == "passed"


def test_timeout_is_not_a_pass(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    old = (case.buggy / "src/app.py").read_text()
    text = patch(old, "import time\ndef add(a, b):\n    time.sleep(10)\n    return a + b\n")
    result = grade_patch(replace(case, timeout_seconds=1), text, tmp_path / "grade")
    assert result["status"] == "timeout"


def test_malformed_probe_output_fails_closed(tmp_path):
    from benchmarks.evaluation.grading import read_probe

    path = tmp_path / "probe.json"
    path.write_text('{"version":1,"collected":[],"reports":[],"exit_code":0}')
    with pytest.raises(ValueError):
        read_probe(path)
    path.write_text("{")
    with pytest.raises(ValueError):
        read_probe(path)


def test_candidate_mutating_its_own_source_is_rejected(case, tmp_path):
    from benchmarks.evaluation.grading import grade_patch

    old = (case.buggy / "src/app.py").read_text()
    new = (
        "from pathlib import Path\n"
        "def add(a, b):\n"
        "    path = Path(__file__)\n"
        "    path.write_text(path.read_text() + '\\n# changed')\n"
        "    return a + b\n"
    )
    result = grade_patch(case, patch(old, new), tmp_path / "grade")
    assert result["status"] == "patch_rejected"
