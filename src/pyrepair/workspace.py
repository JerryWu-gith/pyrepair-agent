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
    root: Path  # 临时根目录
    baseline: Path  # 原始快照（永远不变）
    working: Path  # 可修改副本（agent 在这里工作）

    def snapshot(self) -> PatchSnapshot:
        baseline_paths = _snapshot_paths(self.baseline)
        working_paths = _snapshot_paths(self.working)
        changes: list[FileChange] = []
        for relative in sorted(baseline_paths | working_paths):  # 两个集合的并集
            old_path = self.baseline / relative
            new_path = self.working / relative
            old_bytes = old_path.read_bytes() if old_path.exists() else b""  # 先比字节、后解码
            new_bytes = new_path.read_bytes() if new_path.exists() else b""
            if old_bytes == new_bytes:
                continue
            try:
                old = old_bytes.decode("utf-8")  # 解码
                new = new_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceError(f"无法为非 UTF-8 文件生成 Diff：{relative}") from exc

            diff_lines = list(
                difflib.unified_diff(   # difflib.unified_diff 生成 unified diff
                    old.splitlines(keepends=True),  # splitlines() 把文本按行切成列表；keepends=True 表示保留每行的换行符
                    new.splitlines(keepends=True),
                    fromfile=f"a/{relative.as_posix()}",  # fromfile = 旧文件的显示名，tofile = 新文件的显示名
                    tofile=f"b/{relative.as_posix()}",  # relative.as_posix() 把 Path 转成用 / 分隔的字符串
                )
            )
            changes.append(
                FileChange(
                    path=relative.as_posix(),
                    old_text=old,
                    new_text=new,
                    diff="".join(diff_lines),
                    added_lines=sum(
                        line.startswith("+") and not line.startswith("+++")  # 排除掉 +++ 开头的文件头行（那是 fromfile/tofile 标记，不是真正的加行
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
        shutil.rmtree(self.working)  # 删掉 working
        shutil.copytree(self.baseline, self.working)  # 从 baseline 重拷

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)  # 删除整个临时目录


class WorkspaceManager:  # 沙箱工厂
    def create(self, repo: Path) -> WorkspaceSession:
        source = repo.resolve()  # 变成标准化的绝对路径
        if not source.is_dir():
            raise WorkspaceError(f"目标目录不存在：{source}")
        if not _contains_python_source(source):
            raise WorkspaceError(f"目标目录中没有可处理的 Python 文件：{source}")

        root = Path(tempfile.mkdtemp(prefix="pyrepair-"))  # 建临时根目录
        baseline = root / "baseline"
        working = root / "working"
        try:
            shutil.copytree(source, baseline, ignore=_ignore_excluded)  # 把仓库复制进 baseline，同时排除无关目录
            shutil.copytree(baseline, working)  # 从 baseline 再复制一份成 working
        except Exception as exc:
            shutil.rmtree(root, ignore_errors=True)
            raise WorkspaceError(f"创建临时工作区失败：{exc}") from exc
        return WorkspaceSession(root=root, baseline=baseline, working=working)


def _contains_python_source(repo: Path) -> bool:
    for path in repo.rglob("*.py"):  # rglob 从 root 往下递归列出所有条目，* 匹配任意名字
        relative = path.relative_to(repo)  # 转成相对路径，baseline 和 working 是同一个仓库的两份拷贝，相对路径是"同一个逻辑文件"在这两棵树里的坐标——比较时靠它对齐
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
