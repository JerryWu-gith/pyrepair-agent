"""Content-checked source cache. Downloaded Python is always data, never imported."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.parse
from pathlib import Path

from .cases import contained, is_link
from .catalog_document_links import read_catalog_zip, verify_catalog_files
from .opensource_archive import DEFAULT_LIMITS
from .opensource_assets import (
    _download_url,
    _sha,
    _snapshot_files,
    fetch_bytes,
)
from .source_catalog import _entry, _unique_pairs


def checked_root(path: Path) -> Path:
    path = Path(path).absolute()
    if any(is_link(parent) for parent in (path, *path.parents)):
        raise ValueError("source directories cannot contain links")
    return path


def read_bounded(path: Path) -> bytes:
    path = checked_root(path)
    with path.open("rb") as stream:
        content = stream.read(DEFAULT_LIMITS.archive_bytes + 1)
    return bounded_bytes(content)


def bounded_bytes(content: bytes) -> bytes:
    if type(content) is not bytes or len(content) > DEFAULT_LIMITS.archive_bytes:
        raise ValueError("source response is not bounded bytes")
    return content


def json_bytes(content: bytes) -> dict:
    try:
        value = json.loads(bounded_bytes(content).decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid or excessively complex source metadata JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("source metadata must be a JSON object")
    return value


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_new_json(path: Path, value) -> None:
    with checked_root(path).open("xb") as stream:
        stream.write(canonical(value))


def version_path(entry: dict, label: str, versions: Path) -> Path:
    _entry(entry)
    if label not in ("buggy", "fixed"):
        raise ValueError("expected buggy or fixed source label")
    return contained(checked_root(versions), entry["repository"] + "/" + entry[label + "_commit"])


def _metadata(entry, label, metadata):
    commit = entry[label + "_commit"]
    if metadata.get("sha") != commit:
        raise ValueError("commit response differs from pinned source")
    parents = metadata.get("parents")
    if not isinstance(parents, list) or any(not isinstance(p, dict) for p in parents):
        raise ValueError("invalid commit parent list")
    parent_shas = [_sha(p.get("sha")) for p in parents]
    if label == "fixed" and parent_shas != entry["fixed_parents"]:
        raise ValueError("fixed commit parents differ from registered provenance")
    try:
        tree_sha = _sha(metadata["commit"]["tree"]["sha"])
    except (KeyError, TypeError) as exc:
        raise ValueError("missing source tree identity") from exc
    # Retain provenance fields, not author emails, message text or embedded PR patches.
    return {
        "sha": commit,
        "parents": [{"sha": p} for p in parent_shas],
        "commit": {"tree": {"sha": tree_sha}},
    }


def _evidence(entry, label, root):
    metadata_bytes, tree_bytes = (
        read_bounded(root / "commit.json"),
        read_bounded(root / "tree.json"),
    )
    metadata = _metadata(entry, label, json_bytes(metadata_bytes))
    tree = json_bytes(tree_bytes)
    tree_sha = metadata["commit"]["tree"]["sha"]
    if tree.get("sha") != tree_sha:
        raise ValueError("source tree response identity mismatch")
    files = _snapshot_files(root / "source")
    archive = read_bounded(root / "archive.zip")
    archive_sha = sha256(archive)
    archived, links = read_catalog_zip(
        root / "archive.zip",
        expected_sha256=archive_sha,
        root_prefix=entry["repository"].split("/")[1] + "-" + entry[label + "_commit"],
        tree=tree,
    )
    if archived != files:
        raise ValueError("cached source bytes differ from archived source")
    evidence = verify_catalog_files(files, links, tree)
    licenses = {
        name: evidence["files"][name]
        for name in files
        if "/" not in name and name.upper().startswith(("LICENSE", "COPYING"))
    }
    if not licenses:
        raise ValueError("fixed source is missing root license files")
    return {
        "version": 1,
        "status": "source_verified",
        "repository": entry["repository"],
        "commit": entry[label + "_commit"],
        **evidence,
        "archive_sha256": archive_sha,
        "metadata_sha256": {"commit": sha256(metadata_bytes), "tree": sha256(tree_bytes)},
        "licenses": licenses,
    }


def verify_version(entry: dict, label: str, versions: Path) -> dict:
    root = version_path(entry, label, versions)
    if not root.is_dir():
        raise ValueError("missing prepared source version")
    expected = json_bytes(read_bounded(root / "version.json"))
    actual = _evidence(entry, label, root)
    if actual != expected:
        raise ValueError("cached source verification differs from recorded evidence")
    return {**actual, "path": str(root)}


def prepare_version(entry: dict, label: str, versions: Path, *, fetch=fetch_bytes) -> dict:
    """Publish a version only after both archive structure and Git bytes agree."""
    target = version_path(entry, label, versions)
    if target.exists():
        return verify_version(entry, label, versions)
    versions = checked_root(versions)
    versions.mkdir(parents=True, exist_ok=True)
    commit, repo = entry[label + "_commit"], entry["repository"]
    api = f"https://api.github.com/repos/{repo}"
    metadata = _metadata(entry, label, json_bytes(fetch(f"{api}/commits/{commit}")))
    tree_sha = metadata["commit"]["tree"]["sha"]
    tree_bytes = bounded_bytes(fetch(f"{api}/git/trees/{tree_sha}?recursive=1"))
    tree = json_bytes(tree_bytes)
    if tree.get("sha") != tree_sha:
        raise ValueError("source tree response identity mismatch")
    payload = bounded_bytes(fetch(f"https://codeload.github.com/{repo}/zip/{commit}"))
    with tempfile.TemporaryDirectory(prefix="source-stage-", dir=versions) as temporary:
        stage = checked_root(Path(temporary))
        (stage / "archive.zip").write_bytes(payload)
        files, links = read_catalog_zip(
            stage / "archive.zip",
            expected_sha256=sha256(payload),
            root_prefix=f"{repo.split('/')[1]}-{commit}",
            tree=tree,
        )
        verify_catalog_files(files, links, tree)
        if not any("/" not in n and n.upper().startswith(("LICENSE", "COPYING")) for n in files):
            raise ValueError("fixed source is missing root license files")
        write_new_json(stage / "commit.json", metadata)
        (stage / "tree.json").write_bytes(tree_bytes)
        for name, content in files.items():
            path = contained(stage / "source", name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        evidence = _evidence(entry, label, stage)
        write_new_json(stage / "version.json", evidence)
        # Windows readers can intermittently deny directory rename. Publish to
        # a fresh directory; version.json is the final completeness marker.
        target.mkdir(parents=True, exist_ok=False)
        for name, content in {
            "archive.zip": payload,
            "commit.json": canonical(metadata),
            "tree.json": tree_bytes,
        }.items():
            with (target / name).open("xb") as stream:
                stream.write(content)
        for name, content in files.items():
            path = contained(target / "source", name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
        if _evidence(entry, label, target) != evidence:
            raise ValueError("published source bytes differ from verified staging data")
        write_new_json(target / "version.json", evidence)
    return {**evidence, "path": str(target)}


def metadata_fetcher(root: Path):
    """Use a trusted metadata mirror, never credentials; archive fetch remains bounded."""
    root = checked_root(root)

    def fetch(url):
        _download_url(url)
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname == "codeload.github.com":
            return fetch_bytes(url)
        match = re.fullmatch(
            r"/repos/([\w.-]+)/([\w.-]+)/(commits|git/trees)/([0-9a-f]{40})", parsed.path
        )
        if match is None:
            raise ValueError("metadata mirror accepts only pinned commit/tree requests")
        owner, repo, kind, commit = match.groups()
        if parsed.query != ("recursive=1" if kind == "git/trees" else ""):
            raise ValueError("unexpected metadata query")
        directory = "trees" if kind == "git/trees" else "commits"
        return read_bounded(contained(root, f"{owner}/{repo}/{directory}/{commit}.json"))

    return fetch
