"""Public-only evaluation inputs. Never import or execute repository modules."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from pyrepair.context_builder import validate_task_contract
from pyrepair.policy import _is_protected

from . import container_protocol as protocol
from .cases import EXCLUDED, EvaluationCase, contained

INPUT_POLICY = "agent-public-r2"
_EXCLUDED_PARTS = frozenset(
    p.casefold()
    for p in (*EXCLUDED, "worktrees", ".mypy_cache", ".omp", ".agents", ".claude", ".codex")
)
_INSTRUCTION_FILES = frozenset({"agents.md", "claude.md", "gemini.md", "skill.md"})
_FIELDS = frozenset(
    {
        "version",
        "case_id",
        "revision",
        "source_kind",
        "visible_tests",
        "timeout_seconds",
        "input_policy",
        "public_input_hash",
    }
)


def _validate_payload(value: dict) -> None:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("invalid public descriptor fields")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("invalid public descriptor version")
    identity = value["case_id"]
    if (
        not isinstance(identity, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", identity) is None
    ):
        raise ValueError("invalid public case identity")
    protocol.safe_path(identity)
    if type(value["revision"]) is not int or value["revision"] < 1:
        raise ValueError("invalid public revision")
    if value["source_kind"] not in ("synthetic", "opensource"):
        raise ValueError("invalid public source kind")
    if type(value["timeout_seconds"]) is not int or not 0 < value["timeout_seconds"] <= 120:
        raise ValueError("invalid public timeout")
    tests = value["visible_tests"]
    if not isinstance(tests, list) or not 0 < len(tests) <= 10000:
        raise ValueError("invalid public test files")
    for name in tests:
        protocol.safe_path(name)
        if not name.endswith(".py") or _excluded(name):
            raise ValueError("invalid or filtered public test file")
    if len({name.casefold() for name in tests}) != len(tests):
        raise ValueError("duplicate public test file")
    if value["input_policy"] != INPUT_POLICY:
        raise ValueError("unverified public input policy")
    digest = value["public_input_hash"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid public input digest")


@dataclass(frozen=True)
class PublicTaskSpec:
    version: int
    case_id: str
    revision: int
    source_kind: str
    visible_tests: tuple[str, ...]
    timeout_seconds: int
    input_policy: str
    public_input_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.visible_tests, tuple):
            raise TypeError("public test files must be immutable")
        _validate_payload(self.to_dict())

    def to_dict(self) -> dict:
        value = asdict(self)
        value["visible_tests"] = list(self.visible_tests)
        return value

    @classmethod
    def from_dict(cls, value: dict) -> PublicTaskSpec:
        _validate_payload(value)
        return cls(**{**value, "visible_tests": tuple(value["visible_tests"])})


def _excluded(name: str) -> bool:
    parts = tuple(p.casefold() for p in name.split("/"))
    return (
        any(p in _EXCLUDED_PARTS or p.startswith(".env") for p in parts)
        or parts[-1] in _INSTRUCTION_FILES
        or Path(name).suffix.casefold() in {".pyc", ".pyo"}
    )


def stage_public_snapshot(
    repo: Path,
    destination: Path,
    visible_tests: tuple[str, ...],
    *,
    required_paths: tuple[str, ...] = (),
) -> dict:
    """Copy an exclusively owned filtered snapshot; retain failed outputs as evidence."""
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    protocol.checked_root(repo)
    if destination.resolve().is_relative_to(repo.resolve()) or repo.resolve().is_relative_to(
        destination.resolve()
    ):
        raise ValueError("snapshot roots overlap or destination is inside repository")
    if any(protocol.is_link(p) for p in (destination, *destination.parents)):
        raise ValueError("linked snapshot destination")
    if not visible_tests:
        raise ValueError("required public tests are missing")
    for name in (*visible_tests, *required_paths):
        protocol.safe_path(name)
        if _excluded(name):
            raise ValueError("required file would be filtered")
        if not (repo / name).is_file():
            raise ValueError("required public file is missing")
    destination.mkdir(parents=True, exist_ok=False)
    inventory, excluded = {}, []
    total = 0
    for source in sorted(repo.rglob("*")):
        if protocol.is_link(source):
            raise ValueError("linked public input")
        name = source.relative_to(repo).as_posix()
        if _excluded(name):
            excluded.append(name)
            continue
        info = source.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        protocol.safe_path(name)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("public input must be ordinary unlinked files")
        limit = min(protocol.MAX_INPUT_FILE, protocol.MAX_INPUT_TOTAL - total)
        with source.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit or len(inventory) >= protocol.MAX_INPUT_FILES:
            raise ValueError("public input size or count limit exceeded")
        total += len(data)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        inventory[name] = hashlib.sha256(data).hexdigest()
    if protocol.input_inventory(destination, visible_tests) != inventory:
        raise ValueError("public snapshot copy changed")
    return {
        "inventory": inventory,
        "excluded": excluded,
        "input_policy": INPUT_POLICY,
        "public_input_hash": protocol.inventory_hash(inventory),
    }


def public_task_contract(case: EvaluationCase) -> str:
    """Disclose the grader's exact edit scope, using only public metadata and text."""
    paths = case.allowed_source_paths
    if not isinstance(paths, tuple) or not paths:
        raise ValueError("public edit scope must not be empty")
    for name in paths:
        protocol.safe_path(name)
        path = contained(case.buggy, name)
        if (
            _excluded(name)
            or not path.is_file()
            or path.suffix not in {".py", ".pyi"}
            or _is_protected(PurePosixPath(name))
        ):
            raise ValueError("invalid public edit source")
    if len({name.casefold() for name in paths}) != len(paths):
        raise ValueError("duplicate public edit source")
    with case.description.open("rb") as stream:
        raw = stream.read(protocol.MAX_INPUT_FILE + 1)
    if len(raw) > protocol.MAX_INPUT_FILE:
        raise ValueError("public task contract exceeds size limit")
    body = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    validate_task_contract(body, required=True)
    prefix = (
        f"## 公开评测约束（{INPUT_POLICY}）\n"
        "允许修改的现有源码文件（相对仓库根目录，精确文件路径；不是目录或通配符）：\n"
        + json.dumps(list(paths), ensure_ascii=False)
        + "\n\n补丁只能修改以上文件，不得新增、删除或重命名文件。\n"
        "其他公开文件仅可通过原有工具权限读取，不得修改。\n"
        "不得修改测试、配置、依赖或环境。\n\n## 原始公开任务说明\n"
    )
    return validate_task_contract(prefix + body, required=True)


