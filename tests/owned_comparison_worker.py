"""Owned subprocess fixture, not a production CLI or a selectable provider."""

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from benchmarks.evaluation.comparison_budget import write_new
from benchmarks.evaluation.comparison_worker import run_job
from benchmarks.evaluation.container_protocol import read_json
from pyrepair.models import ModelTurn
from tests.fakes import FakeLLM
from tests.test_agent_worker_docker import successful_client
from tests.test_comparison_methods import PATCH


def main():
    if "DEEPSEEK_API_KEY" in os.environ:
        raise AssertionError("owned offline worker received a credential")
    job = read_json(Path(sys.argv[1]))
    if len(sys.argv) == 3 and sys.argv[2] == "leave-container":
        from benchmarks.evaluation import docker_runner as docker

        original = docker._cli

        def leave(arguments, **kwargs):
            result = original(arguments, **kwargs)
            if arguments[0] == "start":
                write_new(Path(job["output"]) / "owned-container-started.json", {"started": True})
                time.sleep(60)
            return result

        docker._cli = leave
        from benchmarks.evaluation.agent_input import PublicTaskSpec
        from benchmarks.evaluation.agent_test_runner import DockerAgentTestRunner

        runner = DockerAgentTestRunner(
            Path(job["environment"]["lock_path"]),
            PublicTaskSpec.from_dict(job["spec"]),
            Path(job["output"]) / "t",
        )
        runner.run(Path(job["repo"]))
        raise AssertionError("owned interrupted fixture unexpectedly returned")

    if job["slot"]["method"] == "single-shot":
        client = FakeLLM([ModelTurn(PATCH, None, (), 9, 3, "stop")])
    else:
        client = successful_client()
        call = client.turns[0].tool_calls[0]
        client.turns[0] = replace(
            client.turns[0],
            tool_calls=(
                replace(
                    call,
                    arguments={
                        **call.arguments,
                        "path": "src/app.py",
                    },
                ),
            ),
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("host pytest fallback is forbidden")

    from pyrepair.testing import TestRunner

    TestRunner.run = forbidden
    run_job(job, lambda config: client)
    write_new(
        Path(job["output"]) / "owned-requests.json",
        {"requests": json.loads(json.dumps(client.requests))},
    )


if __name__ == "__main__":
    main()
