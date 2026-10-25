"""Owned ZIP/Git trees exercise real data validation, never upstream execution."""

import hashlib
import importlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest


def api():
    name = "benchmarks.evaluation.catalog_source_cache"
    assert importlib.util.find_spec(name) is not None, "catalog source cache is missing"
    return importlib.import_module(name)


def entry_fixture():
    return {
        "id": "os_demo_7",
        "revision": 1,
        "source_kind": "opensource",
        "split": "holdout",
        "repository": "owner/demo",
        "pull_request": 7,
        "title": "Fix returned value",
        "buggy_commit": "a" * 40,
        "fixed_commit": "b" * 40,
        "fixed_parents": ["a" * 40],
        "merged_at": "2026-01-01T00:00:00Z",
        "source_root": "src/demo",
        "reference_source_paths": ["src/demo/__init__.py"],
        "upstream_test_paths": ["tests/test_demo.py"],
        "upstream_ai_assistance": "unknown",
        "legacy_manifest": None,
    }


def owned_responses(*, source_contents=None, documentation_link=None):
    entry = entry_fixture()
    replies = {}
    for label, sha, tree_sha, value in (
        ("buggy", "a" * 40, "c" * 40, b"wrong"),
        ("fixed", "b" * 40, "d" * 40, b"right"),
    ):
        files = {
            "LICENSE": b"Owned fixture license; not an upstream license.\n",
            "src/demo/__init__.py": b"raise RuntimeError('must never import')\nvalue = '"
            + value
            + b"'\n",
            "tests/test_demo.py": b"raise RuntimeError('must never run tests')\n# " + value + b"\n",
        }
        if source_contents is not None:
            files["src/demo/__init__.py"] = source_contents[label]
        if documentation_link is not None:
            files["CHANGELOG.md"] = b"Owned changelog.\n"
            files[documentation_link[0]] = documentation_link[1]
        api_root = "https://api.github.com/repos/owner/demo"
        replies[f"{api_root}/commits/{sha}"] = json.dumps(
            {
                "sha": sha,
                "commit": {"tree": {"sha": tree_sha}},
                "parents": [{"sha": "a" * 40}] if label == "fixed" else [],
            }
        ).encode()
        tree = {"sha": tree_sha, "truncated": False, "tree": []}
        for name, content in files.items():
            blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            tree["tree"].append(
                {"path": name, "type": "blob", "mode": "100644", "size": len(content), "sha": blob}
            )
            if documentation_link is not None and name == documentation_link[0]:
                tree["tree"][-1]["mode"] = "120000"
        replies[f"{api_root}/git/trees/{tree_sha}?recursive=1"] = json.dumps(tree).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as stream:
            for name, content in files.items():
                member = zipfile.ZipInfo(f"demo-{sha}/{name}")
                if documentation_link is not None and name == documentation_link[0]:
                    member.create_system = 3
                    member.external_attr = 0o120777 << 16
                stream.writestr(member, content)
        replies[f"https://codeload.github.com/owner/demo/zip/{sha}"] = buffer.getvalue()
    return entry, replies


def test_verified_archive_is_data_not_imported(tmp_path):
    entry, replies = owned_responses()
    result = api().prepare_version(entry, "buggy", tmp_path / "versions", fetch=replies.__getitem__)
    assert result["status"] == "source_verified"
    source = Path(result["path"]) / "source"
    assert (
        (source / "src/demo/__init__.py")
        .read_bytes()
        .startswith(b"raise RuntimeError('must never import')")
    )
    assert (source / "LICENSE").read_bytes() == b"Owned fixture license; not an upstream license.\n"
    assert (
        result["licenses"]["LICENSE"]["sha256"]
        == hashlib.sha256((source / "LICENSE").read_bytes()).hexdigest()
    )
    assert not list(tmp_path.rglob("*.pyc"))


@pytest.mark.parametrize("problem", ["commit", "tree", "blob", "missing_license", "wrong_parent"])
def test_mismatched_provenance_is_never_published(problem, tmp_path):
    entry, replies = owned_responses()
    commit_url = "https://api.github.com/repos/owner/demo/commits/" + "b" * 40
    tree_url = "https://api.github.com/repos/owner/demo/git/trees/" + "d" * 40 + "?recursive=1"
    if problem in {"commit", "wrong_parent"}:
        value = json.loads(replies[commit_url])
        if problem == "commit":
            value["sha"] = "e" * 40
        else:
            value["parents"] = [{"sha": "e" * 40}]
        replies[commit_url] = json.dumps(value).encode()
    elif problem in {"tree", "blob"}:
        value = json.loads(replies[tree_url])
        if problem == "tree":
            value["sha"] = "e" * 40
        else:
            value["tree"][0]["sha"] = "e" * 40
        replies[tree_url] = json.dumps(value).encode()
    else:
        # Source bytes and tree agree, but there is no usable root license file.
        value = json.loads(replies[tree_url])
        value["tree"] = [e for e in value["tree"] if e["path"] != "LICENSE"]
        replies[tree_url] = json.dumps(value).encode()
        url = "https://codeload.github.com/owner/demo/zip/" + "b" * 40
        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(replies[url])) as original,
            zipfile.ZipFile(output, "w") as stream,
        ):
            for info in original.infolist():
                if not info.filename.endswith("/LICENSE"):
                    stream.writestr(info, original.read(info))
        replies[url] = output.getvalue()
    with pytest.raises(ValueError):
        api().prepare_version(entry, "fixed", tmp_path / "versions", fetch=replies.__getitem__)
    assert not (tmp_path / "versions/owner/demo" / ("b" * 40)).exists()


