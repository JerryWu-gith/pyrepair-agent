"""Bounded, data-only reading of pinned upstream ZIP archives.

Nothing is extracted, imported or executed here. Callers must separately match
the returned bytes against the pinned upstream Git tree before materializing.
"""

from __future__ import annotations

import hashlib
import io
import re
import stat
import zipfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmarks.evaluation.cases import CaseError, safe_relative


@dataclass(frozen=True)
class ArchiveLimits:
    archive_bytes: int = 20 * 1024 * 1024
    total_bytes: int = 20 * 1024 * 1024
    file_bytes: int = 8 * 1024 * 1024
    members: int = 2000


DEFAULT_LIMITS = ArchiveLimits()


class ArchiveError(ValueError):
    """The archive cannot be safely interpreted as ordinary source files."""


def _safe_path(name: str) -> str:
    try:
        safe_relative(name)
    except CaseError as exc:
        raise ArchiveError(str(exc)) from exc
    # Windows also reserves the superscript variants COM¹/²/³ and LPT¹/²/³.
    if any(
        re.fullmatch(r"(COM|LPT)[¹²³]", part.split(".")[0], re.IGNORECASE)
        for part in name.split("/")
    ):
        raise ArchiveError(f"reserved device path: {name!r}")
    return name


def _register_path(
    path: str,
    is_dir: bool,
    seen: dict[str, tuple[str, bool]],
    explicit: set[str],
) -> None:
    if path.casefold() in explicit:
        raise ArchiveError(f"duplicate member: {path!r}")
    parts = path.split("/")
    for index in range(1, len(parts) + 1):
        ancestor = "/".join(parts[:index])
        directory = index < len(parts) or is_dir
        previous = seen.get(ancestor.casefold())
        if previous is not None and previous != (ancestor, directory):
            raise ArchiveError(f"case or file/directory conflict: {path!r}")
        seen[ancestor.casefold()] = (ancestor, directory)
    explicit.add(path.casefold())


def _read_members(
    stream: zipfile.ZipFile,
    root_prefix: str,
    limits: ArchiveLimits,
) -> dict[str, bytes]:
    members = stream.infolist()
    if len(members) > limits.members:
        raise ArchiveError("archive member count exceeds limit")
    seen: dict[str, tuple[str, bool]] = {}
    explicit: set[str] = set()
    files: dict[str, bytes] = {}
    total = 0
    for info in members:
        # ZipInfo.filename silently truncates at NUL; inspect orig_filename first.
        name = info.orig_filename
        directory = name.endswith("/")
        path = _safe_path(name[:-1] if directory else name)
        if path != root_prefix and not path.startswith(root_prefix + "/"):
            raise ArchiveError(f"member outside expected root: {name!r}")
        if path == root_prefix and not directory:
            raise ArchiveError("archive root must be a directory")
        mode = stat.S_IFMT(info.external_attr >> 16)
        expected_mode = stat.S_IFDIR if directory else stat.S_IFREG
        if mode not in {0, expected_mode}:
            raise ArchiveError(f"non-regular or inconsistent member: {name!r}")
        if info.flag_bits & 1:
            raise ArchiveError("encrypted members are not supported")
        _register_path(path, directory, seen, explicit)
        if directory:
            if info.file_size != 0:
                raise ArchiveError("directory member contains file data")
            continue
        allowance = min(limits.file_bytes, limits.total_bytes - total)
        if info.file_size > allowance:
            raise ArchiveError("expanded member or total size exceeds limit")
        with stream.open(info, "r") as member:
            content = member.read(allowance + 1)
        if len(content) > allowance:
            raise ArchiveError("actual expanded size exceeds limit")
        if len(content) != info.file_size:
            raise ArchiveError("member size does not match header")
        total += len(content)
        files[path[len(root_prefix) + 1 :]] = content
    if not files:
        raise ArchiveError("archive contains no ordinary files")
    return files


def read_source_zip(
    archive: Path,
    *,
    expected_sha256: str,
    root_prefix: str,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> dict[str, bytes]:
    """Return verified relative file bytes without extracting or executing."""
    if any(type(value) is not int or value <= 0 for value in asdict(limits).values()):
        raise ArchiveError("archive limits must be positive integers")
    _safe_path(root_prefix)
    if "/" in root_prefix:
        raise ArchiveError("expected root must be a single path component")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", expected_sha256
    ):
        raise ArchiveError("expected SHA-256 must be 64 hexadecimal characters")
    try:
        with archive.open("rb") as source:
            data = source.read(limits.archive_bytes + 1)
        if len(data) > limits.archive_bytes:
            raise ArchiveError("archive byte size exceeds limit")
        if hashlib.sha256(data).hexdigest() != expected_sha256.lower():
            raise ArchiveError("archive SHA-256 mismatch")
        with zipfile.ZipFile(io.BytesIO(data)) as stream:
            return _read_members(stream, root_prefix, limits)
    except ArchiveError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError, zlib.error) as exc:
        raise ArchiveError(f"unreadable ZIP archive: {exc}") from exc
