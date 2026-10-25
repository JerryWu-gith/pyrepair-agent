"""Process adapter around the unchanged PyRepair coordinator (explicit live use only)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from pyrepair.context_builder import validate_task_contract

from .cases import EvaluationCase, prepare_case
from .execution_policy import require_live_cases
from .grading import clean_environment, execute, write_json

WORKER_TIMEOUT = 1800


def exception_details(error: BaseException, sensitive_values: tuple[str, ...] = ()) -> dict:
    """Keep bounded, redacted causes without dumping frames, locals or credentials."""
    chain = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen and len(chain) < 5:
        seen.add(id(current))
        message = str(current)
        for secret in sensitive_values:
            if secret:
                message = message.replace(secret, "[REDACTED]")
        entry = {"type": type(current).__name__, "message": message[:2000]}
        for name in ("errno", "winerror"):
            value = getattr(current, name, None)
            if type(value) is int:
                entry[name] = value
        chain.append(entry)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return {"exception_chain": chain}


class PublicContractContext:
    """Make the public task contract visible, without changing the Agent loop."""

    def __init__(self, builder):
        self.builder = builder

    def build(self, root, report):
        bundle = self.builder.build(root, report)
        contract = validate_task_contract(
            (root / "TASK.md").read_text(encoding="utf-8"), required=True
        )
        overview = "Public task contract:\n" + contract + "\n" + bundle.repo_overview
        snippets = list(bundle.snippets)

        def size():
            return len(overview) + sum(len(s.content) for s in snippets)

        while snippets and size() > 16000:
            snippets.pop()
        return replace(
            bundle,
            repo_overview=overview,
            snippets=tuple(snippets),
            total_chars=size(),
            truncated=bundle.truncated or len(snippets) < len(bundle.snippets),
            task_contract=contract,
        )


def collect_result(output: Path) -> dict:
    artifacts = output / ".pyrepair/runs/evaluation"
    result = {
        "status": "error",
        "attempts": None,
        "patch_path": None,
        "tool_calls": None,
        "model_calls": {"repair": 0, "review": 0},
        "usage": {
            role: {"prompt_tokens": 0, "completion_tokens": 0} for role in ("repair", "review")
        },
        "usage_complete": False,
        "completed_evidence": False,
    }
    try:
        events = [
            json.loads(line)
            for line in (artifacts / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        usage_known = True
        for event in events:
            if event.get("type") == "model_turn" and event.get("role") in result["usage"]:
                result["model_calls"][event["role"]] += 1
                for name in ("prompt_tokens", "completion_tokens"):
                    value = event.get(name)
                    if type(value) is not int or value < 0:
                        raise ValueError("missing/invalid usage")
                    result["usage"][event["role"]][name] += value
                if event.get("prompt_tokens") == event.get("completion_tokens") == 0:
                    # Original client maps missing provider usage to 0/0.
                    usage_known = False
        report = json.loads((artifacts / "report.json").read_text(encoding="utf-8"))
        if report.get("status") in {"success", "failed", "error"}:
            result.update(
                status=report["status"],
                attempts=report.get("attempt_count"),
                failure_reason=report.get("failure_reason"),
            )
            attempts = report.get("attempts", [])
            result["tool_calls"] = sum(
                a["tool_calls_used"] for a in attempts if type(a.get("tool_calls_used")) is int
            )
        result["completed_evidence"] = report.get("status") in {
            "success",
            "failed",
            "error",
        } and any(
            e.get("type") == "run_finished" and e.get("status") == report["status"] for e in events
        )
        if report.get("failure_reason") == "deepseek_error":
            # Coordinator records this before raising; raw recovery must match
            # the normal worker exception path. Partial turns may be unrecorded.
            result["status"] = "error"
        result["usage_complete"] = (
            result["status"] in {"success", "failed"}
            and result["completed_evidence"]
            and usage_known
        )
        patch = artifacts / "fix.patch"
        if patch.is_file() and patch.stat().st_size:
            result["patch_path"] = patch.relative_to(output).as_posix()
    except (OSError, ValueError, TypeError, AttributeError):
        # Present counters are a lower bound, never a claim of zero API cost.
        result["usage_complete"] = False
    ledger_path = output / "model-usage.jsonl"
    if ledger_path.exists():
        from .agent_usage import read_response_usage

        try:
            accounted = read_response_usage(ledger_path)
            usage_known = accounted.pop("usage_known")
            if (
                result["status"] in {"success", "failed"}
                and result["completed_evidence"]
                and usage_known
                and (
                    accounted["model_calls"] != result["model_calls"]
                    or accounted["usage"] != result["usage"]
                )
            ):
                raise ValueError("response ledger contradicts completed coordinator trace")
            # Alternative source, never added to the same responses in trace.
            result.update(accounted)
            result["usage_complete"] = (
                result["status"] in {"success", "failed"}
                and result["completed_evidence"]
                and usage_known
            )
        except (OSError, ValueError, TypeError, KeyError):
            result.update(status="error", usage_complete=False, error="invalid_response_ledger")
    diagnostic = output / "worker-error.json"
    from_summary = not diagnostic.is_file()
    if from_summary:
        # The diagnostic write itself may fail. The child also preserves the
        # original cause in its summary; keep it when the parent collects again.
        # Never recover success, usage or other claims from that summary here.
        diagnostic = output / "agent-result.json"
    if diagnostic.is_file():
        try:
            details = json.loads(diagnostic.read_text(encoding="utf-8"))
            if from_summary:
                if not isinstance(details, dict):
                    raise ValueError("invalid saved worker summary")
                if "error_details" not in details:
                    return result
                details = details["error_details"]
            result.update(status="error", usage_complete=False)
            chain = details.get("exception_chain") if isinstance(details, dict) else None
            if (
                not isinstance(chain, list)
                or not chain
                or not all(
                    isinstance(item, dict)
                    and isinstance(item.get("type"), str)
                    and isinstance(item.get("message"), str)
                    for item in chain
                )
            ):
                raise ValueError("invalid exception chain")
            result["error_details"] = details
        except (OSError, ValueError, TypeError):
            result.update(
                status="error", usage_complete=False, error="invalid_worker_error_details"
            )
    return result


def run_agent(case: EvaluationCase, output: Path, model: str) -> dict:
    require_live_cases((case,))
    env = clean_environment()
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("missing DEEPSEEK_API_KEY (no model request was made)")
    root = Path(__file__).resolve().parents[2]
    env.update(
        DEEPSEEK_API_KEY=key,
        PYTEST_ADDOPTS="--rootdir=.",
        PYTHONPATH=os.pathsep.join((str(root / "src"), str(root))),
    )
    with tempfile.TemporaryDirectory(prefix="pyrepair-agent-input-") as temp:
        repo = prepare_case(case, Path(temp) / "repo")
        command = [
            sys.executable,
            "-m",
            "benchmarks.evaluation.agent_worker",
            "--repo",
            str(repo),
            "--output",
            str(output),
            "--model",
            model,
        ]
        try:
            code = execute(command, root, env, output / "worker.log", WORKER_TIMEOUT)
            result = collect_result(output)
            if code != 0:
                result.update(status="error", usage_complete=False, worker_exit_code=code)
        except subprocess.TimeoutExpired:
            result = collect_result(output)
            result.update(status="timeout", usage_complete=False)
        except OSError as exc:
            result = collect_result(output)
            result.update(
                status="environment_error", usage_complete=False, error=type(exc).__name__
            )
    return result


def build_evaluation_coordinator(config, output: Path, *, runner=None, record_usage=False):
    """Trusted assembly shared by the worker and owned offline FakeLLM validation."""
    from pyrepair.cli import build_coordinator
    from pyrepair.recorder import RunRecorder

    coordinator = build_coordinator(config, model_enabled=True, runner=runner)
    coordinator.context_builder = PublicContractContext(coordinator.context_builder)
    coordinator.recorder_factory = lambda repo: RunRecorder(
        output, run_id="evaluation", sensitive_values=(config.api_key,)
    )
    if record_usage:
        from .agent_usage import RecordingModelClient, ResponseLedger

        ledger = ResponseLedger(output / "model-usage.jsonl")
        agent_factory = coordinator.agent_factory
        reviewer_factory = coordinator.reviewer_factory

        def agent(registry):
            role = agent_factory(registry)
            role.client = RecordingModelClient(role.client, "repair", ledger)
            return role

        def reviewer():
            role = reviewer_factory()
            role.client = RecordingModelClient(role.client, "review", ledger)
            return role

        coordinator.agent_factory = agent
        coordinator.reviewer_factory = reviewer
    return coordinator


def _worker_runner(args):
    if args.public_task is None:
        if args.backend != "host" or args.environment_lock is not None:
            raise ValueError("Docker backend requires a public descriptor and environment lock")
        return None
    from .agent_input import PublicTaskSpec, validate_public_input
    from .container_protocol import read_json

    spec = PublicTaskSpec.from_dict(read_json(args.public_task))
    if spec.source_kind == "opensource":
        raise ValueError(
            "opensource live worker remains disabled; adapter validation is offline-only"
        )
    if args.backend != "docker" or args.environment_lock is None:
        raise ValueError("public descriptor requires explicit Docker backend and environment lock")
    validate_public_input(args.repo, spec)
    from .agent_test_runner import DockerAgentTestRunner

    return DockerAgentTestRunner(args.environment_lock, spec, args.output / "container-tests")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--backend", choices=("host", "docker"), default="host")
    parser.add_argument("--public-task", type=Path)
    parser.add_argument("--environment-lock", type=Path)
    args = parser.parse_args(argv)
    from pyrepair.config import load_config
    from pyrepair.models import RepairRequest

    runner = _worker_runner(args)  # Source/input/backend validation precedes credential setup.
    config = load_config(model_override=args.model)
    coordinator = build_evaluation_coordinator(
        config,
        args.output,
        runner=runner,
        record_usage=runner is not None,
    )
    code = 0
    details = None
    try:
        coordinator.run(RepairRequest(repo=args.repo, model=args.model, max_attempts=3))
    except Exception as exc:  # noqa: BLE001 - worker boundary must persist every non-interrupt failure
        details = exception_details(exc, (config.api_key,))
        print("worker error: " + json.dumps(details, ensure_ascii=False), flush=True)
        code = 2
        try:
            write_json(args.output / "worker-error.json", details)
        except OSError as write_error:
            # Preserve the original error in stdout and agent-result even when
            # this additional diagnostic file cannot be written.
            safe_error = exception_details(write_error, (config.api_key,))
            print("diagnostic write error: " + json.dumps(safe_error), flush=True)
    result = collect_result(args.output)
    if code:
        result.update(status="error", usage_complete=False, error_details=details)
    write_json(args.output / "agent-result.json", result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
