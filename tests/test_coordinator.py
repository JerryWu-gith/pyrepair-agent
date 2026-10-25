import json
from pathlib import Path

import pytest

from pyrepair.context_builder import ContextBuilder
from pyrepair.coordinator import CoordinatorError, RepairCoordinator
from pyrepair.deepseek import DeepSeekError
from pyrepair.feedback import FeedbackBuilder
from pyrepair.models import AgentRun, ModelTurn, PytestFailure, RepairRequest, ReviewResult
from pyrepair.models import TestRun as PytestRun
from pyrepair.policy import PatchPolicyGate
from pyrepair.pytest_parser import PytestParser
from pyrepair.recorder import RunRecorder
from pyrepair.repair_agent import RepairAgent
from pyrepair.review_agent import ReviewAgent
from pyrepair.testing import TestRunner as PytestRunner
from pyrepair.tools import ToolRegistry
from pyrepair.verifier import Verifier
from pyrepair.workspace import WorkspaceManager
from tests.fakes import FakeLLM, model_text_turn, model_tool_turn


def make_buggy_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)
    (repo / "app.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    (tests_dir / "test_app.py").write_text(
        "from app import add, multiply\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\ndef test_multiply():\n    assert multiply(2, 3) == 6\n",
        encoding="utf-8",
    )
    return repo


def approval_turn():
    return model_text_turn(
        json.dumps(
            {"approved": True, "risk": "low", "findings": [], "reason": "minimal fix"}
        )
    )


def build_coordinator(
    repo: Path,
    agent_factory,
    reviewer_factory,
    *,
    runner=None,
    workspaces=None,
    progress=None,
) -> RepairCoordinator:
    selected_runner = runner or PytestRunner(timeout_seconds=10)
    policy = PatchPolicyGate()
    return RepairCoordinator(
        workspaces=workspaces or WorkspaceManager(),
        runner=selected_runner,
        parser=PytestParser(),
        registry_factory=lambda session, node_id: ToolRegistry(
            session, selected_runner, node_id
        ),
        agent_factory=agent_factory,
        context_builder=ContextBuilder(),
        feedback_builder=FeedbackBuilder(),
        policy=policy,
        reviewer_factory=reviewer_factory,
        verifier=Verifier(selected_runner, policy),
        recorder_factory=lambda target_repo: RunRecorder(target_repo, run_id="test-run"),
        progress=progress,
    )


