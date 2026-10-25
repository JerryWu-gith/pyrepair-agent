"""Assemble data-only task assets from verified source; calibration is separate."""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

from pyrepair.policy import _is_protected

from .cases import EXCLUDED, contained, load_cases, safe_relative
from .catalog_references import _reference_patch, verify_references
from .catalog_source_cache import (
    canonical,
    checked_root,
    read_bounded,
    sha256,
    version_path,
    write_new_json,
)
from .opensource_assets import _snapshot_files
from .source_catalog import validate_catalog

PUBLIC = "pyrepair_public_tests/test_repro.py"
HIDDEN = "hidden_tests/test_contract.py"
IMPORTS = "pyrepair_imports.json"
FIELDS = {
    "task",
    "public",
    "hidden",
    "f2p_public",
    "f2p_hidden",
    "p2p_public",
    "p2p_hidden",
    "public_origin",
    "hidden_origin",
    "mutant_origin",
    "mutant",
}


def registered_overlays() -> dict:
    from .catalog_overlays_click import CLICK_OVERLAYS
    from .catalog_overlays_dotenv_more import DOTENV_MORE_OVERLAYS
    from .catalog_overlays_packaging import PACKAGING_OVERLAYS
    from .opensource_overlays import OVERLAYS

    result = {key: dict(value) for key, value in OVERLAYS.items()}
    result["os_more_seekable_1269"]["mutant"] = {
        "keep_paths": ["more_itertools/more.py"],
        "replacements": [
            {
                "path": "more_itertools/more.py",
                "old": "if getattr(self._cache, 'maxlen', None) == 0:",
                "new": "if getattr(self._cache, 'maxlen', None) == 0 and peeked:",
            }
        ],
    }
    result["os_boltons_addlist_458"]["mutant"] = {
        "keep_paths": ["boltons/dictutils.py"],
        "replacements": [
            {
                "path": "boltons/dictutils.py",
                "old": "        v = list(v)\n        if not v:\n            return\n        self_insert = self._insert",
                "new": "        if k not in self:\n            v = list(v)\n        if not v:\n            return\n        self_insert = self._insert",
            }
        ],
    }
    result["os_boltons_addlist_458"]["mutant_origin"] = (
        "Artificial incomplete repair, matching the existing revision-2 calibration: "
        "materialize one-shot iterables only for new keys; appending to an existing key is still broken."
    )
    for group in (PACKAGING_OVERLAYS, CLICK_OVERLAYS, DOTENV_MORE_OVERLAYS):
        if result.keys() & group.keys():
            raise ValueError("duplicate overlay identity")
        result.update(group)
    return result


def _nodes(overlay: dict) -> tuple[list[str], list[str]]:
    if not isinstance(overlay, dict) or set(overlay) != FIELDS:
        raise ValueError("invalid overlay fields")
    for name in ("task", "public", "hidden", "public_origin", "hidden_origin", "mutant_origin"):
        if not isinstance(overlay[name], str) or not overlay[name].strip():
            raise ValueError("empty overlay text")
    failing, passing = [], []
    for stage, filename in (("public", PUBLIC), ("hidden", HIDDEN)):
        module = ast.parse(overlay[stage])
        actual = [
            n.name
            for n in module.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        ]
        f2p, p2p = overlay["f2p_" + stage], overlay["p2p_" + stage]
        if (
            not isinstance(f2p, list)
            or not f2p
            or not isinstance(p2p, list)
            or any(not isinstance(n, str) for n in f2p + p2p)
            or len(actual) != len(set(actual))
            or len(f2p + p2p) != len(set(f2p + p2p))
            or set(actual) != set(f2p + p2p)
            or any(
                n.decorator_list
                for n in module.body
                if isinstance(n, ast.FunctionDef) and n.name in actual
            )
        ):
            raise ValueError("overlay nodes must be explicit unique F2P/P2P functions")
        failing.extend(filename + "::" + n for n in f2p)
        passing.extend(filename + "::" + n for n in p2p)
    return failing, passing


