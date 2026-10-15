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

from .cases import EvaluationCase, prepare_case
from .grading import clean_environment, execute, write_json

WORKER_TIMEOUT = 1800


class PublicContractContext:
    """Make the public task contract visible, without changing the Agent loop."""

    def __init__(self, builder):
        self.builder = builder

    def build(self, root, report):
        bundle = self.builder.build(root, report)
        contract = (root / "TASK.md").read_text(encoding="utf-8")
        if len(contract) > 4000:
            raise ValueError("public contract exceeds 4000 characters")
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
    return result


def run_agent(case: EvaluationCase, output: Path, model: str) -> dict:
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    from pyrepair.cli import build_coordinator
    from pyrepair.config import load_config
    from pyrepair.models import RepairRequest
    from pyrepair.recorder import RunRecorder

    config = load_config(model_override=args.model)
    coordinator = build_coordinator(config, model_enabled=True)
    coordinator.context_builder = PublicContractContext(coordinator.context_builder)
    coordinator.recorder_factory = lambda repo: RunRecorder(
        args.output, run_id="evaluation", sensitive_values=(config.api_key,)
    )
    code = 0
    try:
        coordinator.run(RepairRequest(repo=args.repo, model=args.model, max_attempts=3))
    except Exception as exc:  # noqa: BLE001 - worker boundary must persist every non-interrupt failure
        print(f"worker error: {type(exc).__name__}", flush=True)
        code = 2
    result = collect_result(args.output)
    if code:
        result.update(status="error", usage_complete=False)
    write_json(args.output / "agent-result.json", result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
