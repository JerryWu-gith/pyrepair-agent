"""Append-only paired slots. Resume local artifacts, never re-spend a started slot."""

from __future__ import annotations

import hashlib
import json
import math
from uuid import uuid4

from pyrepair.models import ModelTurn, ToolCallRequest

from .comparison_budget import append_event, checked_path, exclusive, write_new
from .comparison_methods import extract_patch
from .comparison_pack import file_hash
from .container_protocol import read_json
from .experiment import digest
from .layered_grading import validate_layered_grade

TECHNICAL = {"environment_error", "grader_error", "timeout"}
GRADES = TECHNICAL | {
    "passed",
    "visible_failed",
    "hidden_failed",
    "patch_rejected",
    "no_patch",
    "simulated",
}


def _candidate(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"status", "patch", "internal_success", "duration_seconds"}
        or value["status"] not in {"candidate", "format_error", "no_patch", "simulated"}
        or not isinstance(value["patch"], str)
        or len(value["patch"]) > 256000
        or value["internal_success"] is not None
        and type(value["internal_success"]) is not bool
    ):
        raise ValueError("invalid saved candidate")
    duration = value["duration_seconds"]
    if duration is not None and (
        type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0
    ):
        raise ValueError("invalid candidate duration")
    return value


def _grade(value, output=None):
    if isinstance(value, dict) and value.get("version") == 2:
        return validate_layered_grade(value, output)
    if not isinstance(value, dict) or value.get("status") not in GRADES:
        raise ValueError("invalid saved grade")
    return value


def _slot_grade(value, pack, slot, output, candidate, simulation):
    if pack["identity"].get("version") != 2:
        return _grade(value)
    if not isinstance(value, dict) or value.get("version") != 2 or candidate is None:
        raise ValueError("layered comparison requires a candidate-bound layered grade")
    if not simulation and value.get("status") == "simulated":
        raise ValueError("simulated grade cannot be used in a real run")
    case = next(c for c in pack["identity"]["cases"] if c["id"] == slot["case_id"])
    return validate_layered_grade(
        value, output, candidate_patch=candidate["patch"], frozen_case=case
    )


def _record(slot, candidate, grade, simulation, error=None):
    technical = error is not None or grade is not None and grade["status"] in TECHNICAL
    layered = grade is not None and grade.get("version") == 2
    passed = (
        grade is not None
        and (grade.get("core_passed") is True if layered else grade["status"] == "passed")
        and not technical
    )
    result = {
        **slot,
        "status": "technical_error"
        if technical
        else "simulated"
        if simulation
        else "core_passed"
        if layered and passed
        else "passed"
        if passed
        else "failed",
        "passed": None if simulation else passed,
        "simulation": simulation,
        "candidate": candidate,
        "grade": grade,
        "error_type": error,
    }
    if layered:
        result.pop("passed")
        if candidate is not None and "patch" in candidate:
            result["candidate"] = {key: value for key, value in candidate.items() if key != "patch"}
            result["candidate"]["patch_sha256"] = hashlib.sha256(
                candidate["patch"].encode()
            ).hexdigest()
        result.update(
            core_passed=None if simulation else grade["core_passed"],
            fully_verified=None if simulation else grade["fully_verified"],
        )
    return result


def _events(root, pack, simulation):
    path = checked_path(root / "journal.jsonl")
    raw = path.read_bytes() if path.exists() else b""
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("comparison journal exceeds size limit")
    slots = {s["slot"]: s for s in pack["identity"]["slots"]}
    states = {s: [] for s in slots}
    allowed = {
        None: {"started"},
        "started": {"candidate", "terminal"},
        "candidate": {"grade", "terminal"},
        "grade": {"terminal"},
        "terminal": set(),
    }
    active_index, stopped = 0, False
    for line in raw.splitlines():
        event = json.loads(line)
        if (
            not isinstance(event, dict)
            or set(event) != {"pack", "slot", "event", "data"}
            or event["pack"] != pack["identity_hash"]
            or event["slot"] not in slots
        ):
            raise ValueError("invalid comparison journal identity")
        history = states[event["slot"]]
        last = history[-1]["event"] if history else None
        if event["event"] not in allowed[last]:
            raise ValueError("invalid comparison journal transition")
        index = list(slots).index(event["slot"])
        if stopped or index != active_index:
            raise ValueError("comparison journal violates frozen global order")
        folder = root / f"s{index:04d}"
        if event["event"] in ("candidate", "grade"):
            artifact = folder / (event["event"] + ".json")
            if file_hash(artifact) != event["data"]:
                raise ValueError(f"changed saved {event['event']}")
        if event["event"] == "terminal":
            record = event["data"]
            if (
                not isinstance(record, dict)
                or record.get("slot") != event["slot"]
                or record.get("simulation") is not simulation
                or record
                != _record(
                    slots[event["slot"]],
                    record.get("candidate"),
                    record.get("grade"),
                    simulation,
                    record.get("error_type"),
                )
            ):
                raise ValueError("invalid comparison terminal record")
            saved_candidate = (
                _candidate(read_json(folder / "candidate.json"))
                if (folder / "candidate.json").exists()
                else None
            )
            saved_grade = (
                _slot_grade(
                    read_json(folder / "grade.json"),
                    pack,
                    slots[event["slot"]],
                    folder / "g",
                    saved_candidate,
                    simulation,
                )
                if (folder / "grade.json").exists()
                else None
            )
            if record != _record(
                slots[event["slot"]],
                saved_candidate,
                saved_grade,
                simulation,
                record.get("error_type"),
            ):
                raise ValueError("terminal record contradicts saved stage artifact")
            stopped = record["status"] == "technical_error"
            active_index += 1
        history.append(event)
    return states


