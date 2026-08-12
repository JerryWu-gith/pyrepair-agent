from __future__ import annotations

import difflib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import FileChange, PatchSnapshot

EXCLUDED_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyrepair",
    ".worktrees",
    "worktrees",
}


class WorkspaceError(RuntimeError):
    """Raised when an isolated repair workspace cannot be prepared."""


@dataclass
class WorkspaceSession:
    root: Path
    baseline: Path
    working: Path

    def snapshot(self) -> PatchSnapshot:
        baseline_paths = _snapshot_paths(self.baseline)
        working_paths = _snapshot_paths(self.working)
        changes: list[FileChange] = []
        for relative in sorted(baseline_paths | working_paths):
            old_path = self.baseline / relative
            new_path = self.working / relative
            old_bytes = old_path.read_bytes() if old_path.exists() else b""
            new_bytes = new_path.read_bytes() if new_path.exists() else b""
            if old_bytes == new_bytes:
                continue
            try:
                old = old_bytes.decode("utf-8")
                new = new_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceError(f"无法为非 UTF-8 文件生成 Diff：{relative}") from exc

            diff_lines = list(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile=f"a/{relative.as_posix()}",
                    tofile=f"b/{relative.as_posix()}",
                )
            )
            changes.append(
                FileChange(
                    path=relative.as_posix(),
                    old_text=old,
                    new_text=new,
                    diff="".join(diff_lines),
                    added_lines=sum(
                        line.startswith("+") and not line.startswith("+++")
                        for line in diff_lines
                    ),
                    deleted_lines=sum(
                        line.startswith("-") and not line.startswith("---")
                        for line in diff_lines
                    ),
                )
            )
        return PatchSnapshot(tuple(changes))

    def restore_working_from_baseline(self) -> None:
        shutil.rmtree(self.working)
        shutil.copytree(self.baseline, self.working)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)


class WorkspaceManager:
    def create(self, repo: Path) -> WorkspaceSession:
        source = repo.resolve()
        if not source.is_dir():
            raise WorkspaceError(f"目标目录不存在：{source}")
        if not _contains_python_source(source):
            raise WorkspaceError(f"目标目录中没有可处理的 Python 文件：{source}")

        root = Path(tempfile.mkdtemp(prefix="pyrepair-"))
        baseline = root / "baseline"
        working = root / "working"
        try:
            shutil.copytree(source, baseline, ignore=_ignore_excluded)
            shutil.copytree(baseline, working)
        except Exception as exc:
            shutil.rmtree(root, ignore_errors=True)
            raise WorkspaceError(f"创建临时工作区失败：{exc}") from exc
        return WorkspaceSession(root=root, baseline=baseline, working=working)


def _contains_python_source(repo: Path) -> bool:
    for path in repo.rglob("*.py"):
        relative = path.relative_to(repo)
        if path.is_file() and not any(part in EXCLUDED_NAMES for part in relative.parts):
            return True
    return False


def _snapshot_paths(root: Path) -> set[Path]:
    paths: set[Path] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_file() and not any(part in EXCLUDED_NAMES for part in relative.parts):
            paths.add(relative)
    return paths


def _ignore_excluded(directory: str, names: list[str]) -> set[str]:
    del directory
    return {name for name in names if name in EXCLUDED_NAMES}
