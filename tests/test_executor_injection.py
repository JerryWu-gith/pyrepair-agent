"""The production assembly must never lose the caller's execution boundary."""

import json

import pytest

from pyrepair.cli import build_coordinator
from pyrepair.config import AppConfig
from pyrepair.models import PytestFailure, RepairRequest
from pyrepair.models import TestRun as Run
from pyrepair.workspace import WorkspaceManager

NODE = "tests/test_owned.py::test_add"


class OwnedExecutor:
    def __init__(self, falsey):
        self.falsey = falsey
        self.calls = []
        self.passed = False

    def __bool__(self):
        return not self.falsey

    def run(self, repo, target=None):
        assert (repo / "app.py").is_file()
        self.calls.append(target)
        return Run(
            ("owned-executor",),
            0 if self.passed else 1,
            "owned result",
            "",
            1,
            failures=()
            if self.passed
            else (
                PytestFailure(
                    NODE,
                    "call",
                    "failed",
                    "AssertionError",
                    "assert -1 == 5",
                    "tests/test_owned.py:4: AssertionError",
                    1,
                ),
            ),
            capture_source="plugin",
        )


def owned_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "tests/test_owned.py").write_text(
        "from app import add\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
    )
    return repo


@pytest.mark.parametrize("falsey", [False, True])
def test_injected_executor_drives_baseline_tool_and_both_verifier_runs(tmp_path, falsey):
    repo = owned_repo(tmp_path)
    executor = OwnedExecutor(falsey)
    coordinator = build_coordinator(AppConfig("", "deepseek-flash"), False, runner=executor)

    result = coordinator.run(RepairRequest(repo, dry_run=True))

    assert result.status == "dry_run"
    assert executor.calls == [None]
    report = json.loads((result.artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert report["failure"]["node_id"] == NODE
    session = WorkspaceManager().create(repo)
    try:
        executor.passed = True
        registry = coordinator.registry_factory(session, NODE)
        tool = registry.execute("run_target_test", {})
        assert tool.ok and tool.data["passed"] is True
        (session.working / "app.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        verified = coordinator.verifier.verify(session.working, NODE, {NODE}, session.snapshot())
        assert verified.passed is True
        assert executor.calls == [None, NODE, NODE, None]
    finally:
        session.cleanup()


def test_default_assembly_still_runs_owned_host_pytest_without_model(tmp_path):
    repo = owned_repo(tmp_path)
    coordinator = build_coordinator(AppConfig("", "deepseek-flash"), False)

    result = coordinator.run(RepairRequest(repo, dry_run=True))

    assert result.status == "dry_run"
    report = json.loads((result.artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert report["failure"]["node_id"] == NODE
