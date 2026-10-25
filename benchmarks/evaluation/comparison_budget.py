"""Conservative durable model-call reservations, not a currency spending meter."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from pyrepair.models import ModelTurn

from .cases import safe_relative
from .container_protocol import is_link, read_json

ROLES = ("single-shot", "repair", "review")


class QuotaError(RuntimeError):
    pass


def checked_path(path: Path) -> Path:
    path = Path(path).absolute()
    if any(is_link(p) for p in (path, *path.parents)):
        raise ValueError("linked comparison path")
    return path


def write_new(path: Path, value) -> None:
    path = checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("comparison artifact exceeds size limit")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def exclusive(root: Path):
    lock = checked_path(root / "writer.lock")
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise QuotaError("writer lock exists; no automatic removal or retry") from exc
    try:
        with stream:
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        lock.unlink()


def append_event(path, event):
    checked_path(path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _calls(root):
    config = read_json(checked_path(root / "budget.json"))
    if set(config) != {"version", "limit"} or config["version"] != 1:
        raise ValueError("invalid quota identity")
    limit = config["limit"]
    if type(limit) is not int or limit < 1:
        raise ValueError("invalid quota limit")
    journal = checked_path(root / "calls.jsonl")
    calls = {}
    raw = journal.read_bytes() if journal.exists() else b""
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("quota journal exceeds size limit")
    for line in raw.splitlines():
        event = json.loads(line)
        if not isinstance(event, dict) or type(event.get("call_id")) is not int:
            raise ValueError("invalid quota event")
        number, kind = event["call_id"], event.get("event")
        if kind == "reserved":
            if (
                set(event) != {"event", "call_id", "slot", "role", "slot_limit"}
                or number != len(calls) + 1
                or number > limit
                or event["role"] not in ROLES
                or not isinstance(event["slot"], str)
                or type(event["slot_limit"]) is not int
                or event["slot_limit"] < 1
            ):
                raise ValueError("invalid quota reservation")
            previous = [c for c in calls.values() if c["slot"] == event["slot"]]
            if len(previous) >= event["slot_limit"] or any(
                c["slot_limit"] != event["slot_limit"] for c in previous
            ):
                raise ValueError("invalid slot quota")
            calls[number] = event
        elif kind in ("response", "error"):
            expected = {"event", "call_id"} | (
                {"prompt_tokens", "completion_tokens"} if kind == "response" else {"error_type"}
            )
            if set(event) != expected or number not in calls or "result" in calls[number]:
                raise ValueError("invalid quota response transition")
            if kind == "error" and not isinstance(event["error_type"], str):
                raise ValueError("invalid quota error")
            calls[number]["result"] = event
        else:
            raise ValueError("invalid quota event kind")
    return config, calls


class CallBudget:
    def __init__(self, root: Path, limit: int):
        if type(limit) is not int or not 1 <= limit <= 100000:
            raise ValueError("quota limit must be an integer in 1..100000")
        self.root = checked_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        identity = {"version": 1, "limit": limit}
        try:
            write_new(self.root / "budget.json", identity)
        except FileExistsError:
            if read_json(self.root / "budget.json") != identity:
                raise ValueError("quota identity changed") from None
        _calls(self.root)

    def reserve(self, slot, role, slot_limit):
        safe_relative(slot)
        if (
            "/" in slot
            or role not in ROLES
            or type(slot_limit) is not int
            or not 0 < slot_limit <= 36
        ):
            raise ValueError("invalid model slot/role/limit")
        with exclusive(self.root):
            config, calls = _calls(self.root)
            prior = [c for c in calls.values() if c["slot"] == slot]
            if any(c["slot_limit"] != slot_limit for c in prior):
                raise ValueError("slot quota identity changed")
            if len(calls) >= config["limit"] or len(prior) >= slot_limit:
                raise QuotaError("model call quota exhausted; no request made")
            number = len(calls) + 1
            append_event(
                self.root / "calls.jsonl",
                {
                    "event": "reserved",
                    "call_id": number,
                    "slot": slot,
                    "role": role,
                    "slot_limit": slot_limit,
                },
            )
        return number

    def finish(self, event):
        with exclusive(self.root):
            _, calls = _calls(self.root)
            number = event["call_id"]
            if number not in calls or "result" in calls[number]:
                raise ValueError("unknown or completed model reservation")
            append_event(self.root / "calls.jsonl", event)


class GuardedClient:
    def __init__(self, client, budget, slot, role, slot_limit, response_dir):
        self.client, self.budget = client, budget
        self.slot, self.role, self.slot_limit = slot, role, slot_limit
        self.response_dir = checked_path(response_dir)
        if hasattr(client, "max_retries"):
            client.max_retries = 0
        sdk = getattr(client, "client", None)
        if sdk is not None and getattr(sdk, "max_retries", 0) != 0:
            raise ValueError("SDK retries must be disabled in comparison")

    def complete(self, messages, tools):
        number = self.budget.reserve(self.slot, self.role, self.slot_limit)
        try:
            turn = self.client.complete(messages, tools)
            if not isinstance(turn, ModelTurn):
                raise TypeError("invalid ModelTurn response")
            payload = asdict(turn)
            secret = getattr(self.client, "api_key", "")
            if isinstance(secret, str) and secret:
                payload = json.loads(
                    json.dumps(payload, ensure_ascii=False).replace(secret, "[REDACTED]")
                )
            write_new(self.response_dir / f"response-{number:06d}.json", payload)
        except BaseException as exc:
            self.budget.finish(
                {"event": "error", "call_id": number, "error_type": type(exc).__name__}
            )
            raise
        values = {}
        for name in ("prompt_tokens", "completion_tokens"):
            value = getattr(turn, name)
            values[name] = value if type(value) is int and value >= 0 else None
        self.budget.finish({"event": "response", "call_id": number, **values})
        return turn


def read_usage(root: Path) -> dict:
    _, calls = _calls(checked_path(root))
    roles, responses = {}, 0
    for role in ROLES:
        chosen = [c for c in calls.values() if c["role"] == role]
        known, prompt, completion = True, 0, 0
        for call in chosen:
            result = call.get("result", {})
            a, b = result.get("prompt_tokens"), result.get("completion_tokens")
            if result.get("event") == "response":
                responses += 1
            if type(a) is int and type(b) is int and a >= 0 and b >= 0 and a + b > 0:
                prompt += a
                completion += b
            else:
                known = False
        roles[role] = {
            "calls": len(chosen),
            "prompt_tokens": prompt if known else None,
            "completion_tokens": completion if known else None,
            "known_prompt_tokens": prompt,
            "known_completion_tokens": completion,
        }
    return {
        "reserved_calls": len(calls),
        "responses": responses,
        "roles": roles,
        "usage_known": bool(calls) and all(v["prompt_tokens"] is not None for v in roles.values()),
        "transport_requests": None,
        "semantics": "durable ModelClient reservations; no currency cap",
    }
