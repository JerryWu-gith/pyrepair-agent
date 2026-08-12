from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

from .models import PatchCheck, PatchSnapshot

LOCK_FILES = {"poetry.lock", "uv.lock", "pipfile.lock", "requirements.lock"}
CI_FILES = {".gitlab-ci.yml", "azure-pipelines.yml"}
SECRET_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "secrets.json"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
BYPASS_PATTERNS = (
    re.compile(r"pytest\.(?:skip|xfail)\s*\("),
    re.compile(r"@pytest\.mark\.(?:skip|xfail)\b"),
)
COMPARISON_RE = re.compile(r"(?:==|!=|<=|>=|<|>|\bin\b|\bis\b)")


class PatchPolicyGate:
    def check(self, snapshot: PatchSnapshot) -> PatchCheck:
        violations: list[str] = []
        normalized_paths: list[str] = []
        added = sum(change.added_lines for change in snapshot.changes)
        deleted = sum(change.deleted_lines for change in snapshot.changes)

        for change in snapshot.changes:
            normalized = change.path.replace("\\", "/")
            normalized_paths.append(normalized)
            path = PurePosixPath(normalized)
            if path.is_absolute() or PureWindowsPath(normalized).is_absolute() or ".." in path.parts:
                violations.append(f"path_outside_workspace:{normalized}")
                continue
            if _is_protected(path):
                violations.append(f"protected_path:{normalized}")
            if path.suffix.lower() not in {".py", ".pyi"}:
                violations.append(f"non_source_file:{normalized}")
            if _adds_test_bypass(change.old_text, change.new_text):
                violations.append(f"test_bypass:{normalized}")
            if _weakens_assertions(change.old_text, change.new_text):
                violations.append(f"assertion_weakened:{normalized}")

        if len(normalized_paths) > 3:
            violations.append(f"too_many_files:{len(normalized_paths)}>3")
        if added + deleted > 80:
            violations.append(f"too_many_changed_lines:{added + deleted}>80")

        unique_violations = tuple(dict.fromkeys(violations))
        return PatchCheck(
            allowed=not unique_violations,
            violations=unique_violations,
            changed_files=tuple(normalized_paths),
            added_lines=added,
            deleted_lines=deleted,
        )


def _is_protected(path: PurePosixPath) -> bool:
    lower_parts = tuple(part.lower() for part in path.parts)
    name = path.name.lower()
    if "tests" in lower_parts or (name.startswith("test_") and path.suffix.lower() == ".py"):
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    if name in LOCK_FILES or name in CI_FILES:
        return True
    if name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
        return True
    return len(lower_parts) >= 3 and lower_parts[:2] == (".github", "workflows")


def _adds_test_bypass(old_text: str, new_text: str) -> bool:
    return any(
        len(pattern.findall(new_text)) > len(pattern.findall(old_text))
        for pattern in BYPASS_PATTERNS
    )


def _weakens_assertions(old_text: str, new_text: str) -> bool:
    old_assertions = _assertion_lines(old_text)
    new_assertions = _assertion_lines(new_text)
    if len(new_assertions) < len(old_assertions):
        return True
    old_comparisons = sum(bool(COMPARISON_RE.search(line)) for line in old_assertions)
    new_comparisons = sum(bool(COMPARISON_RE.search(line)) for line in new_assertions)
    return new_comparisons < old_comparisons


def _assertion_lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip().startswith("assert "))
