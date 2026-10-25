"""Editing must not turn a local repair into a whole-file newline rewrite."""

import pytest

from pyrepair.policy import PatchPolicyGate
from pyrepair.tools import ReplaceTextTool, ShowDiffTool
from pyrepair.workspace import WorkspaceManager


@pytest.mark.parametrize(
    ("original", "old_text", "new_text", "expected"),
    [
        (b"x = 1\ny = 2\n", "x = 1", "x = 3", b"x = 3\ny = 2\n"),
        (b"x = 1\r\ny = 2\r\n", "x = 1", "x = 3", b"x = 3\r\ny = 2\r\n"),
        (
            b"def add(a, b):\r\n    return a - b\r\n# end\r\n",
            "def add(a, b):\n    return a - b",
            "def add(a, b):\n    value = a + b\n    return value",
            b"def add(a, b):\r\n    value = a + b\r\n    return value\r\n# end\r\n",
        ),
        (
            b"x = 1\ny = 2\n",
            "x = 1\r\ny = 2",
            "x = 3\r\ny = 4",
            b"x = 3\ny = 4\n",
        ),
        (
            b"# first\r\nx = 1\ny = 2\r# last\n",
            "x = 1",
            "x = 3",
            b"# first\r\nx = 3\ny = 2\r# last\n",
        ),
        (
            b"# first\nx = 1\r\ny = 2\n# last\r",
            "x = 1\ny = 2",
            "x = 3\ny = 4",
            b"# first\nx = 3\r\ny = 4\n# last\r",
        ),
        (b"x = 1\ry = 2\r", "x = 1\ny = 2", "x = 3\ny = 4", b"x = 3\ry = 4\r"),
        (b"x = 1\ny = 2", "x = 1", "x = 3", b"x = 3\ny = 2"),
        (b"x = 1\r\ny = 2", "x = 1", "x = 3", b"x = 3\r\ny = 2"),
        (b"x = 1", "x = 1", "x = 3\ny = 4", b"x = 3\ny = 4"),
        (
            b"x = 1\r\ny = 2\r\n",
            "x = 1",
            "x = 3\r\nz = 4",
            b"x = 3\r\nz = 4\r\ny = 2\r\n",
        ),
        (
            b"# keep\r\nx = 1\ny = 2\r\n# end\n",
            "x = 1\ny = 2\n",
            "",
            b"# keep\r\n# end\n",
        ),
        (
            "\ufeff# 中文\nx = '旧'\n# 保留".encode(),
            "'旧'",
            "'新'",
            "\ufeff# 中文\nx = '新'\n# 保留".encode(),
        ),
    ],
    ids=[
        "lf",
        "crlf",
        "crlf-multiline-from-model-lf",
        "lf-multiline-from-crlf-input",
        "mixed-unedited-bytes",
        "mixed-span-uses-its-first-newline",
        "legacy-cr",
        "lf-no-final-newline",
        "crlf-no-final-newline",
        "no-newline-defaults-to-lf",
        "explicit-crlf-is-not-doubled",
        "delete-multiline",
        "utf8-bom-and-unicode",
    ],
)
def test_replace_text_preserves_source_newlines(tmp_path, original, old_text, new_text, expected):
    path = tmp_path / "app.py"
    path.write_bytes(original)

    result = ReplaceTextTool(tmp_path).execute(
        {"path": "app.py", "old_text": old_text, "new_text": new_text}
    )

    assert result.ok is True
    assert path.read_bytes() == expected


@pytest.mark.parametrize(
    "old_text, matches", [("missing", 0), ("x = 1\ny = 2", 2), ("\n\n", 0), ("\n", 4)]
)
def test_newline_matching_still_requires_exactly_one_literal_occurrence(
    tmp_path, old_text, matches
):
    path = tmp_path / "app.py"
    original = b"x = 1\r\ny = 2\r\nx = 1\ny = 2\n"
    path.write_bytes(original)

    result = ReplaceTextTool(tmp_path).execute(
        {"path": "app.py", "old_text": old_text, "new_text": "x = 3"}
    )

    assert result.ok is False
    assert result.error.code == "expected_one_match"
    assert result.metadata["matches"] == matches
    assert path.read_bytes() == original


def test_replace_text_does_not_interpret_regex_or_replacement_escapes(tmp_path):
    path = tmp_path / "app.py"
    path.write_bytes(b"value = r'[a]+\\1'\n# unchanged\n")

    result = ReplaceTextTool(tmp_path).execute(
        {"path": "app.py", "old_text": "[a]+\\1", "new_text": "[b]*\\2"}
    )

    assert result.ok is True
    assert path.read_bytes() == b"value = r'[b]*\\2'\n# unchanged\n"


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_one_line_repair_in_large_file_has_minimal_diff_and_passes_unchanged_policy(
    tmp_path, newline
):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "app.py"
    original = newline.join([b"# unchanged"] * 200 + [b"value = 1", b""])
    path.write_bytes(original)
    session = WorkspaceManager().create(repo)
    try:
        result = ReplaceTextTool(session.working).execute(
            {"path": "app.py", "old_text": "value = 1", "new_text": "value = 2"}
        )
        snapshot = session.snapshot()
        check = PatchPolicyGate().check(snapshot)
        diff = ShowDiffTool(session).execute({})

        assert result.ok is True
        assert len(snapshot.changes) == 1
        assert (check.added_lines, check.deleted_lines) == (1, 1)
        assert check.allowed is True
        assert diff.data["added_lines"] == diff.data["deleted_lines"] == 1
        assert diff.data["truncated"] is False
        assert path.read_bytes() == original
        assert (session.baseline / "app.py").read_bytes() == original
        assert (session.working / "app.py").read_bytes() == (
            newline.join([b"# unchanged"] * 200 + [b"value = 2", b""])
        )
        session.restore_working_from_baseline()
        assert (session.working / "app.py").read_bytes() == original
        assert session.snapshot().changes == ()
    finally:
        session.cleanup()