def _mutant(old: dict, fixed: dict, overlay: dict, reference_paths: list[str]) -> str:
    spec = overlay["mutant"]
    if not isinstance(spec, dict) or set(spec) != {"keep_paths", "replacements"}:
        raise ValueError("invalid mutant fields")
    keep, edits = spec["keep_paths"], spec["replacements"]
    if (
        not isinstance(keep, list)
        or not keep
        or len(keep) != len(set(keep))
        or not set(keep) <= set(reference_paths)
        or not isinstance(edits, list)
    ):
        raise ValueError("mutant must retain only registered production changes")
    candidate = {**old, **{p: fixed[p] for p in keep}}
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"path", "old", "new"}:
            raise ValueError("invalid mutant replacement")
        path, before, after = edit["path"], edit["old"], edit["new"]
        if (
            path not in keep
            or not isinstance(before, str)
            or not before
            or not isinstance(after, str)
            or before == after
        ):
            raise ValueError("invalid mutant edit target")
        body = candidate[path].decode("utf-8")
        if body.count(before) != 1:
            raise ValueError("mutant anchor is not unique in reference source")
        body = body.replace(before, after, 1)
        ast.parse(body)
        candidate[path] = body.encode("utf-8")
    changed = [p for p in reference_paths if old[p] != candidate[p]]
    if not changed or all(candidate[p] == fixed[p] for p in reference_paths):
        raise ValueError("mutant must differ from both buggy and reference")
    return _reference_patch(old, candidate, changed)


def _profile(entry: dict, original: dict) -> dict:
    root = entry["source_root"]
    package = root.split("/")[-1]
    module, file = (
        ("boltons.dictutils", "boltons/dictutils.py")
        if package == "boltons"
        else (package, root + "/__init__.py")
    )
    if file not in original:
        raise ValueError("task package import source is missing")
    return {
        "version": 1,
        "roots": ["src" if root.startswith("src/") else "."],
        "modules": {module: file},
    }


def _prepare(entry: dict, refs: Path, overlay: dict) -> dict:
    f2p, p2p = _nodes(overlay)
    original = _snapshot_files(version_path(entry, "buggy", refs / "versions") / "source")
    fixed = _snapshot_files(version_path(entry, "fixed", refs / "versions") / "source")
    for reserved in (PUBLIC, HIDDEN, IMPORTS, "TASK.md"):
        if reserved in original or any(p.startswith(reserved + "/") for p in original):
            raise ValueError("overlay collides with upstream source")
    if any(p.startswith("hidden_tests/") for p in original) or "pyproject.toml" not in original:
        raise ValueError("reserved hidden directory or missing pyproject")
    root = entry["source_root"] + "/"
    allowed = sorted(
        p
        for p in original
        if p.startswith(root) and p.endswith(".py") and not _is_protected(PurePosixPath(p))
    )
    if not set(entry["reference_source_paths"]) <= set(allowed):
        raise ValueError("reference changes outside public production ACL")
    for path in allowed:
        safe_relative(path)
    return {
        "entry": entry,
        "overlay": overlay,
        "original": original,
        "gold": read_bounded(refs / "cases" / entry["id"] / "gold.patch"),
        "wrong": _mutant(original, fixed, overlay, entry["reference_source_paths"]).encode("utf-8"),
        "profile": _profile(entry, original),
        "allowed": allowed,
        "f2p": f2p,
        "p2p": p2p,
    }


def _write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body)