def prepare_agent_input(case: EvaluationCase, destination: Path) -> PublicTaskSpec:
    """Use only the explicit public tree and authored public contract, never private assets."""
    if destination.resolve().is_relative_to(case.root.resolve()):
        raise ValueError("Agent input must be outside task assets")
    contract = public_task_contract(case)
    stage_public_snapshot(
        case.buggy,
        destination,
        case.visible_tests,
        required_paths=(*case.allowed_source_paths, "pyproject.toml"),
    )
    (destination / "TASK.md").write_bytes(contract.encode("utf-8"))
    inventory = protocol.input_inventory(destination, case.visible_tests)
    return PublicTaskSpec(
        version=1,
        case_id=case.id,
        revision=case.revision,
        source_kind=case.source_kind,
        visible_tests=case.visible_tests,
        timeout_seconds=case.timeout_seconds,
        input_policy=INPUT_POLICY,
        public_input_hash=protocol.inventory_hash(inventory),
    )


def validate_public_input(repo: Path, spec: PublicTaskSpec) -> None:
    """Check the initial model-visible input, before credentials/model construction."""
    protocol.checked_root(repo)
    for path in repo.rglob("*"):
        if protocol.is_link(path):
            raise ValueError("linked public worker input")
        if _excluded(path.relative_to(repo).as_posix()):
            raise ValueError("public worker input contains excluded files")
    inventory = protocol.input_inventory(repo, spec.visible_tests)
    if protocol.inventory_hash(inventory) != spec.public_input_hash:
        raise ValueError("public worker input digest differs from descriptor identity")