def _recover_response(folder):
    responses = list((folder / "responses").glob("response-*.json"))
    if len(responses) != 1:
        return None
    payload = read_json(checked_path(responses[0]))
    if set(payload) != {
        "content",
        "reasoning_content",
        "tool_calls",
        "prompt_tokens",
        "completion_tokens",
        "stop_reason",
    }:
        raise ValueError("invalid recoverable response")
    turn = ModelTurn(
        **{**payload, "tool_calls": tuple(ToolCallRequest(**c) for c in payload["tool_calls"])}
    )
    try:
        patch, status = extract_patch(turn), "candidate"
    except ValueError:
        patch, status = "", "format_error"
    result = {"status": status, "patch": patch, "internal_success": None, "duration_seconds": None}
    write_new(folder / "candidate.json", result)
    return result


def run_slots(pack, output, executor, grader, simulation=False):
    if type(simulation) is not bool or digest(pack["identity"]) != pack["identity_hash"]:
        raise ValueError("invalid comparison run identity")
    output = checked_path(output)
    output.mkdir(parents=True, exist_ok=True)
    identity = {"pack": pack["identity_hash"], "simulation": simulation}
    try:
        write_new(output / "run.json", identity)
    except FileExistsError:
        if read_json(output / "run.json") != identity:
            raise ValueError("comparison run identity changed") from None
    with exclusive(output):
        histories = _events(output, pack, simulation)
        records = []
        for index, slot in enumerate(pack["identity"]["slots"]):
            history = histories[slot["slot"]]
            if history and history[-1]["event"] == "terminal":
                record = history[-1]["data"]
                records.append(record)
                if record["status"] == "technical_error":
                    break
                continue
            folder = checked_path(output / f"s{index:04d}")
            folder.mkdir(exist_ok=True)

            def emit(kind, data=None, *, slot=slot, history=history):
                event = {
                    "pack": pack["identity_hash"],
                    "slot": slot["slot"],
                    "event": kind,
                    "data": data,
                }
                append_event(output / "journal.jsonl", event)
                history.append(event)

            candidate, grade = None, None
            try:
                if not history:
                    emit("started")
                    candidate = _candidate(executor(slot, folder))
                    if not (folder / "candidate.json").exists():
                        write_new(folder / "candidate.json", candidate)
                    elif read_json(folder / "candidate.json") != candidate:
                        raise ValueError("executor candidate contradicts saved artifact")
                elif (folder / "candidate.json").exists():
                    candidate = _candidate(read_json(folder / "candidate.json"))
                elif slot["method"] == "single-shot":
                    candidate = _recover_response(folder)
                if candidate is None:
                    record = _record(slot, None, None, simulation, "interrupted_without_candidate")
                    emit("terminal", record)
                    records.append(record)
                    break
                if history[-1]["event"] == "started":
                    emit("candidate", file_hash(folder / "candidate.json"))
                if (folder / "grade.json").exists():
                    grade = _slot_grade(
                        read_json(folder / "grade.json"),
                        pack,
                        slot,
                        folder / "g",
                        candidate,
                        simulation,
                    )
                else:
                    grading_folder = folder / (
                        "g" if pack["identity"].get("version") == 2 else "g" + uuid4().hex[:8]
                    )
                    grade = _slot_grade(
                        grader(slot, candidate, grading_folder),
                        pack,
                        slot,
                        grading_folder,
                        candidate,
                        simulation,
                    )
                    write_new(folder / "grade.json", grade)
                if history[-1]["event"] == "candidate":
                    emit("grade", file_hash(folder / "grade.json"))
                record = _record(slot, candidate, grade, simulation)
            except Exception as exc:  # noqa: BLE001 - persist controller faults, not interrupts
                # A worker may publish a candidate and then fail (including a
                # supervisor cleanup failure). Preserve that evidence in the
                # technical terminal; never grade it or silently restart it.
                if candidate is None and (folder / "candidate.json").exists():
                    try:
                        candidate = _candidate(read_json(folder / "candidate.json"))
                    except (OSError, ValueError, TypeError, KeyError):
                        # Invalid evidence stays on disk and remains fail-closed
                        # during replay. Do not replace the original fault.
                        pass
                record = _record(slot, candidate, grade, simulation, type(exc).__name__)
            emit("terminal", record)
            records.append(record)
            if record["status"] == "technical_error":
                break
    return records
