"""Fetch pinned source as data and bind every regular file to a Git blob.

This module never imports upstream modules, runs tests, or invokes build hooks.
The GitHub API/HTTPS endpoint is a trusted provenance source, not a signed
attestation; archive SHA-256 and per-file Git blob IDs are retained separately.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .cases import contained, is_link, load_cases, public_files
from .grading import write_json
from .opensource_archive import DEFAULT_LIMITS, _register_path, _safe_path, read_source_zip
from .opensource_overlays import OVERLAYS
from .patching import patch_paths

REGISTRY = Path(__file__).resolve().parents[1] / "opensource_sources.json"
SOURCE_IDS = ("os_more_seekable_1269", "os_boltons_addlist_458")


def source_definition(case_id: str) -> dict:
    if case_id not in SOURCE_IDS:
        raise ValueError("unknown registered opensource case")
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if data.get("version") != 1 or set(data.get("cases", {})) != set(SOURCE_IDS):
        raise ValueError("invalid opensource source registry")
    spec = data["cases"][case_id]
    repository = _safe_path(spec["repository"])
    if len(repository.split("/")) != 2 or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("invalid registered repository")
    for field in ("buggy_commit", "fixed_commit"):
        _sha(spec[field])
    return spec


def _sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("invalid Git SHA-1 identity")
    return value


def _download_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in {"api.github.com", "codeload.github.com"}
        or parts.username is not None
        or parts.password is not None
        or parts.port not in {None, 443}
        or parts.fragment
    ):
        raise ValueError("unapproved source download URL")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(url: str, *, limit: int = DEFAULT_LIMITS.archive_bytes) -> bytes:
    _download_url(url)
    if type(limit) is not int or not 0 < limit <= DEFAULT_LIMITS.archive_bytes:
        raise ValueError("invalid download size limit")
    request = urllib.request.Request(url, headers={"User-Agent": "PyRepair-offline-source/1"})
    with urllib.request.build_opener(SafeRedirect()).open(request, timeout=30) as response:
        _download_url(response.geturl())
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("source download exceeds size limit")
    return payload


def verify_source_files(files: dict[str, bytes], git_tree: dict) -> dict:
    if (
        not isinstance(git_tree, dict)
        or git_tree.get("truncated") is not False
        or not isinstance(git_tree.get("tree"), list)
        or not 0 < len(git_tree["tree"]) <= DEFAULT_LIMITS.members
    ):
        raise ValueError("incomplete or oversized Git tree")
    tree_sha = _sha(git_tree.get("sha"))
    blobs = {}
    seen: dict[str, tuple[str, bool]] = {}
    explicit: set[str] = set()
    for entry in git_tree["tree"]:
        if not isinstance(entry, dict):
            raise ValueError("invalid Git tree entry")  # noqa: TRY004 - malformed JSON protocol
        path = _safe_path(entry.get("path"))
        kind, mode = entry.get("type"), entry.get("mode")
        if (kind, mode) not in {("tree", "040000"), ("blob", "100644"), ("blob", "100755")}:
            raise ValueError(f"non-regular Git entry: {path}")
        _register_path(path, kind == "tree", seen, explicit)
        _sha(entry.get("sha"))
        if kind == "blob":
            blobs[path] = entry
    if not blobs or set(blobs) != set(files):
        raise ValueError("archive file set differs from pinned Git tree")
    records = {}
    total = 0
    for path, entry in blobs.items():
        content = files[path]
        if type(content) is not bytes:
            raise ValueError("source content must be bytes")
        if type(entry.get("size")) is not int or entry["size"] != len(content):
            raise ValueError(f"Git blob size mismatch: {path}")
        total += len(content)
        if len(content) > DEFAULT_LIMITS.file_bytes or total > DEFAULT_LIMITS.total_bytes:
            raise ValueError("source tree exceeds expanded size limit")
        blob = hashlib.sha1(
            b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        ).hexdigest()
        if blob != entry["sha"]:
            raise ValueError(f"Git blob content mismatch: {path}")
        records[path] = {
            "git_blob": blob,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "mode": entry["mode"],
        }
    return {
        "tree_sha": tree_sha,
        "file_count": len(records),
        "total_bytes": total,
        "files": records,
    }


def _new_directory(path: Path) -> None:
    if any(is_link(parent) for parent in (path, *path.parents)):
        raise ValueError("source output cannot use linked directories")
    path.mkdir(parents=True, exist_ok=False)


def prepare_source(case_id: str, output: Path) -> dict:
    """Download and verify both commits; retain failure evidence without retry."""
    spec = source_definition(case_id)
    _new_directory(output)
    result = {"version": 1, "case_id": case_id, "status": "source_error", "versions": {}}
    verified = {}
    repository = spec["repository"]

    def fetch(label: str, kind: str, url: str) -> bytes:
        result["last_request"] = {"version": label, "kind": kind, "url": url}
        return fetch_bytes(url)

    try:
        for label in ("buggy", "fixed"):
            commit = spec[label + "_commit"]
            api = f"https://api.github.com/repos/{repository}"
            metadata = json.loads(fetch(label, "commit", f"{api}/commits/{commit}"))
            if not isinstance(metadata, dict) or metadata.get("sha") != commit:
                raise ValueError("commit response does not match pinned identity")
            if label == "fixed" and (
                not isinstance(metadata.get("parents"), list)
                or not metadata["parents"]
                or not isinstance(metadata["parents"][0], dict)
                or metadata["parents"][0].get("sha") != spec["buggy_commit"]
            ):
                raise ValueError("fixed commit first parent does not match buggy commit")
            tree_sha = _sha(metadata["commit"]["tree"]["sha"])
            tree = json.loads(fetch(label, "tree", f"{api}/git/trees/{tree_sha}?recursive=1"))
            if not isinstance(tree, dict) or tree.get("sha") != tree_sha:
                raise ValueError("Git tree response identity mismatch")
            archive_url = f"https://codeload.github.com/{repository}/zip/{commit}"
            payload = fetch(label, "archive", archive_url)
            if len(payload) > DEFAULT_LIMITS.archive_bytes:
                raise ValueError("source archive exceeds size limit")
            archive = output / (label + ".zip")
            archive.write_bytes(payload)
            archive_sha = hashlib.sha256(payload).hexdigest()
            files = read_source_zip(
                archive,
                expected_sha256=archive_sha,
                root_prefix=repository.split("/")[1] + "-" + commit,
            )
            evidence = verify_source_files(files, tree)
            if spec["license_path"] not in files:
                raise ValueError("fixed source license is missing")
            write_json(output / (label + "-commit.json"), metadata)
            write_json(output / (label + "-tree.json"), tree)
            result["versions"][label] = {
                **evidence,
                "repository": repository,
                "commit": commit,
                "archive_url": archive_url,
                "archive_sha256": archive_sha,
            }
            verified[label] = files
        # Both archives must be fully verified before any source tree is written.
        for label, files in verified.items():
            root = output / label
            root.mkdir()
            for relative, content in files.items():
                target = contained(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        result.update(status="source_verified", license_path=spec["license_path"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        write_json(output / "source-verification.json", result)
        raise
    write_json(output / "source-verification.json", result)
    return result


def _snapshot_files(root: Path) -> dict[str, bytes]:
    if any(is_link(p) for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError("missing or linked source snapshot")
    files = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if is_link(path):
            raise ValueError("snapshot contains a link")
        if path.is_file():
            relative = _safe_path(path.relative_to(root).as_posix())
            remaining = min(DEFAULT_LIMITS.file_bytes, DEFAULT_LIMITS.total_bytes - total)
            with path.open("rb") as stream:
                content = stream.read(remaining + 1)
            if len(content) > remaining:
                raise ValueError("source snapshot exceeds size limit")
            files[relative] = content
            total += len(content)
            if len(files) > DEFAULT_LIMITS.members:
                raise ValueError("too many snapshot files")
    return files


def _verified_snapshots(case_id: str, source: Path, fixed: Path, spec: dict) -> tuple:
    if source.name != "buggy" or fixed.name != "fixed" or source.parent != fixed.parent:
        raise ValueError("expected paired buggy/fixed source snapshots")
    report = json.loads((source.parent / "source-verification.json").read_text(encoding="utf-8"))
    if report.get("status") != "source_verified" or report.get("case_id") != case_id:
        raise ValueError("source preparation has not been verified")
    snapshots = []
    for label, root in (("buggy", source), ("fixed", fixed)):
        files = _snapshot_files(root)
        tree = json.loads((root.parent / (label + "-tree.json")).read_text(encoding="utf-8"))
        evidence = verify_source_files(files, tree)
        expected = report["versions"][label]
        if expected["commit"] != spec[label + "_commit"] or any(
            expected.get(key) != value for key, value in evidence.items()
        ):
            raise ValueError("snapshot differs from recorded source verification")
        snapshots.append(files)
    return *snapshots, report


def _source_patch(old: dict[str, bytes], new: dict[str, bytes], allowed: list[str]) -> str:
    chunks = []
    for path in allowed:
        before = old[path].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        after = new[path].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        if before == after:
            raise ValueError(f"expected upstream production change is missing: {path}")
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(True),
                after.splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
    result = "".join(chunks)
    if patch_paths(result) != tuple(allowed):
        raise ValueError("generated patch path mismatch")
    return result


def _overlay_nodes(overlay: dict) -> tuple[list[str], list[str]]:
    f2p, p2p = [], []
    for stage, path in (
        ("public", "tests/test_pyrepair_repro.py"),
        ("hidden", "hidden_tests/test_pyrepair_hidden.py"),
    ):
        module = ast.parse(overlay[stage])
        actual = {
            node.name
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }
        failing, passing = overlay["f2p_" + stage], overlay["p2p_" + stage]
        if set(failing) & set(passing) or actual != set(failing + passing):
            raise ValueError("declared overlay node does not match its Python AST")
        f2p.extend(f"{path}::{name}" for name in failing)
        p2p.extend(f"{path}::{name}" for name in passing)
    return f2p, p2p


def assemble_case(case_id: str, source: Path, fixed: Path, destination: Path) -> Path:
    """Create new per-case assets and a draft manifest; no external test runs.

    destination is the benchmark root, which may already contain old tasks.
    Every new case directory and draft manifest must be absent.
    """
    spec = source_definition(case_id)
    public_relative = f"eval_cases/opensource_v1/{case_id}"
    private_relative = f"eval_private/opensource_v1/{case_id}"
    public_root = contained(destination, public_relative)
    private_root = contained(destination, private_relative)
    manifest = contained(destination, f"manifest_{case_id}.json")
    for output in (public_root, private_root, manifest):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite task asset: {output}")
        if any(
            output.resolve().is_relative_to(p.resolve())
            or p.resolve().is_relative_to(output.resolve())
            for p in (source, fixed)
        ):
            raise ValueError("source snapshots and assembly outputs must not overlap")
    original, corrected, source_report = _verified_snapshots(case_id, source, fixed, spec)
    overlay = OVERLAYS[case_id]
    f2p, p2p = _overlay_nodes(overlay)
    public_test = "tests/test_pyrepair_repro.py"
    hidden_test = "hidden_tests/test_pyrepair_hidden.py"
    for forbidden in ("TASK.md", public_test, hidden_test):
        if forbidden in original:
            raise ValueError(f"overlay collides with upstream file: {forbidden}")
    for required in (
        spec["license_path"],
        "pyproject.toml",
        *spec["visible_upstream_tests"],
        *spec["allowed_source_paths"],
    ):
        if required not in original:
            raise ValueError(f"required source file is missing: {required}")
    gold = _source_patch(original, corrected, spec["allowed_source_paths"])
    if case_id == "os_more_seekable_1269":
        path = spec["allowed_source_paths"][0]
        anchor = b"if getattr(self._cache, 'maxlen', None) == 0:"
        if corrected[path].count(anchor) != 1:
            raise ValueError("mutant anchor is not unique in pinned reference")
        mutant = {
            **corrected,
            path: corrected[path].replace(
                anchor,
                b"if getattr(self._cache, 'maxlen', None) == 0 and peeked:",
            ),
        }
        wrong = _source_patch(original, mutant, [path])
    else:
        wrong = _source_patch(original, corrected, ["boltons/dictutils.py"])
    _new_directory(public_root)
    _new_directory(private_root)
    buggy = public_root / "buggy"
    buggy.mkdir()
    for relative, content in original.items():
        target = contained(buggy, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (buggy / public_test).write_text(overlay["public"], encoding="utf-8", newline="\n")
    (public_root / "TASK.md").write_text(overlay["task"], encoding="utf-8", newline="\n")
    target = contained(private_root, hidden_test)
    target.parent.mkdir(parents=True)
    target.write_text(overlay["hidden"], encoding="utf-8", newline="\n")
    (private_root / "gold.patch").write_text(gold, encoding="utf-8", newline="\n")
    (private_root / "wrong.patch").write_text(wrong, encoding="utf-8", newline="\n")
    runtime_names = {p.relative_to(buggy).as_posix() for p in public_files(buggy)}
    origin = {
        "description": "Pinned upstream defect with project-authored evaluation overlay",
        "repository": spec["repository"],
        "buggy_commit": spec["buggy_commit"],
        "fixed_commit": spec["fixed_commit"],
        "urls": spec["origin_urls"],
        "scope": spec["scope_note"],
        "upstream_ai_assistance": spec["upstream_ai_assistance"],
        "preparation_status": "assets_prepared",
        "nodes_status": "declared_not_collected",
    }
    evidence = {
        "version": 1,
        "case_id": case_id,
        "status": "assets_prepared",
        "nodes_status": "declared_not_collected",
        "source": source_report,
        "origin": origin,
        "runtime_excluded": sorted(set(original) - runtime_names),
        "overlay": {
            key: overlay[key] for key in ("public_origin", "hidden_origin", "mutant_origin")
        },
        "overlay_sha256": {
            name: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for name, content in {
                "TASK.md": overlay["task"],
                public_test: overlay["public"],
                hidden_test: overlay["hidden"],
                "gold.patch": gold,
                "wrong.patch": wrong,
            }.items()
        },
    }
    write_json(private_root / "source-verification.json", evidence)
    item = {
        "id": case_id,
        "revision": 1,
        "suite": "capability",
        "split": "dev",
        "source_kind": "opensource",
        "origin": origin,
        "buggy_path": public_relative + "/buggy",
        "public_description_path": public_relative + "/TASK.md",
        "private_path": private_relative,
        "visible_tests": [*spec["visible_upstream_tests"], public_test],
        "hidden_tests": [hidden_test],
        "fail_to_pass": f2p,
        "pass_to_pass": p2p,
        "allowed_source_paths": spec["allowed_source_paths"],
        "timeout_seconds": 120,
    }
    write_json(manifest, {"version": 2, "cases": [item]})
    load_cases(manifest)  # Structural validation only; does not import case source.
    return manifest
