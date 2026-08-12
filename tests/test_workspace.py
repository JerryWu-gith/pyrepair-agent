from pathlib import Path

import pytest

from pyrepair.workspace import WorkspaceError, WorkspaceManager


def make_python_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    return repo


def test_workspace_changes_do_not_touch_source(tmp_path):
    repo = make_python_repo(tmp_path)
    session = WorkspaceManager().create(repo)

    (session.working / "app.py").write_text("value = 2\n", encoding="utf-8")
    snapshot = session.snapshot()

    assert (repo / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    assert snapshot.changes[0].path == "app.py"
    assert "+value = 2" in snapshot.text
    assert snapshot.changes[0].added_lines == 1
    assert snapshot.changes[0].deleted_lines == 1
    session.cleanup()


def test_workspace_excludes_git_env_cache_and_nested_worktrees(tmp_path):
    repo = make_python_repo(tmp_path)
    excluded = (".git", ".venv", "__pycache__", ".pyrepair", ".worktrees")
    for name in excluded:
        directory = repo / name
        directory.mkdir()
        (directory / "ignored.txt").write_text("ignored", encoding="utf-8")

    session = WorkspaceManager().create(repo)

    assert all(not (session.working / name).exists() for name in excluded)
    session.cleanup()


def test_workspace_rejects_repo_without_python(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "README.md").write_text("no source", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="Python"):
        WorkspaceManager().create(repo)


def test_workspace_rejects_missing_directory(tmp_path):
    with pytest.raises(WorkspaceError, match="不存在"):
        WorkspaceManager().create(tmp_path / "missing")


def test_restore_discards_previous_attempt_and_cleanup_removes_root(tmp_path):
    repo = make_python_repo(tmp_path)
    session = WorkspaceManager().create(repo)
    root = session.root
    (session.working / "app.py").write_text("changed = True\n", encoding="utf-8")

    session.restore_working_from_baseline()

    assert (session.working / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    session.cleanup()
    assert root.exists() is False


def test_snapshot_tracks_added_and_deleted_files(tmp_path):
    repo = make_python_repo(tmp_path)
    (repo / "old.py").write_text("old = True\n", encoding="utf-8")
    session = WorkspaceManager().create(repo)
    (session.working / "old.py").unlink()
    (session.working / "new.py").write_text("new = True\n", encoding="utf-8")

    snapshot = session.snapshot()

    changes = {change.path: change for change in snapshot.changes}
    assert set(changes) == {"new.py", "old.py"}
    assert changes["new.py"].added_lines == 1
    assert changes["new.py"].deleted_lines == 0
    assert changes["old.py"].added_lines == 0
    assert changes["old.py"].deleted_lines == 1
    session.cleanup()


def test_snapshot_rejects_non_utf8_changes_with_workspace_error(tmp_path):
    repo = make_python_repo(tmp_path)
    session = WorkspaceManager().create(repo)
    (session.working / "app.py").write_bytes(b"\xff\xfe")

    with pytest.raises(WorkspaceError, match="非 UTF-8"):
        session.snapshot()

    session.cleanup()
