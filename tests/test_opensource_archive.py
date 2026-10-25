"""Archive tests use only hand-written bytes, never downloaded Python code."""

import hashlib
import stat
import warnings
import zipfile

import pytest


def make_zip(tmp_path, entries):
    path = tmp_path / "source.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # Deliberate duplicate member.
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            for name, data in entries:
                stream.writestr(name, data)
    return path


def read_archive(path, **kwargs):
    from benchmarks.evaluation.opensource_archive import read_source_zip

    kwargs.setdefault("expected_sha256", hashlib.sha256(path.read_bytes()).hexdigest())
    kwargs.setdefault("root_prefix", "repo-abc")
    return read_source_zip(path, **kwargs)


def test_archive_payload_is_data_only(tmp_path):
    canary = tmp_path / "executed"
    code = f"from pathlib import Path\nPath({str(canary)!r}).touch()\n".encode()
    archive = make_zip(
        tmp_path,
        [
            ("repo-abc/", b""),
            ("repo-abc/pkg/__init__.py", code),
            ("repo-abc/pkg/empty.py", b""),
            ("repo-abc/LICENSE", b"hand-written test license"),
        ],
    )
    assert read_archive(archive) == {
        "pkg/__init__.py": code,
        "pkg/empty.py": b"",
        "LICENSE": b"hand-written test license",
    }
    assert not canary.exists()
    assert not (tmp_path / "repo-abc").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape.py",
        "/repo-abc/file.py",
        "C:/repo-abc/file.py",
        "repo-abc/../escape.py",
        "repo-abc/./file.py",
        "repo-abc//file.py",
        "repo-abc/file\x01.py",
        "repo-abc/AUX.txt",
        "repo-abc/dir/COM1.py",
        "repo-abc/NUL",
        "repo-abc/COM¹.py",
        "repo-abc/file.",
        "repo-abc/dir /file.py",
        "repo-abc/file:stream",
        "repo-other/file.py",
        "repo-abc",
        "repo-abc//",
    ],
)
def test_unsafe_member_rejects_entire_archive(tmp_path, name):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    archive = make_zip(tmp_path, [("repo-abc/good.py", b"safe"), (name, b"bad")])
    with pytest.raises(ArchiveError):
        read_archive(archive)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.zip"]


@pytest.mark.parametrize(
    "names",
    [
        ("repo-abc/a.py", "repo-abc/a.py"),
        ("repo-abc/a.py", "repo-abc/A.py"),
        ("repo-abc/A/a.py", "repo-abc/a/b.py"),
        ("repo-abc/dir", "repo-abc/dir/file.py"),
        ("repo-abc/dir/file.py", "repo-abc/dir"),
        ("repo-abc/dir/", "repo-abc/dir/"),
        ("repo-abc/", "repo-abc/"),
    ],
)
def test_duplicate_or_conflicting_members_fail_closed(tmp_path, names):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    archive = make_zip(tmp_path, [(name, b"" if name.endswith("/") else b"x") for name in names])
    with pytest.raises(ArchiveError):
        read_archive(archive)


@pytest.mark.parametrize(
    "mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK, stat.S_IFDIR]
)
def test_non_regular_unix_file_is_rejected(tmp_path, mode):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    info = zipfile.ZipInfo("repo-abc/member")
    info.create_system = 3
    info.external_attr = (mode | 0o644) << 16
    with pytest.raises(ArchiveError):
        read_archive(make_zip(tmp_path, [(info, b"target")]))