@pytest.mark.parametrize(
    "file", ["source/src/demo/__init__.py", "archive.zip", "commit.json", "tree.json"]
)
def test_cached_version_is_rechecked_before_reuse(file, tmp_path):
    entry, replies = owned_responses()
    versions = tmp_path / "versions"
    result = api().prepare_version(entry, "fixed", versions, fetch=replies.__getitem__)
    target = Path(result["path"]) / file
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(ValueError):
        api().verify_version(entry, "fixed", versions)


def test_valid_cache_is_reused_without_network(tmp_path):
    entry, replies = owned_responses()
    versions = tmp_path / "versions"
    first = api().prepare_version(entry, "fixed", versions, fetch=replies.__getitem__)

    def no_network(url):
        raise AssertionError("cache reuse must not fetch " + url)

    second = api().prepare_version(entry, "fixed", versions, fetch=no_network)
    assert second == first


def test_metadata_mirror_is_data_only_and_missing_does_not_fall_back(tmp_path):
    cache = api()
    directory = tmp_path / "metadata/owner/demo/commits"
    directory.mkdir(parents=True)
    payload = b'{"sha":"' + b"a" * 40 + b'"}'
    path = directory / ("a" * 40 + ".json")
    path.write_bytes(payload)
    fetch = cache.metadata_fetcher(tmp_path / "metadata")
    assert fetch("https://api.github.com/repos/owner/demo/commits/" + "a" * 40) == payload
    with pytest.raises(OSError):
        fetch("https://api.github.com/repos/owner/demo/commits/" + "b" * 40)
    assert path.read_bytes() == payload


def test_document_link_is_verified_as_metadata_never_materialized(tmp_path):
    entry, replies = owned_responses(documentation_link=("docs/changelog.md", b"../CHANGELOG.md"))
    result = api().prepare_version(entry, "buggy", tmp_path / "versions", fetch=replies.__getitem__)
    source = Path(result["path"]) / "source"
    assert not (source / "docs/changelog.md").exists()
    assert result["documentation_links"]["docs/changelog.md"]["target"] == "../CHANGELOG.md"
    assert result["documentation_links"]["docs/changelog.md"]["materialized"] is False
    assert result["documentation_links"]["docs/changelog.md"]["mode"] == "120000"
    assert api().verify_version(entry, "buggy", tmp_path / "versions") == result


@pytest.mark.parametrize(
    ("link", "target"),
    [
        ("src/demo/alias.py", b"../../CHANGELOG.md"),
        ("tests/alias.py", b"../CHANGELOG.md"),
        ("docs/alias.py", b"../CHANGELOG.md"),
        ("docs/changelog.md", b"/etc/passwd"),
        ("docs/changelog.md", b"../../outside"),
        ("docs/changelog.md", b"../MISSING.md"),
        ("docs/changelog.md", b"../src/demo/__init__.py"),
        ("docs/changelog.md", b"..\\CHANGELOG.md"),
    ],
)
def test_only_internal_document_to_document_links_are_accepted(link, target, tmp_path):
    entry, replies = owned_responses(documentation_link=(link, target))
    with pytest.raises(ValueError):
        api().prepare_version(entry, "buggy", tmp_path / "versions", fetch=replies.__getitem__)
    assert not (tmp_path / "versions/owner/demo" / ("a" * 40)).exists()


def test_document_link_verification_needs_no_temporary_directory(tmp_path, monkeypatch):
    import tempfile

    entry, replies = owned_responses(documentation_link=("docs/changelog.md", b"../CHANGELOG.md"))
    versions = tmp_path / "versions"
    prepared = api().prepare_version(entry, "buggy", versions, fetch=replies.__getitem__)

    def no_filesystem_scratch(*args, **kwargs):
        raise AssertionError("offline verification must not write temporary directories")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", no_filesystem_scratch)
    assert api().verify_version(entry, "buggy", versions) == prepared
