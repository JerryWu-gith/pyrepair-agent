"""Actual Docker and new subprocess supervision; FakeLLM only, never a provider."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.evaluation.comparison_budget import read_usage
from benchmarks.evaluation.comparison_pack import prepare_pack, verify_pack
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.docker_runner import DockerTestRunner, _cli
from benchmarks.evaluation.layered_grading import grade_layered
from benchmarks.evaluation.live_plan import public_job
from benchmarks.evaluation.worker_supervisor import run_worker
from tests.test_agent_docker_integration import configured_lock
from tests.test_layered_grading import owned_case
from tests.test_public_edit_scope import scope_paths

pytestmark = pytest.mark.docker
ROOT = Path(__file__).resolve().parents[1]


def worker_command(job, *options):
    return [
        sys.executable,
        "-B",
        "-m",
        "tests.owned_comparison_worker",
        str(Path(job["output"]) / "job.json"),
        *options,
    ]


def test_new_process_both_methods_have_shared_role_budget_and_independent_docker_grades(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    case = owned_case(tmp_path)
    lock = configured_lock()
    pack_path = prepare_pack([case], tmp_path / "p", lock, "deepseek-flash")
    pack = verify_pack(pack_path, [case])
    quota = tmp_path / "o/q"
    first_user_messages = []
    for index, slot in enumerate(pack["identity"]["slots"][:2]):
        folder = tmp_path / "o" / f"s{index:04d}"
        job = public_job(pack_path, pack, slot, folder, quota, 37)
        result = run_worker(job, worker_command=worker_command(job))
        grade = grade_layered(
            case, result["patch"], tmp_path / f"g{index}", test_runner=DockerTestRunner(lock)
        )
        assert grade["core_passed"] is True
        assert grade["extended"]["status"] == "passed"
        assert read_json(folder / "supervision.json")["cleanup"]["status"] == "clean"
        requests = read_json(folder / "owned-requests.json")["requests"]
        first_user_messages.append(requests[0][0][1])
        facts = json.loads(first_user_messages[-1]["content"])
        assert scope_paths(facts["context"]["repo_overview"]) == list(case.allowed_source_paths)
        if slot["method"] == "full-agent":
            review = json.loads(requests[-1][0][1]["content"])
            task = review["task_contract"]["content"]
            assert scope_paths(task) == list(case.allowed_source_paths)
            assert task == job["evidence"]["context"]["task_contract"]
            assert review["task_contract"]["trusted"] is False
        assert "hidden_tests" not in str(requests)
        assert "gold.patch" not in str(requests)
        assert "DEEPSEEK_API_KEY" not in str(read_json(folder / "job.json"))
    assert first_user_messages[0] == first_user_messages[1]
    usage = read_usage(quota)
    assert usage["reserved_calls"] == 6
    assert {k: v["calls"] for k, v in usage["roles"].items()} == {
        "single-shot": 1,
        "repair": 4,
        "review": 1,
    }


def test_actual_worker_timeout_removes_only_its_recorded_container(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    case = owned_case(tmp_path)
    lock = configured_lock()
    pack_path = prepare_pack([case], tmp_path / "p", lock, "deepseek-flash")
    pack = verify_pack(pack_path, [case])
    folder = tmp_path / "o/s0000"
    job = public_job(pack_path, pack, pack["identity"]["slots"][0], folder, tmp_path / "o/q", 37)
    with pytest.raises(subprocess.TimeoutExpired):
        run_worker(job, worker_command=worker_command(job, "leave-container"), timeout=15)
    assert read_json(folder / "owned-container-started.json") == {"started": True}
    supervision = read_json(folder / "supervision.json")
    assert supervision["status"] == "timeout"
    assert supervision["cleanup"]["status"] == "clean"
    assert len(supervision["cleanup"]["removed"]) == 1
    verified = DockerTestRunner(lock).assert_environment_verified()
    cid = supervision["cleanup"]["removed"][0]
    assert (
        _cli(
            ["container", "ls", "--all", "--no-trunc", "--filter=id=" + cid, "--format={{.ID}}"],
            host=verified["engine"]["host"],
        ).strip()
        == ""
    )
