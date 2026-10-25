"""Source checks use invented byte trees and HTTP responses, not upstream imports."""

import copy
import hashlib
import io
import json
import zipfile

import pytest

CASE_ID = "os_more_seekable_1269"
BUGGY = "1da45ae4b61a832ed080f08a8833784aad0a9534"
FIXED = "b5e3886a37209bb880f17d82fbf4ba00ece0e41e"


def git_blob(content):
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def tree_for(files, sha="a" * 40):
    return {
        "sha": sha,
        "truncated": False,
        "tree": [
            {
                "path": name,
                "mode": "100644",
                "type": "blob",
                "sha": git_blob(content),
                "size": len(content),
            }
            for name, content in files.items()
        ],
    }


def fake_downloads():
    responses = {}
    for commit, tree_sha, source in [
        (BUGGY, "a" * 40, b"raise RuntimeError('never import')\n"),
        (FIXED, "b" * 40, b"raise RuntimeError('also data')\n"),
    ]:
        files = {"LICENSE": b"fixture license", "pkg/__init__.py": source}
        api = "https://api.github.com/repos/more-itertools/more-itertools"
        responses[f"{api}/commits/{commit}"] = json.dumps(
            {
                "sha": commit,
                "commit": {"tree": {"sha": tree_sha}},
                "parents": [{"sha": BUGGY}] if commit == FIXED else [],
            }
        ).encode()
        responses[f"{api}/git/trees/{tree_sha}?recursive=1"] = json.dumps(
            tree_for(files, tree_sha)
        ).encode()
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as stream:
            for name, content in files.items():
                stream.writestr(f"more-itertools-{commit}/{name}", content)
        responses[f"https://codeload.github.com/more-itertools/more-itertools/zip/{commit}"] = (
            payload.getvalue()
        )
    return responses


def test_file_bytes_match_every_pinned_git_blob():
    from benchmarks.evaluation.opensource_assets import verify_source_files

    files = {"LICENSE": b"license", "pkg/a.py": b"raise RuntimeError('not executed')\n"}
    result = verify_source_files(files, tree_for(files))
    assert result["file_count"] == 2
    assert result["files"]["LICENSE"]["sha256"] == hashlib.sha256(b"license").hexdigest()
    assert set(result["files"]) == {"LICENSE", "pkg/a.py"}


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "extra",
        "modified",
        "blob",
        "size",
        "truncated",
        "symlink",
        "submodule",
        "unsafe",
        "duplicate",
        "case_collision",
    ],
)
def test_incomplete_or_unsafe_tree_is_rejected(problem):
    from benchmarks.evaluation.opensource_assets import verify_source_files

    files = {"LICENSE": b"license", "a.py": b"a"}
    tree = tree_for(files)
    if problem == "missing":
        del files["a.py"]
    elif problem == "extra":
        files["extra"] = b"extra"
    elif problem == "modified":
        files["a.py"] = b"different"
    elif problem == "blob":
        tree["tree"][0]["sha"] = "0" * 40
    elif problem == "size":
        tree["tree"][0]["size"] = 123
    elif problem == "truncated":
        tree["truncated"] = True
    elif problem == "symlink":
        tree["tree"][0]["mode"] = "120000"
    elif problem == "submodule":
        tree["tree"][0].update(type="commit", mode="160000")
    elif problem == "unsafe":
        tree["tree"][0]["path"] = "../outside"
    elif problem == "duplicate":
        tree["tree"].append(copy.deepcopy(tree["tree"][0]))
    else:
        tree["tree"].append({**tree["tree"][1], "path": "A.py"})
        files["A.py"] = b"a"
    with pytest.raises(ValueError):
        verify_source_files(files, tree)


def test_pinned_source_is_saved_without_execution(tmp_path, monkeypatch):
    from benchmarks.evaluation import opensource_assets as assets

    responses = fake_downloads()
    monkeypatch.setattr(assets, "fetch_bytes", lambda url, **kwargs: responses[url])
    output = tmp_path / "source"
    result = assets.prepare_source(CASE_ID, output)
    assert result["status"] == "source_verified"
    assert (output / "buggy/LICENSE").read_bytes() == b"fixture license"
    assert (output / "buggy/pkg/__init__.py").read_bytes().startswith(b"raise RuntimeError")
    saved = json.loads((output / "source-verification.json").read_text())
    assert saved["versions"]["buggy"]["commit"] == BUGGY
    assert saved["versions"]["fixed"]["commit"] == FIXED
    assert not list(output.rglob("*.pyc"))


