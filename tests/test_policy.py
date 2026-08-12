import pytest

from pyrepair.models import FileChange, PatchSnapshot
from pyrepair.policy import PatchPolicyGate


def make_change(
    path: str,
    old_text: str = "value = 1\n",
    new_text: str = "value = 2\n",
    added_lines: int = 1,
    deleted_lines: int = 1,
) -> FileChange:
    return FileChange(path, old_text, new_text, "candidate diff", added_lines, deleted_lines)


def make_snapshot(*changes: FileChange) -> PatchSnapshot:
    return PatchSnapshot(changes)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_app.py",
        "test_app.py",
        ".env",
        ".env.local",
        "config/secrets.json",
        "keys/private.pem",
        "id_rsa",
        ".github/workflows/ci.yml",
        ".gitlab-ci.yml",
        "azure-pipelines.yml",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
        "requirements.lock",
    ],
)
def test_policy_rejects_protected_paths(path):
    check = PatchPolicyGate().check(make_snapshot(make_change(path)))

    assert check.allowed is False
    assert any(item.startswith("protected_path:") for item in check.violations)


@pytest.mark.parametrize(
    "new_text",
    [
        "import pytest\npytest.skip('later')\n",
        "import pytest\npytest.xfail('later')\n",
        "@pytest.mark.skip\ndef test_something(): ...\n",
        "@pytest.mark.xfail\ndef test_something(): ...\n",
    ],
)
def test_policy_rejects_new_test_bypass(new_text):
    change = make_change("src/app.py", old_text="value = 1\n", new_text=new_text)

    check = PatchPolicyGate().check(make_snapshot(change))

    assert "test_bypass:src/app.py" in check.violations


def test_policy_does_not_reject_unchanged_preexisting_skip():
    old = "import pytest\npytest.skip('unsupported platform')\nvalue = 1\n"
    new = "import pytest\npytest.skip('unsupported platform')\nvalue = 2\n"

    check = PatchPolicyGate().check(make_snapshot(make_change("src/app.py", old, new)))

    assert all(not item.startswith("test_bypass:") for item in check.violations)


def test_policy_rejects_removed_or_weakened_assertions():
    removed = make_change("src/checks.py", "assert value == 3\n", "value = 3\n")
    weakened = make_change("src/checks.py", "assert value == 3\n", "assert value\n")

    removed_check = PatchPolicyGate().check(make_snapshot(removed))
    weakened_check = PatchPolicyGate().check(make_snapshot(weakened))

    assert "assertion_weakened:src/checks.py" in removed_check.violations
    assert "assertion_weakened:src/checks.py" in weakened_check.violations


def test_policy_rejects_more_than_three_files_and_eighty_lines():
    changes = tuple(make_change(f"src/module_{index}.py", added_lines=20, deleted_lines=1) for index in range(4))

    check = PatchPolicyGate().check(make_snapshot(*changes))

    assert "too_many_files:4>3" in check.violations
    assert "too_many_changed_lines:84>80" in check.violations


@pytest.mark.parametrize(
    "path",
    ["../outside.py", "/absolute.py", "C:\\outside.py", "docs/readme.md"],
)
def test_policy_rejects_path_escape_absolute_and_non_source(path):
    check = PatchPolicyGate().check(make_snapshot(make_change(path)))

    assert check.allowed is False
    assert any(
        item.startswith(("path_outside_workspace:", "non_source_file:"))
        for item in check.violations
    )


def test_policy_allows_small_source_only_fix_and_reports_stats():
    change = make_change(
        "src/account.py",
        "if balance > amount:\n",
        "if balance >= amount:\n",
        added_lines=1,
        deleted_lines=1,
    )

    check = PatchPolicyGate().check(make_snapshot(change))

    assert check.allowed is True
    assert check.violations == ()
    assert check.changed_files == ("src/account.py",)
    assert check.added_lines == 1
    assert check.deleted_lines == 1
