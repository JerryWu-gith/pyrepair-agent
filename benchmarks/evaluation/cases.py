from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pyrepair.policy import _is_protected

EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".pyrepair",
    ".worktrees",
    "case.json",
    ".env",
}
DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)),
}


class CaseError(ValueError):
    """A task is malformed or crosses a declared filesystem boundary."""


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaseError("expected nonempty relative path")
    parts = value.split("/")
    if (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(c in value for c in '\\:*?"<>|')
        or any(ord(c) < 32 for c in value)
        or any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in parts)
        or any(p.split(".")[0].upper() in DEVICE_NAMES for p in parts)
    ):
        raise CaseError(f"unsafe relative path: {value!r}")
    return value


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def contained(root: Path, relative: str) -> Path:
    safe_relative(relative)
    root = root.resolve()
    candidate = root
    for part in relative.split("/"):
        candidate = candidate / part
        if is_link(candidate):
            raise CaseError(f"links are not supported: {relative}")
    if not candidate.resolve().is_relative_to(root):
        raise CaseError(f"path escapes root: {relative}")
    return candidate


def public_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if any(p in EXCLUDED or p.startswith(".env.") for p in parts):
            continue
        if is_link(path):
            raise CaseError(f"links are not supported: {path.name}")
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            contained(root, path.relative_to(root).as_posix())
            files.append(path)
    return files


@dataclass(frozen=True)
class EvaluationCase:
    root: Path
    id: str
    revision: int
    suite: str
    split: str
    source_kind: str
    origin: dict[str, Any]
    buggy_path: str
    public_description_path: str
    private_path: str
    visible_tests: tuple[str, ...]
    hidden_tests: tuple[str, ...]
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    allowed_source_paths: tuple[str, ...]
    timeout_seconds: int

    @property
    def buggy(self) -> Path:
        return contained(self.root, self.buggy_path)

    @property
    def private(self) -> Path:
        return contained(self.root, self.private_path)

    @property
    def description(self) -> Path:
        return contained(self.root, self.public_description_path)

    @property
    def gold_patch(self) -> Path:
        return self.private / "gold.patch"

    @property
    def wrong_patch(self) -> Path:
        return self.private / "wrong.patch"

    def metadata(self) -> dict:
        result = asdict(self)
        del result["root"]
        return result


def _string_list(item: dict, key: str, *, nonempty: bool = True) -> tuple[str, ...]:
    values = item.get(key)
    if (
        not isinstance(values, list)
        or (nonempty and not values)
        or any(not isinstance(v, str) or not v for v in values)
        or len(values) != len(set(values))
    ):
        raise CaseError(f"invalid or duplicate {key}")
    return tuple(values)


def load_cases(manifest: Path) -> list[EvaluationCase]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 2:
        raise CaseError("expected manifest version 2")
    if not isinstance(data.get("cases"), list) or not data["cases"]:
        raise CaseError("manifest must contain cases")
    cases = []
    ids: set[str] = set()
    for item in data["cases"]:
        if not isinstance(item, dict):
            raise CaseError("case must be an object")
        identity = item.get("id")
        if not isinstance(identity, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", identity
        ):
            raise CaseError("invalid case id")
        safe_relative(identity)
        if identity.casefold() in ids:
            raise CaseError(f"duplicate case id: {identity}")
        ids.add(identity.casefold())
        for key in ("revision", "timeout_seconds"):
            if type(item.get(key)) is not int or item[key] < 1:
                raise CaseError(f"invalid {key}")
        for key, allowed in (
            ("suite", {"regression", "capability"}),
            ("split", {"dev", "holdout"}),
            ("source_kind", {"synthetic", "opensource"}),
        ):
            if not isinstance(item.get(key), str) or item[key] not in allowed:
                raise CaseError(f"invalid {key}")
        if not isinstance(item.get("origin"), dict) or not item["origin"]:
            raise CaseError("origin metadata required")
        values = dict(item)
        for key in (
            "visible_tests",
            "hidden_tests",
            "fail_to_pass",
            "pass_to_pass",
            "allowed_source_paths",
        ):
            values[key] = _string_list(item, key, nonempty=key != "pass_to_pass")
        try:
            case = EvaluationCase(root=manifest.resolve().parent, **values)
        except TypeError as exc:
            raise CaseError("unknown or missing case fields") from exc
        _validate_paths(case)
        cases.append(case)
    return cases


def _validate_paths(case: EvaluationCase) -> None:
    if not case.buggy.is_dir() or not case.private.is_dir():
        raise CaseError("missing buggy/private directory")
    if case.private.is_relative_to(case.buggy) or case.buggy.is_relative_to(case.private):
        raise CaseError("private and public trees must be separate")
    for path in (case.description, case.gold_patch, case.wrong_patch):
        if not path.is_file() or is_link(path):
            raise CaseError(f"missing or linked asset: {path.name}")
    public_files(case.buggy)
    public_files(case.private)
    visible, hidden = set(case.visible_tests), set(case.hidden_tests)
    if visible & hidden:
        raise CaseError("visible and hidden test paths overlap")
    for relative in visible:
        if not contained(case.buggy, relative).is_file():
            raise CaseError(f"missing visible test: {relative}")
    for relative in hidden:
        if (
            not relative.startswith("hidden_tests/")
            or not contained(case.private, relative).is_file()
        ):
            raise CaseError(f"missing or invalid hidden test: {relative}")
        if contained(case.buggy, relative).exists():
            raise CaseError("hidden test already exists in public tree")
    for node in (*case.fail_to_pass, *case.pass_to_pass):
        filename, separator, test_name = node.partition("::")
        safe_relative(filename)
        if not separator or not test_name or any(ord(c) < 32 for c in test_name):
            raise CaseError(f"invalid node id: {node}")
        if filename not in visible | hidden:
            raise CaseError(f"node does not belong to selected tests: {node}")
    if set(case.fail_to_pass) & set(case.pass_to_pass):
        raise CaseError("F2P and P2P overlap")
    for relative in case.allowed_source_paths:
        path = contained(case.buggy, relative)
        if (
            not path.is_file()
            or path.suffix not in {".py", ".pyi"}
            or _is_protected(PurePosixPath(relative))
        ):
            raise CaseError(f"invalid allowed source: {relative}")


def prepare_case(case: EvaluationCase, destination: Path) -> Path:
    # Only copy the explicit public tree, never its benchmark parent.
    if destination.resolve().is_relative_to(case.root):
        raise CaseError("runtime destination must be outside task assets")
    destination.mkdir(parents=True, exist_ok=False)
    for source in public_files(case.buggy):
        target = contained(destination, source.relative_to(case.buggy).as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(case.description, destination / "TASK.md")
    return destination


def case_fingerprint(case: EvaluationCase) -> str:
    digest = hashlib.sha256(
        json.dumps(
            case.metadata(),
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    )
    for label, root in (("public", case.buggy), ("private", case.private)):
        for path in public_files(root):
            digest.update(f"{label}/{path.relative_to(root).as_posix()}\0".encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(case.description.read_bytes())
    return digest.hexdigest()