@pytest.mark.parametrize(
    "problem",
    [
        "commit",
        "parent",
        "tree",
        "blob",
        "metadata_type",
        "tree_type",
        "parents_type",
    ],
)
def test_remote_metadata_mismatch_never_materializes_source(tmp_path, monkeypatch, problem):
    from benchmarks.evaluation import opensource_assets as assets

    responses = fake_downloads()
    prefix = "https://api.github.com/repos/more-itertools/more-itertools"
    url = f"{prefix}/commits/{FIXED}"
    payload = json.loads(responses[url])
    if problem == "commit":
        payload["sha"] = "f" * 40
    elif problem == "parent":
        payload["parents"][0]["sha"] = "f" * 40
    elif problem == "tree":
        url = f"{prefix}/git/trees/{'b' * 40}?recursive=1"
        payload = json.loads(responses[url])
        payload["sha"] = "f" * 40
    elif problem == "blob":
        url = f"{prefix}/git/trees/{'b' * 40}?recursive=1"
        payload = json.loads(responses[url])
        payload["tree"][0]["sha"] = "f" * 40
    elif problem == "metadata_type":
        payload = []
    elif problem == "tree_type":
        url = f"{prefix}/git/trees/{'b' * 40}?recursive=1"
        payload = []
    else:
        payload["parents"] = ["not a parent object"]
    responses[url] = json.dumps(payload).encode()
    monkeypatch.setattr(assets, "fetch_bytes", lambda url, **kwargs: responses[url])
    output = tmp_path / "source"
    with pytest.raises(ValueError):
        assets.prepare_source(CASE_ID, output)
    assert not (output / "buggy").exists()
    assert not (output / "fixed").exists()
    saved = json.loads((output / "source-verification.json").read_text())
    assert saved["status"] == "source_error"


def test_existing_source_directory_is_never_overwritten(tmp_path, monkeypatch):
    from benchmarks.evaluation import opensource_assets as assets

    output = tmp_path / "source"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_bytes(b"preserve")
    monkeypatch.setattr(assets, "fetch_bytes", lambda *a, **k: pytest.fail("must not download"))
    with pytest.raises(FileExistsError):
        assets.prepare_source(CASE_ID, output)
    assert sentinel.read_bytes() == b"preserve"
    assert sorted(p.name for p in output.iterdir()) == ["sentinel"]


def test_unknown_source_id_cannot_supply_a_url(tmp_path, monkeypatch):
    from benchmarks.evaluation import opensource_assets as assets

    monkeypatch.setattr(assets, "fetch_bytes", lambda *a, **k: pytest.fail("must not download"))
    output = tmp_path / "source"
    with pytest.raises(ValueError):
        assets.prepare_source("https://attacker.example/source.zip", output)
    assert not output.exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/x",
        "https://attacker.example/file",
        "https://user:secret@api.github.com/file",
        "https://api.github.com:444/file",
        "file:///etc/passwd",
        "https://api.github.com.evil.test/file",
    ],
)
def test_disallowed_download_url_is_rejected_before_network(url, monkeypatch):
    from benchmarks.evaluation import opensource_assets as assets

    monkeypatch.setattr(
        assets.urllib.request, "build_opener", lambda *a: pytest.fail("network must not start")
    )
    with pytest.raises(ValueError):
        assets.fetch_bytes(url)


def test_redirect_to_unapproved_host_is_rejected_before_following():
    from benchmarks.evaluation import opensource_assets as assets

    request = assets.urllib.request.Request("https://api.github.com/repos/x")
    with pytest.raises(ValueError):
        assets.SafeRedirect().redirect_request(
            request,
            None,
            302,
            "redirect",
            {},
            "https://attacker.example/file",
        )


def test_timeout_records_last_fixed_url_and_preserves_failure(tmp_path, monkeypatch):
    from benchmarks.evaluation import opensource_assets as assets

    responses = fake_downloads()
    url = f"https://api.github.com/repos/more-itertools/more-itertools/git/trees/{'a' * 40}?recursive=1"

    def timeout(target, **kwargs):
        if target == url:
            raise TimeoutError("read timed out")
        return responses[target]

    monkeypatch.setattr(assets, "fetch_bytes", timeout)
    with pytest.raises(TimeoutError):
        assets.prepare_source(CASE_ID, tmp_path / "failed")
    report = json.loads((tmp_path / "failed/source-verification.json").read_text())
    assert report["last_request"] == {"version": "buggy", "kind": "tree", "url": url}
    assert report["status"] == "source_error"
    assert not (tmp_path / "failed/buggy").exists()