def test_coordinator_generates_patch_without_touching_original(tmp_path):
    repo = make_buggy_repo(tmp_path)
    original = (repo / "app.py").read_text(encoding="utf-8")
    agent_llm = FakeLLM(
        [
            model_tool_turn(
                "replace-1",
                "replace_text",
                {"path": "app.py", "old_text": "return a - b", "new_text": "return a + b"},
            ),
            model_tool_turn("diff-1", "show_diff", {}),
            model_tool_turn("target-1", "run_target_test", {}),
            model_text_turn("done"),
        ]
    )
    review_llm = FakeLLM([approval_turn()])
    phases = []
    coordinator = build_coordinator(
        repo,
        lambda registry: RepairAgent(agent_llm, registry),
        lambda: ReviewAgent(review_llm),
        progress=phases.append,
    )

    result = coordinator.run(RepairRequest(repo=repo))

    assert result.status == "success"
    assert result.attempts == 1
    assert (repo / "app.py").read_text(encoding="utf-8") == original
    assert "+    return a + b" in (result.artifact_dir / "fix.patch").read_text(
        encoding="utf-8"
    )
    report = json.loads((result.artifact_dir / "report.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (result.artifact_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert report["status"] == "success"
    assert sum(event.get("type") == "context_built" for event in events) == 1
    assert "baseline" in phases
    assert "verify" in phases


def test_coordinator_dry_run_never_builds_agent_or_reviewer(tmp_path):
    repo = make_buggy_repo(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not build model roles")

    coordinator = build_coordinator(repo, forbidden, forbidden)

    result = coordinator.run(RepairRequest(repo=repo, dry_run=True))

    assert result.status == "dry_run"
    assert result.attempts == 0
    assert (result.artifact_dir / "fix.patch").read_text(encoding="utf-8") == ""


class BaselineRunner:
    def run(self, repo, target=None):
        del repo, target
        return PytestRun(
            ("python", "-m", "pytest"),
            1,
            "unrelated text summary",
            "",
            10,
            failures=(
                PytestFailure(
                    "tests/test_a.py::test_a",
                    "call",
                    "failed",
                    "AssertionError",
                    "other",
                    "full other traceback",
                    1,
                ),
                PytestFailure(
                    "tests/test_z.py::test_z",
                    "call",
                    "failed",
                    "AssertionError",
                    "add",
                    "full selected traceback",
                    1,
                ),
            ),
            capture_source="plugin",
        )


class StaticRunRunner:
    def __init__(self, run):
        self.run_result = run

    def run(self, repo, target=None):
        del repo, target
        return self.run_result


def test_coordinator_prefers_requested_structured_failure_and_records_capture_metadata(tmp_path):
    repo = make_buggy_repo(tmp_path)
    coordinator = build_coordinator(
        repo,
        lambda registry: None,
        lambda: None,
        runner=BaselineRunner(),
    )

    result = coordinator.run(
        RepairRequest(repo=repo, test_target="tests/test_z.py::test_z", dry_run=True)
    )

    report = json.loads((result.artifact_dir / "report.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (result.artifact_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert report["failure"]["node_id"] == "tests/test_z.py::test_z"
    assert "traceback" not in report["failure"]
    assert events[0] == {
        "type": "baseline",
        "exit_code": 1,
        "duration_ms": 10,
        "capture_source": "plugin",
        "failure_count": 2,
    }


def test_coordinator_records_already_passing_baseline(tmp_path):
    repo = make_buggy_repo(tmp_path)
    coordinator = build_coordinator(
        repo,
        lambda registry: None,
        lambda: None,
        runner=StaticRunRunner(
            PytestRun(
                ("python", "-m", "pytest"),
                0,
                "1 passed",
                "",
                10,
                capture_source="plugin",
            )
        ),
    )

    result = coordinator.run(RepairRequest(repo=repo))

    assert result.status == "failed"
    assert result.failure_reason == "tests_already_pass"


def test_coordinator_records_baseline_launch_error(tmp_path):
    repo = make_buggy_repo(tmp_path)
    coordinator = build_coordinator(
        repo,
        lambda registry: None,
        lambda: None,
        runner=StaticRunRunner(
            PytestRun(
                ("python", "-m", "pytest"),
                None,
                "",
                "",
                10,
                launch_error="python unavailable",
            )
        ),
    )

    with pytest.raises(CoordinatorError, match="无法启动") as captured:
        coordinator.run(RepairRequest(repo=repo))

    report = json.loads((captured.value.artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert report["failure_reason"] == "baseline_launch_error"


def test_coordinator_records_incomplete_agent_after_patch(tmp_path):
    repo = make_buggy_repo(tmp_path)

    class IncompleteAgent:
        def __init__(self, registry):
            self.registry = registry

        def run(
            self,
            report,
            previous_feedback=(),
            *,
            context=None,
            attempt=1,
            max_attempts=3,
        ):
            del report, previous_feedback, context, attempt, max_attempts
            path = self.registry.workspace / "app.py"
            path.write_text(
                path.read_text(encoding="utf-8").replace("return a - b", "return a + b"),
                encoding="utf-8",
            )
            return AgentRun(False, (), "model_stopped")

    coordinator = build_coordinator(
        repo,
        IncompleteAgent,
        lambda: None,
        runner=BaselineRunner(),
    )

    result = coordinator.run(RepairRequest(repo=repo, max_attempts=1))

    report = json.loads((result.artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert report["attempts"][0]["outcome"] == "model_stopped"


def test_coordinator_records_unparseable_baseline(tmp_path):
    repo = make_buggy_repo(tmp_path)
    coordinator = build_coordinator(
        repo,
        lambda registry: None,
        lambda: None,
        runner=StaticRunRunner(
            PytestRun(("python", "-m", "pytest"), 1, "unparseable output", "", 10)
        ),
    )

    result = coordinator.run(RepairRequest(repo=repo))

    assert result.status == "failed"
    assert result.failure_reason == "unparseable_pytest_output"


def test_coordinator_records_deepseek_error(tmp_path):
    repo = make_buggy_repo(tmp_path)

    class RaisingAgent:
        def __init__(self, registry):
            self.registry = registry

        def run(
            self,
            report,
            previous_feedback=(),
            *,
            context=None,
            attempt=1,
            max_attempts=3,
        ):
            del report, previous_feedback, context, attempt, max_attempts
            raise DeepSeekError("service unavailable")

    coordinator = build_coordinator(
        repo,
        RaisingAgent,
        lambda: None,
        runner=BaselineRunner(),
    )

    with pytest.raises(CoordinatorError, match="DeepSeek") as captured:
        coordinator.run(RepairRequest(repo=repo))

    report = json.loads((captured.value.artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert report["failure_reason"] == "deepseek_error"


def test_coordinator_stops_after_three_attempts_without_patch(tmp_path):
    repo = make_buggy_repo(tmp_path)
    turns = []
    for attempt in range(3):
        turns.extend(
            [
                model_tool_turn(f"show-{attempt}", "show_diff", {}),
                model_text_turn("no patch"),
            ]
        )
    agent_llm = FakeLLM(turns)
    coordinator = build_coordinator(
        repo,
        lambda registry: RepairAgent(agent_llm, registry),
        lambda: ReviewAgent(FakeLLM([])),
    )

    result = coordinator.run(RepairRequest(repo=repo, max_attempts=3))

    assert result.status == "failed"
    assert result.attempts == 3
    assert result.failure_reason == "max_attempts_exceeded"
    assert len(agent_llm.requests) == 6


class DirectWriteAgent:
    def __init__(self, registry, writer) -> None:
        self.registry = registry
        self.writer = writer

    def run(
        self,
        report,
        previous_feedback=(),
        *,
        context=None,
        attempt=1,
        max_attempts=3,
    ):
        del report, previous_feedback, context, attempt, max_attempts
        self.writer(self.registry.workspace)
        return AgentRun(True, ())


class StaticReviewer:
    def __init__(self, result: ReviewResult) -> None:
        self.result = result

    def review(self, report, snapshot):
        return self.result


def test_coordinator_passes_contract_built_from_baseline_to_review(tmp_path):
    from benchmarks.evaluation.agent_worker import PublicContractContext

    repo = make_buggy_repo(tmp_path)
    contract = "Return the sum of two integers."
    (repo / "TASK.md").write_text(contract, encoding="utf-8")
    client = FakeLLM([approval_turn()])

    class BaselineBuilder(PublicContractContext):
        def build(self, root, report):
            assert root.name == "baseline"
            return super().build(root, report)

    def fix(workspace):
        path = workspace / "app.py"
        path.write_text(path.read_text().replace("return a - b", "return a + b"))

    coordinator = build_coordinator(
        repo, lambda registry: DirectWriteAgent(registry, fix), lambda: ReviewAgent(client)
    )
    coordinator.context_builder = BaselineBuilder(ContextBuilder())
    result = coordinator.run(RepairRequest(repo=repo, max_attempts=1))
    assert result.status == "success"
    assert json.loads(client.requests[0][0][1]["content"])["task_contract"] == {
        "trusted": False, "content": contract,
    }


def test_contract_reaches_repair_once_and_review_with_no_private_fields(tmp_path):
    from benchmarks.evaluation.agent_worker import PublicContractContext

    repo = make_buggy_repo(tmp_path)
    contract = "Return the sum of two integers."
    (repo / "TASK.md").write_text(contract, encoding="utf-8")
    agent_client = FakeLLM([
        model_tool_turn("edit", "replace_text", {
            "path": "app.py", "old_text": "return a - b", "new_text": "return a + b",
        }),
        model_tool_turn("diff", "show_diff", {}),
        model_tool_turn("test", "run_target_test", {}),
        model_text_turn("done"),
    ])
    reviewer_client = FakeLLM([approval_turn()])
    coordinator = build_coordinator(
        repo, lambda registry: RepairAgent(agent_client, registry),
        lambda: ReviewAgent(reviewer_client),
    )
    coordinator.context_builder = PublicContractContext(ContextBuilder())
    assert coordinator.run(RepairRequest(repo=repo, max_attempts=1)).status == "success"
    repair_text = json.dumps(agent_client.requests[0][0], ensure_ascii=False)
    assert repair_text.count(contract) == 1
    assert '"task_contract"' not in repair_text
    payload = json.loads(reviewer_client.requests[0][0][1]["content"])
    assert set(payload) == {"failure", "patch", "task_contract"}
    assert payload["task_contract"]["content"] == contract


def test_coordinator_rejects_policy_violation_before_review(tmp_path):
    repo = make_buggy_repo(tmp_path)
    reviewer_called = False

    def reviewer_factory():
        nonlocal reviewer_called
        reviewer_called = True
        return StaticReviewer(ReviewResult(True, "low", (), "ok"))

    coordinator = build_coordinator(
        repo,
        lambda registry: DirectWriteAgent(
            registry,
            lambda workspace: (workspace / ".env").write_text("SECRET=x\n", encoding="utf-8"),
        ),
        reviewer_factory,
    )

    result = coordinator.run(RepairRequest(repo=repo, max_attempts=1))

    assert result.status == "failed"
    assert reviewer_called is False
    assert not (repo / ".env").exists()


def test_coordinator_stops_when_review_rejects(tmp_path):
    repo = make_buggy_repo(tmp_path)

    def fix_add(workspace):
        path = workspace / "app.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace("return a - b", "return a + b"),
            encoding="utf-8",
        )

    coordinator = build_coordinator(
        repo,
        lambda registry: DirectWriteAgent(registry, fix_add),
        lambda: StaticReviewer(ReviewResult(False, "high", ("side effect",), "reject")),
    )

    result = coordinator.run(RepairRequest(repo=repo, max_attempts=1))

    assert result.status == "failed"
    assert result.failure_reason == "max_attempts_exceeded"
    assert "return a - b" in (repo / "app.py").read_text(encoding="utf-8")


def test_coordinator_records_review_model_token_usage(tmp_path: Path) -> None:
    repo = make_buggy_repo(tmp_path)

    def fix_add(workspace: Path) -> None:
        path = workspace / "app.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace("return a - b", "return a + b"),
            encoding="utf-8",
        )

    review_turn = ModelTurn(
        '{"approved":true,"risk":"low","findings":[],"reason":"ok"}',
        None,
        (),
        prompt_tokens=17,
        completion_tokens=5,
    )
    coordinator = build_coordinator(
        repo,
        lambda registry: DirectWriteAgent(registry, fix_add),
        lambda: ReviewAgent(FakeLLM([review_turn])),
    )

    result = coordinator.run(RepairRequest(repo=repo, max_attempts=1))

    events = [
        json.loads(line)
        for line in (result.artifact_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    review_events = [event for event in events if event.get("role") == "review"]
    assert review_events == [
        {
            "type": "model_turn",
            "role": "review",
            "attempt": 1,
            "prompt_tokens": 17,
            "completion_tokens": 5,
        }
    ]


def test_coordinator_detects_new_full_suite_regression(tmp_path):
    repo = make_buggy_repo(tmp_path)

    def fix_target_break_other(workspace):
        path = workspace / "app.py"
        text = path.read_text(encoding="utf-8")
        text = text.replace("return a - b", "return a + b")
        text = text.replace("return a * b", "return a + b")
        path.write_text(text, encoding="utf-8")

    coordinator = build_coordinator(
        repo,
        lambda registry: DirectWriteAgent(registry, fix_target_break_other),
        lambda: StaticReviewer(ReviewResult(True, "low", (), "approve")),
    )

    result = coordinator.run(RepairRequest(repo=repo, max_attempts=1))

    report = json.loads((result.artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert result.status == "failed"
    assert report["attempts"][0]["regression_failures"] == [
        "tests/test_app.py::test_multiply"
    ]


def test_coordinator_feeds_failed_patch_evidence_to_clean_second_attempt(tmp_path):
    repo = make_buggy_repo(tmp_path)
    agent_llm = FakeLLM(
        [
            model_tool_turn(
                "edit-1",
                "replace_text",
                {
                    "path": "app.py",
                    "old_text": "return a - b",
                    "new_text": "return a * b",
                },
            ),
            model_tool_turn("diff-1", "show_diff", {}),
            model_tool_turn("test-1", "run_target_test", {}),
            model_text_turn("first attempt done"),
            model_tool_turn("read-2", "read_file", {"path": "app.py"}),
            model_text_turn("second attempt stopped"),
        ]
    )
    coordinator = build_coordinator(
        repo,
        lambda registry: RepairAgent(agent_llm, registry),
        lambda: ReviewAgent(FakeLLM([approval_turn()])),
    )

    result = coordinator.run(RepairRequest(repo=repo, max_attempts=2))

    second_attempt_payload = json.loads(agent_llm.requests[4][0][1]["content"])
    previous = second_attempt_payload["previous_attempts"][0]
    assert previous["outcome"] == "verification_failed"
    assert "app.py" in previous["candidate_diff"]
    assert previous["policy_violations"] == []
    assert previous["review_findings"] == []
    assert previous["target_failure"]["summary"]
    assert previous["trusted"] is False

    second_request_tool = next(
        item
        for item in agent_llm.requests[5][0]
        if item.get("tool_call_id") == "read-2"
    )
    second_read = json.loads(second_request_tool["content"])
    assert "return a - b" in second_read["data"]["content"]
    assert result.metadata["attempts"][0]["feedback"]["outcome"] == "verification_failed"


class TimeoutRunner:
    def run(self, repo, target=None):
        return PytestRun(("python", "-m", "pytest"), None, "", "", 10, timed_out=True)


class TrackingWorkspaceManager(WorkspaceManager):
    def __init__(self) -> None:
        self.session = None

    def create(self, repo):
        self.session = super().create(repo)
        return self.session


def test_coordinator_records_timeout_and_cleans_workspace(tmp_path):
    repo = make_buggy_repo(tmp_path)
    workspaces = TrackingWorkspaceManager()
    coordinator = build_coordinator(
        repo,
        lambda registry: None,
        lambda: None,
        runner=TimeoutRunner(),
        workspaces=workspaces,
    )

    with pytest.raises(CoordinatorError, match="超时") as captured:
        coordinator.run(RepairRequest(repo=repo))

    assert workspaces.session is not None
    assert workspaces.session.root.exists() is False
    report = json.loads((captured.value.artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["failure_reason"] == "baseline_timeout"
