"""Public execution descriptors must not become a private-manifest side channel."""

import hashlib

import pytest

from tests.evaluation_helpers import make_case


def public_payload():
    return {
        "version": 1,
        "case_id": "owned",
        "revision": 1,
        "source_kind": "opensource",
        "visible_tests": ["tests/test_owned.py"],
        "timeout_seconds": 30,
        "input_policy": "agent-public-r2",
        "public_input_hash": "a" * 64,
    }


def test_prepared_input_filters_instructions_credentials_and_private_answers(tmp_path):
    from benchmarks.evaluation.agent_input import prepare_agent_input
    from benchmarks.evaluation.cases import load_cases

    case = load_cases(make_case(tmp_path / "assets"))[0]
    names = [
        ".omp/skills/release/SKILL.md",
        ".agents/notes.txt",
        ".claude/config.json",
        ".codex/config.toml",
        "docs/aGeNtS.Md",
        "docs/CLAUDE.md",
        "GEMINI.md",
        "docs/SKILL.md",
        ".env",
        ".env.local",
        ".envrc",
        ".env-production",
        ".environment",
        "__pycache__/stale.pyc",
        ".pyrepair/runs/private.json",
        ".mypy_cache/state.json",
    ]
    for name in names:
        path = case.buggy / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("worthless-owned-sentinel", encoding="utf-8")
    original = (case.buggy / "src/app.py").read_bytes()
    destination = tmp_path / "public"

    spec = prepare_agent_input(case, destination)

    assert (destination / "src/app.py").read_bytes() == original
    from tests.test_public_edit_scope import scope_paths

    assert (destination / "TASK.md").read_bytes().endswith(case.description.read_bytes())
    assert scope_paths((destination / "TASK.md").read_text("utf-8")) == ["src/app.py"]
    assert all(not (destination / name).exists() for name in names)
    assert not (destination / "hidden_tests").exists()
    assert not list(destination.rglob("*.patch"))
    assert all((case.buggy / name).exists() for name in names)
    assert spec.visible_tests == ("tests/test_app.py",)
    assert set(spec.to_dict()) == set(public_payload())
    assert "hidden" not in str(spec.to_dict())
    assert len(spec.public_input_hash) == 64


@pytest.mark.parametrize(
    "changes",
    [
        {"private_path": "private/answers"},
        {"hidden_tests": ["test_hidden.py"]},
        {"version": True},
        {"version": 2},
        {"case_id": "../owned"},
        {"case_id": ""},
        {"revision": True},
        {"revision": 0},
        {"source_kind": "unknown"},
        {"visible_tests": []},
        {"visible_tests": ["../test.py"]},
        {"visible_tests": ["-p"]},
        {"visible_tests": ["test.py::test_x"]},
        {"visible_tests": ["tests/test.py", "tests/test.py"]},
        {"timeout_seconds": 121},
        {"timeout_seconds": True},
        {"input_policy": "unverified"},
        {"public_input_hash": "short"},
    ],
)
def test_public_descriptor_rejects_extra_private_or_invalid_fields(changes):
    from benchmarks.evaluation.agent_input import PublicTaskSpec

    with pytest.raises(ValueError):
        PublicTaskSpec.from_dict(public_payload() | changes)


def test_public_descriptor_roundtrip_keeps_only_public_identity():
    from benchmarks.evaluation.agent_input import PublicTaskSpec

    spec = PublicTaskSpec.from_dict(public_payload())

    assert spec.to_dict() == public_payload()
    assert spec.visible_tests == ("tests/test_owned.py",)


def test_runtime_snapshot_filters_generated_artifacts_and_hashes_new_source(tmp_path):
    from benchmarks.evaluation.agent_input import stage_public_snapshot

    repo = tmp_path / "working"
    repo.mkdir()
    (repo / "test_owned.py").write_bytes(b"def test_owned():\n    assert True\n")
    (repo / "app.py").write_bytes(b"value = 1\n")
    (repo / ".pyrepair/internal").mkdir(parents=True)
    (repo / ".pyrepair/internal/secret.json").write_text("owned-sentinel")
    first = stage_public_snapshot(repo, tmp_path / "first", ("test_owned.py",))
    (repo / "app.py").write_bytes(b"value = 2\n")

    second = stage_public_snapshot(repo, tmp_path / "second", ("test_owned.py",))

    assert first["inventory"]["app.py"] == hashlib.sha256(b"value = 1\n").hexdigest()
    assert second["inventory"]["app.py"] == hashlib.sha256(b"value = 2\n").hexdigest()
    assert first["public_input_hash"] != second["public_input_hash"]
    assert "secret.json" not in str(second["inventory"])
    assert (tmp_path / "first/app.py").read_bytes() == b"value = 1\n"
    assert any(p.startswith(".pyrepair") for p in second["excluded"])


@pytest.mark.parametrize("required", [".agents/test_owned.py", "AGENTS.md"])
def test_required_file_cannot_be_silently_filtered(tmp_path, required):
    from benchmarks.evaluation.agent_input import stage_public_snapshot

    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / required
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("owned")

    with pytest.raises(ValueError, match="required|filtered"):
        stage_public_snapshot(repo, tmp_path / "filtered", (required,))


def test_snapshot_rejects_missing_selected_test_and_recursive_destination(tmp_path):
    from benchmarks.evaluation.agent_input import stage_public_snapshot

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "test_owned.py").write_text("owned")
    with pytest.raises(ValueError, match="missing|required"):
        stage_public_snapshot(repo, tmp_path / "missing", ("test_absent.py",))
    with pytest.raises(ValueError, match="overlap|inside"):
        stage_public_snapshot(repo, repo / "recursive", ("test_owned.py",))


def test_snapshot_does_not_overwrite_existing_evidence(tmp_path):
    from benchmarks.evaluation.agent_input import stage_public_snapshot

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "test_owned.py").write_text("owned")
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep")
    with pytest.raises((ValueError, FileExistsError)):
        stage_public_snapshot(repo, output, ("test_owned.py",))
    assert sentinel.read_text() == "keep"


def test_worker_input_validation_rejects_digest_change_and_excluded_files(tmp_path):
    from benchmarks.evaluation.agent_input import prepare_agent_input, validate_public_input
    from benchmarks.evaluation.cases import load_cases

    case = load_cases(make_case(tmp_path / "assets"))[0]
    repo = tmp_path / "public"
    spec = prepare_agent_input(case, repo)
    validate_public_input(repo, spec)
    (repo / ".env").write_text("worthless-sentinel")
    with pytest.raises(ValueError, match="excluded|filtered"):
        validate_public_input(repo, spec)
    (repo / ".env").unlink()  # Only the self-authored worthless fixture is removed.
    (repo / "src/app.py").write_text("changed\n")
    with pytest.raises(ValueError, match="digest|identity"):
        validate_public_input(repo, spec)
