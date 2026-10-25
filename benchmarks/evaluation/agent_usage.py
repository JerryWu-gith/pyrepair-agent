"""Immediate response accounting, separate from delayed coordinator trace writes.

Counts ModelClient invocations, not HTTP retries inside the provider client.
Never serialize prompts, content, reasoning, keys or arbitrary exception text.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .container_protocol import is_link


class ResponseLedger:
    def __init__(self, path: Path):
        self.path = Path(path).absolute()
        if any(is_link(p) for p in (self.path, *self.path.parents)):
            raise ValueError("linked response ledger")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.open("x", encoding="utf-8").close()
        self.sequence = 0

    def append(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"version": 1, **event}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


class RecordingModelClient:
    def __init__(self, client, role: str, ledger: ResponseLedger):
        if role not in ("repair", "review"):
            raise ValueError("unknown model role")
        self.client, self.role, self.ledger = client, role, ledger

    def complete(self, messages, tools):
        self.ledger.sequence += 1
        identity = {"call_id": self.ledger.sequence, "role": self.role}
        self.ledger.append({**identity, "event": "started"})
        try:
            turn = self.client.complete(messages, tools)
        except BaseException as exc:
            self.ledger.append({**identity, "event": "error", "error_type": type(exc).__name__})
            raise
        self.ledger.append(
            {
                **identity,
                "event": "response",
                **{
                    name: value if type(value) is int and value >= 0 else None
                    for name in ("prompt_tokens", "completion_tokens")
                    for value in (getattr(turn, name, None),)
                },
            }
        )
        return turn


def read_response_usage(path: Path) -> dict:
    if is_link(path):
        raise ValueError("linked response ledger")
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("response ledger size exceeded")
    usage = {role: {"prompt_tokens": 0, "completion_tokens": 0} for role in ("repair", "review")}
    calls = {role: 0 for role in usage}
    started, finished = {}, set()
    known = True
    for line in raw.splitlines():
        event = json.loads(line)
        if (
            not isinstance(event, dict)
            or type(event.get("version")) is not int
            or event["version"] != 1
            or type(event.get("call_id")) is not int
            or event.get("role") not in ("repair", "review")
        ):
            raise ValueError("invalid response ledger identity")
        call_id, role, kind = event["call_id"], event["role"], event.get("event")
        fields = {"version", "call_id", "role", "event"}
        if kind == "started":
            if set(event) != fields or call_id != len(started) + 1:
                raise ValueError("invalid started model call")
            started[call_id] = role
            calls[role] += 1
            continue
        if call_id not in started or started[call_id] != role or call_id in finished:
            raise ValueError("unknown or duplicate model response")
        finished.add(call_id)
        if kind == "error":
            if set(event) != fields | {"error_type"} or not isinstance(event["error_type"], str):
                raise ValueError("invalid model error evidence")
            known = False
        elif kind == "response":
            if set(event) != fields | {"prompt_tokens", "completion_tokens"}:
                raise ValueError("invalid model usage fields")
            for name in ("prompt_tokens", "completion_tokens"):
                value = event[name]
                if type(value) is int and value >= 0:
                    usage[role][name] += value
                else:
                    known = False
            if event["prompt_tokens"] == event["completion_tokens"] == 0:
                known = False
        else:
            raise ValueError("unknown response ledger event")
    return {
        "usage": usage,
        "model_calls": calls,
        "usage_known": known and len(started) == len(finished),
        "usage_source": "response_ledger",
        "transport_requests": None,
        "model_call_semantics": "ModelClient.complete invocations; transport retries not counted",
    }
