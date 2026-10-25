"""Trusted public-job worker. Upstream tests run only in the verified Docker runner."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .agent_input import PublicTaskSpec
from .agent_test_runner import DockerAgentTestRunner
from .comparison_budget import CallBudget, GuardedClient, write_new
from .comparison_methods import full_agent, single_shot
from .container_protocol import read_json
from .experiment import digest
from .live_plan import absolute_path, validate_job


def live_client(config):
    """Only the explicitly authorized worker route calls this function."""
    from pyrepair.deepseek import DeepSeekClient

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key.strip():
        raise ValueError("missing authorized worker credential")
    return DeepSeekClient(
        api_key=key,
        model=config["model"],
        base_url=config["endpoint"],
        timeout=90,
        max_retries=0,
    )


def _coordinator(client, config, output, runner):
    from pyrepair.cli import build_coordinator
    from pyrepair.config import AppConfig
    from pyrepair.recorder import RunRecorder
    from pyrepair.repair_agent import RepairAgent
    from pyrepair.review_agent import ReviewAgent

    # Reuse all production assembly except provider construction. There is one
    # caller-owned ModelClient shared by both roles and guarded by full_agent.
    key = getattr(client, "api_key", "")
    coordinator = build_coordinator(
        AppConfig(key, config["model"], base_url=config["endpoint"]),
        model_enabled=False,
        runner=runner,
    )
    coordinator.agent_factory = lambda registry: RepairAgent(client, registry)
    coordinator.reviewer_factory = lambda: ReviewAgent(client)
    coordinator.recorder_factory = lambda repo: RunRecorder(
        output, run_id="evaluation", sensitive_values=(key,)
    )
    return coordinator


def run_job(job, client_factory):
    """Tests supply an owned FakeLLM; the CLI supplies the one fixed live factory."""
    validate_job(job)
    output = absolute_path(job["output"])
    if (output / "candidate.json").exists():
        raise FileExistsError("candidate exists; workers never re-run")
    write_new(output / "worker-started.json", {"job_hash": digest(job)})
    budget = CallBudget(absolute_path(job["quota"]), job["call_limit"])
    spec = PublicTaskSpec.from_dict(job["spec"])
    slot = job["slot"]
    runner = (
        DockerAgentTestRunner(Path(job["environment"]["lock_path"]), spec, output / "t")
        if slot["method"] == "full-agent"
        else None
    )
    client = client_factory(job["config"])
    if slot["method"] == "single-shot":
        guarded = GuardedClient(
            client, budget, slot["slot"], "single-shot", 1, output / "responses"
        )
        return single_shot(job["evidence"], spec, guarded, output)
    coordinator = _coordinator(client, job["config"], output, runner)
    return full_agent(
        Path(job["repo"]), spec, job["evidence"], coordinator, budget, output, slot["slot"]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--execute-authorized", action="store_true")
    args = parser.parse_args(argv)
    try:
        job = read_json(absolute_path(args.job))
        # This capability is an accidental-invocation barrier, not a security
        # boundary against a malicious host. Only the parent checks human approval.
        if not args.execute_authorized or os.environ.get("PYREPAIR_APPROVED_JOB_HASH") != digest(
            job
        ):
            raise ValueError("worker requires an authorized parent capability")
        run_job(job, live_client)
        return 0
    except Exception as exc:  # noqa: BLE001 - print types only; no provider messages or secrets
        print(f"Controlled worker stopped: {type(exc).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
