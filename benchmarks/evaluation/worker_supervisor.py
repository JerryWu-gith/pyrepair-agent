"""Own one worker process; clean only recorded, fully identity-checked Docker CIDs."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import docker_runner as docker
from .comparison_budget import checked_path, write_new
from .container_protocol import IDENTITY, read_json, validate_request
from .experiment import digest
from .grading import clean_environment, execute
from .live_plan import absolute_path, validate_job

ROOT = Path(__file__).resolve().parents[2]


class WorkerError(RuntimeError):
    """Fatal infrastructure/protocol failure; the journal must pause, never retry."""


def _stages(root):
    pending, stages, count = [root], set(), 0
    while pending:
        current = checked_path(pending.pop())
        count += 1
        if count > 4096:
            raise ValueError("worker stage directory limit exceeded")
        if current.name.endswith(".docker") and (current / "input/request.json").exists():
            stages.add(current)
        for child in current.iterdir():
            checked_path(child)
            if child.is_dir():
                pending.append(child)
            elif child.name == "container.cid":
                stages.add(child.parent)
    return sorted(stages)


def cleanup_owned(root, environment_lock):
    """Run only after our child has exited. Never list/stop unrelated containers."""
    result = {"status": "clean", "removed": [], "absent": [], "errors": []}
    try:
        tests = absolute_path(root) / "t"
        checked_path(tests)
        if not tests.exists():
            return result
        stages = _stages(tests)
        if not stages:
            return result
        verified = docker.DockerTestRunner(environment_lock).assert_environment_verified()
        host, lock = verified["engine"]["host"], verified["lock"]
        seen = set()
        for stage in stages:
            request = validate_request(read_json(checked_path(stage / "input/request.json")))
            if (
                request["version"] != 2
                or request["environment_hash"] != verified["environment_hash"]
            ):
                raise ValueError("owned cleanup request identity mismatch")
            if re.fullmatch(r"[0-9a-f]{32}", request["run_id"]) is None:
                raise ValueError("invalid owned run identity")
            cid = docker._recorded_cid(stage)
            if cid is None or cid in seen:
                raise ValueError("missing or repeated owned CID")
            seen.add(cid)
            record = stage / "container.json"
            if record.exists() and read_json(checked_path(record)) != {
                "container_id": cid,
                **{k: request[k] for k in IDENTITY},
            }:
                raise ValueError("owned cleanup CID record mismatch")
            # An exact full-ID filter distinguishes already-removed from a daemon
            # inspection error. A daemon error must not be misread as absence.
            present = docker._cli(
                [
                    "container",
                    "ls",
                    "--all",
                    "--no-trunc",
                    "--filter=id=" + cid,
                    "--format={{.ID}}",
                ],
                host=host,
            ).strip()
            if not present:
                result["absent"].append(cid)
                continue
            if present != cid:
                raise ValueError("ambiguous owned Docker CID lookup")
            inspected = docker._inspect(cid, host)
            if inspected.get("Name") != "/pyrepair-" + request["run_id"]:
                raise ValueError("owned cleanup container name mismatch")
            docker._inspect_profile(
                inspected, lock, {"/input": stage / "input", "/output": stage / "output"}
            )
            deadline = time.monotonic() + 30
            docker._cli(["stop", "--time=5", cid], host=host, timeout=10)
            state = docker._inspect(cid, host, timeout=max(0.001, deadline - time.monotonic()))
            if state["State"].get("Running") is not False:
                raise ValueError("owned container did not stop")
            docker._cli(["rm", cid], host=host, timeout=max(0.001, deadline - time.monotonic()))
            result["removed"].append(cid)
    except Exception as exc:  # noqa: BLE001 - cleanup is fail-closed; never dump raw daemon messages
        result["status"] = "environment_error"
        result["errors"].append(type(exc).__name__)
    return result


def run_worker(job, *, credential=None, worker_command=None, timeout=1800):
    """An optional trusted test command permits owned offline process integration.

    Neither the public job nor any CLI flag can select a factory or executable.
    The normal command is fixed and has no host/upstream command tool.
    """
    validate_job(job)
    if type(timeout) not in (int, float) or not 0 < timeout <= 1800:
        raise ValueError("invalid worker deadline")
    if worker_command is None and (not isinstance(credential, str) or not credential.strip()):
        raise ValueError("authorized credential is required for the fixed live worker")
    output = absolute_path(job["output"])
    write_new(output / "job.json", job)  # Exclusive start: never spawn twice for this folder.
    env = clean_environment()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    env["PYREPAIR_APPROVED_JOB_HASH"] = digest(job)
    if credential is not None:
        env["DEEPSEEK_API_KEY"] = credential
    command = worker_command or [
        sys.executable,
        "-B",
        "-m",
        "benchmarks.evaluation.comparison_worker",
        "--job",
        str(output / "job.json"),
        "--execute-authorized",
    ]
    status, code, error = "worker_error", None, None
    try:
        code = execute(command, ROOT, env, output / "worker.log", timeout)
        status = "completed" if code == 0 else "worker_error"
    except subprocess.TimeoutExpired as exc:
        status, error = "timeout", exc
    except BaseException as exc:  # noqa: BLE001 - record cleanup, then re-raise the original interrupt
        status, error = "interrupted" if isinstance(exc, KeyboardInterrupt) else "worker_error", exc
    finally:
        cleanup = cleanup_owned(output, Path(job["environment"]["lock_path"]))
        if cleanup["status"] != "clean":
            status = "cleanup_error"
        write_new(
            output / "supervision.json",
            {
                "job_hash": digest(job),
                "status": status,
                "returncode": code,
                "error_type": type(error).__name__ if error else None,
                "cleanup": cleanup,
            },
        )
    if status == "cleanup_error":
        raise WorkerError("owned worker cleanup incomplete") from None
    if error is not None:
        raise error
    if code != 0:
        raise WorkerError("worker did not complete; no automatic request retry")
    candidate = read_json(checked_path(output / "candidate.json"))
    if candidate.get("status") == "simulated":
        raise WorkerError("a simulated candidate is not a worker result")
    return candidate