def test_directory_cannot_carry_file_content(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    archive = make_zip(tmp_path, [("repo-abc/dir/", b"payload")])
    with pytest.raises(ArchiveError):
        read_archive(archive)


def test_nul_in_original_zip_name_is_not_silently_truncated(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    archive = make_zip(tmp_path, [("repo-abc/fileX.py", b"data")])
    archive.write_bytes(archive.read_bytes().replace(b"fileX.py", b"file\0.py"))
    with pytest.raises(ArchiveError):
        read_archive(archive)


def test_raw_backslash_name_is_rejected_on_windows_too(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    # The Windows ZIP writer normalizes backslashes. Change the raw member
    # headers after writing, so the reader actually receives the unsafe name.
    archive = make_zip(tmp_path, [("repo-abc/dirXfile.py", b"data")])
    archive.write_bytes(archive.read_bytes().replace(b"dirXfile.py", b"dir\\file.py"))
    with pytest.raises(ArchiveError):
        read_archive(archive)


@pytest.mark.parametrize("prefix", ["../repo", "repo/abc", "", "C:", "repo-abc/"])
def test_invalid_expected_root_is_rejected(tmp_path, prefix):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    with pytest.raises(ArchiveError):
        read_archive(make_zip(tmp_path, [("repo-abc/a", b"a")]), root_prefix=prefix)


@pytest.mark.parametrize("digest", ["0" * 64, "z" * 64, "", "1234"])
def test_digest_mismatch_or_malformed_digest_is_rejected(tmp_path, digest):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    with pytest.raises(ArchiveError):
        read_archive(make_zip(tmp_path, [("repo-abc/a", b"a")]), expected_sha256=digest)


def test_non_zip_bytes_are_rejected(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    archive = tmp_path / "source.zip"
    archive.write_bytes(b"not an archive")
    with pytest.raises(ArchiveError):
        read_archive(archive)


def test_invalid_deflate_stream_is_reported_as_archive_error(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    archive = make_zip(tmp_path, [("repo-abc/a", b"some payload")])
    data = bytearray(archive.read_bytes())
    name_size = int.from_bytes(data[26:28], "little")
    extra_size = int.from_bytes(data[28:30], "little")
    data[30 + name_size + extra_size] = 0x07  # Reserved DEFLATE block type.
    archive.write_bytes(data)
    with pytest.raises(ArchiveError):
        read_archive(archive)


def test_corrupt_member_crc_is_rejected_even_with_matching_archive_hash(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as stream:
        stream.writestr("repo-abc/a", b"unique payload")
    archive.write_bytes(archive.read_bytes().replace(b"unique payload", b"changedpayload"))
    with pytest.raises(ArchiveError):
        read_archive(archive)


@pytest.mark.parametrize("entries", [[], [("repo-abc/", b"")]])
def test_empty_file_set_is_rejected(tmp_path, entries):
    from benchmarks.evaluation.opensource_archive import ArchiveError

    with pytest.raises(ArchiveError):
        read_archive(make_zip(tmp_path, entries))


@pytest.mark.parametrize(
    "field,limit",
    [
        ("archive_bytes", 1),
        ("members", 1),
        ("file_bytes", 3),
        ("total_bytes", 7),
    ],
)
def test_each_resource_limit_is_enforced(tmp_path, field, limit):
    from benchmarks.evaluation.opensource_archive import ArchiveError, ArchiveLimits

    archive = make_zip(tmp_path, [("repo-abc/a", b"1234"), ("repo-abc/b", b"5678")])
    with pytest.raises(ArchiveError):
        read_archive(archive, limits=ArchiveLimits(**{field: limit}))


def test_limits_are_inclusive(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveLimits

    archive = make_zip(tmp_path, [("repo-abc/a", b"1234"), ("repo-abc/b", b"5678")])
    assert read_archive(
        archive,
        limits=ArchiveLimits(
            archive_bytes=archive.stat().st_size,
            members=2,
            file_bytes=4,
            total_bytes=8,
        ),
    ) == {"a": b"1234", "b": b"5678"}


def test_small_compressed_archive_cannot_expand_past_file_limit(tmp_path):
    from benchmarks.evaluation.opensource_archive import ArchiveError, ArchiveLimits

    archive = make_zip(tmp_path, [("repo-abc/a", b"x" * 4096)])
    with pytest.raises(ArchiveError):
        read_archive(archive, limits=ArchiveLimits(file_bytes=16))


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_limits_fail_closed(tmp_path, value):
    from benchmarks.evaluation.opensource_archive import ArchiveError, ArchiveLimits

    archive = make_zip(tmp_path, [("repo-abc/a", b"a")])
    with pytest.raises(ArchiveError):
        read_archive(archive, limits=ArchiveLimits(members=value))