def _publish(prepared: dict, output: Path) -> dict:
    entry, overlay = prepared["entry"], prepared["overlay"]
    public = "tasks/" + entry["id"]
    private = "private/" + entry["id"]
    buggy = output / public / "buggy"
    excluded = []
    for path, body in prepared["original"].items():
        if any(p in EXCLUDED or p.startswith(".env.") for p in path.split("/")) or path.endswith(
            (".pyc", ".pyo")
        ):
            excluded.append(path)
            continue
        _write_bytes(contained(buggy, path), body)
    assets = {
        public + "/TASK.md": overlay["task"].encode("utf-8"),
        public + "/buggy/" + PUBLIC: overlay["public"].encode("utf-8"),
        public + "/buggy/" + IMPORTS: canonical(prepared["profile"]),
        private + "/" + HIDDEN: overlay["hidden"].encode("utf-8"),
        private + "/gold.patch": prepared["gold"],
        private + "/wrong.patch": prepared["wrong"],
    }
    for path, body in assets.items():
        _write_bytes(contained(output, path), body)
    origin = {
        "repository": entry["repository"],
        "pull_request": entry["pull_request"],
        "buggy_commit": entry["buggy_commit"],
        "fixed_commit": entry["fixed_commit"],
        "upstream_ai_assistance": entry["upstream_ai_assistance"],
        "scope": "Project-authored selected contract tests, not the full upstream suite",
        "catalog_entry_sha256": sha256(canonical(entry)),
        "source_catalog_revision": entry["revision"],
        "preparation_status": "assets_prepared",
        "nodes_status": "declared_not_collected",
    }
    write_new_json(
        output / private / "preparation.json",
        {
            "status": "assets_prepared",
            "origin": origin,
            "overlay_origins": {
                k: overlay[k] for k in ("public_origin", "hidden_origin", "mutant_origin")
            },
            "asset_sha256": {p: sha256(b) for p, b in assets.items()},
            "runtime_excluded_regular_files": excluded,
            "documentation_links": "Metadata only in verified source cache; never materialized",
            "calibration_status": "not_run",
            "ready_for_model_evaluation": False,
        },
    )
    return {
        "id": entry["id"],
        "revision": entry["revision"] + (1 if entry["legacy_manifest"] else 0),
        "suite": "capability",
        "split": entry["split"],
        "source_kind": "opensource",
        "origin": origin,
        "buggy_path": public + "/buggy",
        "public_description_path": public + "/TASK.md",
        "private_path": private,
        "visible_tests": [PUBLIC],
        "hidden_tests": [HIDDEN],
        "fail_to_pass": prepared["f2p"],
        "pass_to_pass": prepared["p2p"],
        "allowed_source_paths": prepared["allowed"],
        "timeout_seconds": 120,
    }


def assemble_catalog(catalog: dict, references: Path, output: Path, *, overlays=None) -> dict:
    """New output only; verify all sources and recipes before publishing any task."""
    data = validate_catalog(catalog)
    # Reject links before resolving aliases; lexical '..' must not bypass the
    # source-cache/output separation on Windows (absolute() alone preserves it).
    references, output = checked_root(references).resolve(), checked_root(output).resolve()
    if output.exists():
        raise FileExistsError("refusing to overwrite task assembly")
    if output.is_relative_to(references) or references.is_relative_to(output):
        raise ValueError("source cache and task output overlap")
    verify_references(data, references)
    overlays = registered_overlays() if overlays is None else overlays
    if not isinstance(overlays, dict) or set(overlays) != {e["id"] for e in data["entries"]}:
        raise ValueError("overlay case set differs from source catalog")
    prepared = [_prepare(e, references, overlays[e["id"]]) for e in data["entries"]]
    output.mkdir(parents=True, exist_ok=False)
    state = {"status": "assembly_interrupted", "completed": [], "model_calls": 0}
    try:
        cases = []
        for item in prepared:
            cases.append(_publish(item, output))
            state["completed"].append(item["entry"]["id"])
        write_new_json(output / "manifest.json", {"version": 2, "cases": cases})
        load_cases(output / "manifest.json")
        state.update(
            status="assets_prepared",
            case_count=len(cases),
            catalog_sha256=sha256(canonical(data)),
            calibration_status="not_run",
            ready_for_model_evaluation=False,
        )
        return state
    except (OSError, ValueError, TypeError, KeyError) as exc:
        state.update(error={"type": type(exc).__name__, "message": str(exc)[:1600]})
        raise
    finally:
        write_new_json(output / "assembly.json", state)
