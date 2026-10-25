"""Single-use fixed Review A/B execution; never automatically retries or resumes."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pyrepair.config import ALLOWED_MODELS
from pyrepair.review_agent import _parse_review

from .experiment import digest
from .review_fixtures import PROTOCOL, load_prepared, messages_for_input, save_json


def schedule(candidate_ids: list[str], repeats: int) -> list[dict]:
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise ValueError("repeats must be an integer in 1..100")
    if not candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("empty or duplicate candidates")
    rows = []
    for i, candidate in enumerate(candidate_ids):
        for repeat in range(repeats):
            for arm in "AB" if (i + repeat) % 2 == 0 else "BA":
                rows.append(
                    {
                        "id": f"{len(rows) + 1:04d}",
                        "candidate": candidate,
                        "repeat": repeat + 1,
                        "arm": arm,
                    }
                )
    return rows


def _client_factory(*, model: str, max_retries: int):
    from pyrepair.deepseek import DeepSeekClient

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY is required; never pass it on the command line")
    return DeepSeekClient(
        api_key=key,
        model=model,
        base_url="https://api.deepseek.com",
        timeout=90,
        max_retries=max_retries,
    )


def _redact(text: str) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    return text.replace(key, "[REDACTED]") if key else text


def _valid_parsed(content: str, parsed) -> bool:
    # Compare raw fields to the production parser's result, not to its reserved
    # fallback text. A legitimate semantic rejection may use that same wording.
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("approved") is parsed.approved
        and data.get("risk") == parsed.risk
        and data.get("findings") == list(parsed.findings)
        and data.get("reason") == parsed.reason
    )


def run_review(
    prepared: Path,
    output: Path,
    *,
    live: bool,
    model: str,
    repeats: int,
    request_cap: int,
    client_factory=None,
) -> Path:
    if live is not True:
        raise ValueError("explicit --live authorization required")
    if model not in ALLOWED_MODELS:
        raise ValueError("model is not allowed")
    data = load_prepared(prepared)
    rows = schedule(list(data["inputs"]), repeats)
    if type(request_cap) is not int or request_cap < len(rows):
        raise ValueError(f"request cap insufficient: {len(rows)} planned")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "protocol": PROTOCOL,
        "prepared_digest": digest(data),
        "runtime": data["runtime"],
        "model": model,
        "repeats": repeats,
        "request_cap": request_cap,
        "schedule": rows,
        "inputs": data["inputs"],
        "labels": data["labels"],
        "provenance": data["provenance"],
        "settings": {
            "max_retries": 0,
            "error_policy": "stop_after_first_api_or_parse_error",
            "timeout_seconds": 90,
            "thinking": "enabled",
            "reasoning_effort": "high",
            "randomness": "provider default; no seed supplied",
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    if "dataset" in data:
        manifest["dataset"] = data["dataset"]
    manifest["request_hashes"] = {
        row["id"]: digest(
            {
                "id": row["id"],
                "messages": messages_for_input(
                    data["inputs"][row["candidate"]], with_contract=row["arm"] == "B"
                ),
                "tools": [],
            }
        )
        for row in rows
    }
    save_json(output / "manifest.json", {"payload": manifest, "digest": digest(manifest)})
    client = (client_factory or _client_factory)(model=model, max_retries=0)
    for row in rows:
        directory = output / "requests" / row["id"]
        messages = messages_for_input(
            data["inputs"][row["candidate"]], with_contract=row["arm"] == "B"
        )
        request = {"id": row["id"], "messages": messages, "tools": []}
        request_hash = digest(request)
        # Neither write is inside the API exception handler: disk errors must
        # stop the loop, not become another model error followed by more calls.
        save_json(directory / "request.json", request)
        save_json(
            directory / "started.json",
            {"id": row["id"], "request_hash": request_hash, "at": datetime.now(UTC).isoformat()},
        )
        start = time.monotonic()
        result = {
            "id": row["id"],
            "request_hash": request_hash,
            "usage_known": False,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        try:
            turn = client.complete(messages, [])
            parsed = _parse_review(
                turn.content,
                prompt_tokens=turn.prompt_tokens,
                completion_tokens=turn.completion_tokens,
            )
            known = (
                type(turn.prompt_tokens) is int
                and type(turn.completion_tokens) is int
                and min(turn.prompt_tokens, turn.completion_tokens) >= 0
                and turn.prompt_tokens + turn.completion_tokens > 0
            )
            result.update(
                status="valid" if _valid_parsed(turn.content, parsed) else "parse_error",
                content=_redact(turn.content),
                parsed=json.loads(_redact(json.dumps(asdict(parsed)))),
                usage_known=known,
                prompt_tokens=turn.prompt_tokens,
                completion_tokens=turn.completion_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - record one model-boundary failure; never retry
            result.update(
                status="api_error",
                error={"type": type(exc).__name__, "message": _redact(str(exc))[:2000]},
            )
        result["seconds"] = time.monotonic() - start
        result["record_digest"] = digest(result)
        save_json(directory / "result.json", result)
        if result["status"] != "valid":
            break  # Preserve the error; later planned requests remain unstarted.
    return output
