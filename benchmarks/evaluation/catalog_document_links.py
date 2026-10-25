"""Opt-in document-link provenance, without creating or following any symlink.

The original strict ZIP reader remains unchanged. Only registered internal
documentation links are recorded separately from materialized source files.
"""

from __future__ import annotations

import copy
import hashlib
import io
import posixpath
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from .opensource_archive import (
    DEFAULT_LIMITS,
    ArchiveError,
    _read_members,
    _safe_path,
    read_source_zip,
)
from .opensource_assets import verify_source_files


def _document(path):
    name = PurePosixPath(path)
    return name.suffix.lower() in {".md", ".rst", ".txt"} or name.name.upper().startswith(
        ("LICENSE", "COPYING")
    )


def _target(path, content, tree):
    _safe_path(path)
    if (
        not path.startswith("docs/")
        or PurePosixPath(path).suffix.lower() not in {".md", ".rst", ".txt"}
        or any(p in {"test", "tests"} for p in path.split("/"))
    ):
        raise ArchiveError("only documentation link paths are permitted")
    if len(content) > 4096:
        raise ArchiveError("documentation link target is too large")
    try:
        target = content.decode("utf-8")
    except UnicodeError as exc:
        raise ArchiveError("documentation link target is not UTF-8") from exc
    if (
        not target
        or target.startswith("/")
        or any(c in target for c in '\\:*?"<>|')
        or any(ord(c) < 32 for c in target)
    ):
        raise ArchiveError("unsafe documentation link target")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    _safe_path(resolved)
    if (
        not _document(resolved)
        or ("/" in resolved and not resolved.startswith("docs/"))
        or any(p in {"test", "tests"} for p in resolved.split("/"))
    ):
        raise ArchiveError("documentation link cannot target production or test files")
    destination = tree.get(resolved)
    if (
        destination is None
        or destination.get("type") != "blob"
        or destination.get("mode") not in {"100644", "100755"}
    ):
        raise ArchiveError("documentation link target is missing or not an ordinary document")
    return target, resolved


def read_catalog_zip(archive: Path, *, expected_sha256: str, root_prefix: str, tree: dict):
    _safe_path(root_prefix)
    if "/" in root_prefix:
        raise ArchiveError("expected a single source root component")
    entries = tree.get("tree")
    if (
        tree.get("truncated") is not False
        or not isinstance(entries, list)
        or len(entries) > DEFAULT_LIMITS.members
    ):
        raise ArchiveError("incomplete source tree")
    if any(not isinstance(e, dict) for e in entries):
        raise ArchiveError("invalid source tree entry")
    declared = {e.get("path"): e for e in entries if e.get("mode") == "120000"}
    if not declared:
        return read_source_zip(
            archive, expected_sha256=expected_sha256, root_prefix=root_prefix
        ), {}
    by_path = {e.get("path"): e for e in entries if isinstance(e.get("path"), str)}
    with archive.open("rb") as stream:
        original = stream.read(DEFAULT_LIMITS.archive_bytes + 1)
    if (
        len(original) > DEFAULT_LIMITS.archive_bytes
        or hashlib.sha256(original).hexdigest() != expected_sha256
    ):
        raise ArchiveError("source archive size or digest mismatch")
    links = {}
    try:
        with io.BytesIO() as normalized:
            with zipfile.ZipFile(archive) as source, zipfile.ZipFile(normalized, "w") as out:
                members = source.infolist()
                if len(members) > DEFAULT_LIMITS.members:
                    raise ArchiveError("archive member count exceeds limit")
                total = 0
                for info in members:
                    path = _safe_path(
                        info.orig_filename[:-1] if info.is_dir() else info.orig_filename
                    )
                    if path != root_prefix and not path.startswith(root_prefix + "/"):
                        raise ArchiveError("member outside expected source root")
                    relative = path[len(root_prefix) + 1 :]
                    if info.flag_bits & 1:
                        raise ArchiveError("encrypted archive member")
                    allowance = min(DEFAULT_LIMITS.file_bytes, DEFAULT_LIMITS.total_bytes - total)
                    if info.file_size > allowance:
                        raise ArchiveError("expanded archive size exceeds limit")
                    with source.open(info) as stream:
                        content = stream.read(allowance + 1)
                    if len(content) > allowance or len(content) != info.file_size:
                        raise ArchiveError("archive member size mismatch")
                    total += len(content)
                    mode = stat.S_IFMT(info.external_attr >> 16)
                    rewritten = copy.copy(info)
                    if mode == stat.S_IFLNK or relative in declared:
                        if mode != stat.S_IFLNK or relative not in declared or relative in links:
                            raise ArchiveError("archive link differs from declared Git link")
                        if declared[relative].get("type") != "blob":
                            raise ArchiveError("documentation link is not a Git blob")
                        raw_target, resolved = _target(relative, content, by_path)
                        links[relative] = {
                            "target": raw_target,
                            "resolved_target": resolved,
                            "raw": content,
                        }
                        rewritten.external_attr = (stat.S_IFREG | 0o644) << 16
                    out.writestr(rewritten, content)
            if set(links) != set(declared):
                raise ArchiveError("archive is missing declared documentation links")
            if len(normalized.getvalue()) > DEFAULT_LIMITS.archive_bytes:
                raise ArchiveError("normalized source archive exceeds size limit")
            # All original path, collision, mode and resource checks still run.
            normalized.seek(0)
            with zipfile.ZipFile(normalized) as stream:
                files = _read_members(stream, root_prefix, DEFAULT_LIMITS)
            return {p: b for p, b in files.items() if p not in links}, links
    except ArchiveError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ArchiveError("unreadable documentation-link source archive") from exc


def verify_catalog_files(files, links, tree):
    if not links:
        return verify_source_files(files, tree)
    combined = {**files, **{name: value["raw"] for name, value in links.items()}}
    normalized_tree = {
        **tree,
        "tree": [{**e, "mode": "100644"} if e.get("path") in links else e for e in tree["tree"]],
    }
    checked = verify_source_files(combined, normalized_tree)
    records = {
        name: {
            **checked["files"][name],
            "mode": "120000",
            "target": info["target"],
            "resolved_target": info["resolved_target"],
            "materialized": False,
        }
        for name, info in links.items()
    }
    return {
        **checked,
        "file_count": len(files),
        "total_bytes": sum(len(b) for b in files.values()),
        "files": {p: v for p, v in checked["files"].items() if p in files},
        "git_tree_file_count": checked["file_count"],
        "git_tree_total_bytes": checked["total_bytes"],
        "documentation_links": records,
        "link_policy": "documentation-metadata-only-v1",
    }
