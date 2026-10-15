"""Immutable experiment identity and append-only trial journal."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from pathlib import Path
from uuid import uuid4

from pyrepair.config import ALLOWED_MODELS

from .agent_worker import WORKER_TIMEOUT, collect_result, run_agent
from .cases import EvaluationCase, case_fingerprint, contained
from .grading import grade_patch, validate_case, write_json

PROTOCOL = 2
ROOT = Path(__file__).resolve().parents[2]


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def runtime_identity() -> dict:
    files = [
        *sorted((ROOT / "src").rglob("*.py")),
        *sorted((ROOT / "benchmarks/evaluation").glob("*.py")),
        ROOT / "pyproject.toml",
    ]
    if (ROOT / "benchmarks/run_evaluation.py").exists():
        files.append(ROOT / "benchmarks/run_evaluation.py")
    return {
        "source_hash": digest(
            {
                p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in files
            }
        ),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": sorted(
            (d.metadata["Name"], d.version)
            for d in importlib.metadata.distributions()
            if d.metadata["Name"]
        ),
    }


def _identity(cases: list[EvaluationCase], model: str, trials: int) -> dict:
    return {
        "protocol": PROTOCOL,
        "model": model,
        "trials": trials,
        "max_attempts": 3,
        "max_tool_calls": 8,
        "worker_timeout": WORKER_TIMEOUT,
        "randomness": "provider default; no seed supplied",
        "runtime": runtime_identity(),
        "cases": [
            {
                "id": c.id,
                "fingerprint": case_fingerprint(c),
                "suite": c.suite,
                "split": c.split,
                "source_kind": c.source_kind,
            }
            for c in cases
        ],
    }


def create_experiment(cases: list[EvaluationCase], output: Path, model: str, trials: int) -> Path:
    if model not in ALLOWED_MODELS or type(trials) is not int or not 1 <= trials <= 100:
        raise ValueError("invalid model or trial count (1..100)")
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("empty or duplicate tasks")
    identity = _identity(cases, model, trials)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = {
        "version": PROTOCOL,
        "experiment_id": uuid4().hex,
        "identity": identity,
        "identity_hash": digest(identity),
    }
    write_json(output / "experiment.json", config)
    for case in cases:
        validation = validate_case(case, output / "validation" / case.id)
        if validation["status"] != "valid":
            raise ValueError(f"invalid task: {case.id}; see {output / 'validation'}")
    return output


def load_config(path: Path) -> dict:
    config = json.loads((path / "experiment.json").read_text(encoding="utf-8"))
    if (
        not isinstance(config, dict)
        or config.get("version") != PROTOCOL
        or not isinstance(config.get("identity"), dict)
        or config.get("identity_hash") != digest(config["identity"])
    ):
        raise ValueError("invalid experiment identity; v1 results cannot be resumed")
    return config


def load_events(path: Path) -> list[dict]:
    config = load_config(path)
    journal = path / "trials.jsonl"
    if not journal.exists():
        return []
    case_ids = {c["id"] for c in config["identity"]["cases"]}
    events, states, terminal = [], {}, set()
    for line in journal.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if (
            not isinstance(event, dict)
            or event.get("version") != PROTOCOL
            or event.get("experiment_id") != config["experiment_id"]
            or event.get("case_id") not in case_ids
            or type(event.get("trial_index")) is not int
            or not 1 <= event["trial_index"] <= config["identity"]["trials"]
            or type(event.get("execution_index")) is not int
            or event["execution_index"] < 1
            or event.get("event") not in {"started", "agent_finished", "trial_finished"}
        ):
            raise ValueError("invalid trial journal event")
        slot = (event["case_id"], event["trial_index"])
        key = (*slot, event["execution_index"])
        stage = event["event"]
        previous = states.get(key)
        if (
            slot in terminal
            or (stage == "started" and previous is not None)
            or (stage == "agent_finished" and previous != "started")
            or (stage == "trial_finished" and previous != "agent_finished")
        ):
            raise ValueError("invalid trial journal transition")
        states[key] = stage
        if stage == "trial_finished":
            if not isinstance(event.get("record"), dict):
                raise ValueError("missing final trial record")
            terminal.add(slot)
        if stage == "agent_finished" and not isinstance(event.get("agent"), dict):
            raise ValueError("missing Agent result")
        events.append(event)
    return events


def _append(path: Path, event: dict) -> None:
    with (path / "trials.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def final_records(events: list[dict]) -> list[dict]:
    return [e["record"] for e in events if e["event"] == "trial_finished"]


def report_records(path: Path) -> list[dict]:
    """Include unfinished execution evidence without counting it as a terminal trial."""
    events = load_events(path)
    records = final_records(events)
    done = {(r["case_id"], r["trial_index"]) for r in records}
    for cid, trial in sorted({(e["case_id"], e["trial_index"]) for e in events} - done):
        slot = [e for e in events if (e["case_id"], e["trial_index"]) == (cid, trial)]
        index = max(e["execution_index"] for e in slot)
        folder = path / "trials" / cid / str(trial)
        partial = []
        for number in range(1, index + 1):
            finished = next(
                (
                    e
                    for e in slot
                    if e["execution_index"] == number and e["event"] == "agent_finished"
                ),
                None,
            )
            partial.append(
                finished["agent"]
                if finished
                else collect_result(folder / f"execution-{number}" / "agent")
            )
        records.append(
            {
                "case_id": cid,
                "trial_index": trial,
                "execution_index": index,
                "pending": True,
                "passed": False,
                "agent": partial[-1],
                "grade": {"status": "not_run"},
                "cost_complete": False,
                "interrupted_executions": index - 1,
                "interrupted_usage": partial[:-1],
                "execution_dir": (folder / f"execution-{index}").relative_to(path).as_posix(),
            }
        )
    return records


def run_experiment(path: Path, cases: list[EvaluationCase], agent_executor=None) -> list[dict]:
    path = path.resolve()
    config = load_config(path)
    identity = config["identity"]
    if digest(_identity(cases, identity["model"], identity["trials"])) != config["identity_hash"]:
        raise ValueError("experiment identity/fingerprint changed; create a new experiment")
    for case in cases:
        validation = json.loads(
            (path / "validation" / case.id / "validation.json").read_text(encoding="utf-8")
        )
        if validation.get("status") != "valid" or validation.get("fingerprint") != case_fingerprint(
            case
        ):
            raise ValueError("missing/invalid preflight fingerprint")
    lock = path / "writer.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(
            "writer.lock exists; confirm no active writer before manually removing it"
        ) from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        events = load_events(path)
        for case in cases:
            for trial in range(1, identity["trials"] + 1):
                slot = [e for e in events if e["case_id"] == case.id and e["trial_index"] == trial]
                if any(e["event"] == "trial_finished" for e in slot):
                    continue
                execution = max((e["execution_index"] for e in slot), default=0)
                last = [e for e in slot if e["execution_index"] == execution]
                finished = next((e for e in last if e["event"] == "agent_finished"), None)
                trial_dir = path / "trials" / case.id / str(trial)
                prior_output = trial_dir / f"execution-{execution}" / "agent"
                saved = prior_output / "agent-result.json"
                agent = finished["agent"] if finished else None
                if agent is None and execution and saved.is_file():
                    agent = json.loads(saved.read_text(encoding="utf-8"))
                if agent is None and execution:
                    recovered = collect_result(prior_output)
                    if recovered["completed_evidence"]:
                        agent = recovered
                        write_json(saved, agent)
                new_execution = agent is None
                if new_execution:
                    execution += 1
                base = {
                    "version": PROTOCOL,
                    "experiment_id": config["experiment_id"],
                    "case_id": case.id,
                    "trial_index": trial,
                    "execution_index": execution,
                }

                def append(kind, *, base=base, **data):
                    event = {**base, "event": kind, **data}
                    _append(path, event)
                    events.append(event)

                folder = trial_dir / f"execution-{execution}"
                agent_dir = folder / "agent"
                start = time.perf_counter()
                if new_execution:
                    agent_dir.mkdir(parents=True, exist_ok=False)
                    append("started")
                    try:
                        agent = (agent_executor or run_agent)(case, agent_dir, identity["model"])
                    except Exception as exc:  # noqa: BLE001 - persist executor faults as terminal trials
                        agent = collect_result(agent_dir)
                        agent.update(
                            status="executor_error", usage_complete=False, error=type(exc).__name__
                        )
                    agent["duration_seconds"] = time.perf_counter() - start
                    write_json(agent_dir / "agent-result.json", agent)
                if not finished:
                    append("agent_finished", agent=agent)
                if agent.get("status") not in {
                    "success",
                    "failed",
                    "error",
                    "timeout",
                    "environment_error",
                    "executor_error",
                }:
                    raise ValueError("invalid saved Agent result")
                grade_dir = folder / ("grade-" + uuid4().hex[:10])
                patch_path = agent.get("patch_path")
                grade_start = time.perf_counter()
                try:
                    patch = (
                        contained(agent_dir, patch_path).read_text(encoding="utf-8")
                        if patch_path
                        else ""
                    )
                except (OSError, ValueError) as exc:
                    grade = {
                        "status": "grader_error",
                        "error": type(exc).__name__,
                        "visible": None,
                        "hidden": None,
                    }
                    write_json(grade_dir / "grade.json", grade)
                else:
                    if not patch and agent["status"] in {
                        "error",
                        "timeout",
                        "environment_error",
                        "executor_error",
                    }:
                        grade = {"status": "not_run", "visible": None, "hidden": None}
                        write_json(grade_dir / "grade.json", grade)
                    else:
                        grade = grade_patch(case, patch, grade_dir)
                grader_seconds = time.perf_counter() - grade_start
                prior = [
                    collect_result(trial_dir / f"execution-{i}" / "agent")
                    for i in range(1, execution)
                ]
                record = {
                    **base,
                    "suite": case.suite,
                    "split": case.split,
                    "source_kind": case.source_kind,
                    "agent": agent,
                    "grade": grade,
                    "passed": agent["status"] == "success" and grade["status"] == "passed",
                    "execution_dir": folder.relative_to(path).as_posix(),
                    "grader_seconds": grader_seconds,
                    "grade_dir": grade_dir.relative_to(path).as_posix(),
                    "interrupted_executions": execution - 1,
                    "interrupted_usage": prior,
                    "cost_complete": bool(agent.get("usage_complete")) and execution == 1,
                }
                append("trial_finished", record=record)
        return final_records(events)
    finally:
        lock.unlink()
