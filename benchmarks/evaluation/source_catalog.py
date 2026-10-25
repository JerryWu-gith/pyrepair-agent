"""Read-only upstream provenance metadata; never task calibration or live authority.

These checks validate a source list, not GitHub's truthfulness, source bytes,
licenses, reproducibility or scoring. Those require separate preparation.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .cases import safe_relative

TOP_FIELDS = {
    "version",
    "kind",
    "stage",
    "agent_baseline_commit",
    "expected_count",
    "minimum_repositories",
    "entries",
    "exclusions",
}
ENTRY_FIELDS = {
    "id",
    "revision",
    "source_kind",
    "split",
    "repository",
    "pull_request",
    "title",
    "buggy_commit",
    "fixed_commit",
    "fixed_parents",
    "merged_at",
    "source_root",
    "reference_source_paths",
    "upstream_test_paths",
    "upstream_ai_assistance",
    "legacy_manifest",
}
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
SHA = re.compile(r"[0-9a-f]{40}")
MAX_BYTES = 512 * 1024


class CatalogError(ValueError):
    """The source list is inconsistent or outside its declared data contract."""


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise CatalogError("unexpected catalog fields")


def _positive(value):
    if type(value) is not int or value < 1:
        raise CatalogError("expected a positive integer")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise CatalogError("expected nonempty text")


def _sha(value):
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise CatalogError("expected a full lowercase Git SHA")


def _relative(value):
    try:
        return safe_relative(value)
    except ValueError as exc:
        raise CatalogError("unsafe relative catalog path") from exc


def _strings(values, *, nonempty=True):
    if not isinstance(values, list) or (nonempty and not values):
        raise CatalogError("expected a list of strings")
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise CatalogError("duplicate list value")
    return values


def _repository(value):
    if not isinstance(value, str) or REPOSITORY.fullmatch(value) is None:
        raise CatalogError("expected owner/repository")
    return value.casefold()


def _entry(entry):
    _fields(entry, ENTRY_FIELDS)
    identity = entry["id"]
    if (
        not isinstance(identity, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", identity) is None
    ):
        raise CatalogError("invalid source id")
    _relative(identity)
    _positive(entry["revision"])
    _positive(entry["pull_request"])
    repo = _repository(entry["repository"])
    if (
        entry["source_kind"] != "opensource"
        or not isinstance(entry["split"], str)
        or entry["split"] not in {"dev", "holdout"}
    ):
        raise CatalogError("invalid source kind or split")
    _text(entry["title"])
    _text(entry["upstream_ai_assistance"])
    for sha in (entry["buggy_commit"], entry["fixed_commit"]):
        _sha(sha)
    parents = _strings(entry["fixed_parents"])
    for parent in parents:
        _sha(parent)
    if parents[0] != entry["buggy_commit"] or entry["fixed_commit"] == entry["buggy_commit"]:
        raise CatalogError("fixed commit must differ and its first parent must be the buggy commit")
    merged = entry["merged_at"]
    if (
        not isinstance(merged, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", merged) is None
    ):
        raise CatalogError("expected an explicit UTC merge timestamp")
    try:
        datetime.fromisoformat(merged)
    except ValueError as exc:
        raise CatalogError("invalid merge timestamp") from exc
    root = _relative(entry["source_root"])
    for path in _strings(entry["reference_source_paths"]):
        _relative(path)
        if (
            not path.startswith(root + "/")
            or not path.endswith(".py")
            or any(part in {"test", "tests"} for part in path.split("/"))
            or path.rsplit("/", 1)[-1].startswith("test_")
        ):
            raise CatalogError("reference source file is outside the production package")
    for path in _strings(entry["upstream_test_paths"], nonempty=False):
        _relative(path)
    legacy = entry["legacy_manifest"]
    if legacy is not None:
        _relative(legacy)
        if not legacy.endswith(".json"):
            raise CatalogError("legacy manifest must be JSON")
    return repo


def validate_catalog(data: object) -> dict:
    """Validate declared source provenance only; do not touch a repository or key."""
    _fields(data, TOP_FIELDS)
    if (
        type(data["version"]) is not int
        or data["version"] != 1
        or data["kind"] != "pyrepair-opensource-source-catalog"
        or data["stage"] != "provenance_checked"
    ):
        raise CatalogError("unsupported source catalog identity or stage")
    _sha(data["agent_baseline_commit"])
    _positive(data["expected_count"])
    _positive(data["minimum_repositories"])
    entries = data["entries"]
    if not isinstance(entries, list) or len(entries) != data["expected_count"]:
        raise CatalogError("source count differs from declared count")
    ids, issues, commits, repositories = set(), set(), set(), set()
    for entry in entries:
        repo = _entry(entry)
        issue, commit = (repo, entry["pull_request"]), (repo, entry["fixed_commit"])
        if entry["id"].casefold() in ids or issue in issues or commit in commits:
            raise CatalogError("duplicate source identity, PR or fixed commit")
        ids.add(entry["id"].casefold())
        issues.add(issue)
        commits.add(commit)
        repositories.add(repo)
    if len(repositories) < data["minimum_repositories"]:
        raise CatalogError("too few distinct upstream repositories")
    if not isinstance(data["exclusions"], list):
        raise CatalogError("expected exclusion records")
    excluded = set()
    for exclusion in data["exclusions"]:
        _fields(exclusion, {"repository", "pull_request", "reason", "evidence"})
        repo = _repository(exclusion["repository"])
        _positive(exclusion["pull_request"])
        _text(exclusion["reason"])
        _text(exclusion["evidence"])
        key = repo, exclusion["pull_request"]
        if key in issues or key in excluded:
            raise CatalogError("duplicate or selected exclusion")
        excluded.add(key)
    try:
        return json.loads(json.dumps(data))
    except (ValueError, TypeError) as exc:
        raise CatalogError("catalog must contain only JSON values") from exc


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_catalog(path: Path) -> dict:
    """Read bounded JSON, rejecting duplicate keys before validating provenance."""
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise CatalogError("catalog size exceeds 512 KiB")
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except CatalogError:
        raise
    except (ValueError, RecursionError) as exc:
        raise CatalogError("invalid or excessively complex source catalog JSON") from exc
    return validate_catalog(data)


def summarize_catalog(data: dict) -> dict:
    """Count sources without claiming their bytes, tests or environments are ready."""
    value = validate_catalog(data)
    repositories = Counter(e["repository"].casefold() for e in value["entries"])
    splits = Counter(e["split"] for e in value["entries"])
    return {
        "stage": "provenance_checked",
        "source_count": len(value["entries"]),
        "repository_count": len(repositories),
        "repositories": dict(sorted(repositories.items())),
        "split_counts": {"dev": splits["dev"], "holdout": splits["holdout"]},
        "ready_for_model_evaluation": False,
        "calibration_status": "not assessed by source catalog",
    }
