from __future__ import annotations

import copy
from collections import deque
from typing import Any

from pyrepair.models import ModelTurn, ToolCallRequest


class FakeLLM:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = deque(turns)
        self.requests: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        if not self.turns:
            raise AssertionError("FakeLLM 没有剩余响应")
        return self.turns.popleft()


def model_text_turn(content: str, reasoning: str | None = None) -> ModelTurn:
    return ModelTurn(content, reasoning, ())


def model_tool_turn(
    call_id: str,
    name: str,
    arguments: dict[str, Any],
    reasoning: str | None = None,
) -> ModelTurn:
    return ModelTurn("", reasoning, (ToolCallRequest(call_id, name, arguments),))
