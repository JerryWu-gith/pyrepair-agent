from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from openai import OpenAI

from .config import ALLOWED_MODELS
from .models import ModelTurn, ToolCallRequest


class DeepSeekError(RuntimeError):
    """Raised when a DeepSeek request cannot be completed safely."""


class ModelClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn: ...


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 90.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if model not in ALLOWED_MODELS:
            raise DeepSeekError(f"unsupported_model:{model}")
        if max_retries < 0:
            raise DeepSeekError("max_retries_must_be_non_negative")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.sleep = sleep
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,  #关掉 SDK 自带重试，自己实现重试（更可控）
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        if tools:
            request["tools"] = tools

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**request)
                return _to_model_turn(response)
            except DeepSeekError:
                raise
            except Exception as exc:
                if _is_retryable(exc) and attempt < self.max_retries:
                    self.sleep(float(2**attempt))  #指数退避 → 等 1 秒、2 秒
                    continue
                safe_message = str(exc).replace(self.api_key, "[REDACTED]")  # 错误消息里把 api_key 替换掉，API key 不能进日志/异常
                raise DeepSeekError(f"deepseek_request_failed:{safe_message}") from exc
        raise DeepSeekError("deepseek_request_failed:retry_loop_exhausted")


def _to_model_turn(response: Any) -> ModelTurn:   # 把 LLM 返回的原始对象翻译成内部的 ModelTurn
    choice = response.choices[0]
    message = choice.message
    calls: list[ToolCallRequest] = []
    for call in message.tool_calls or ():
        try:
            arguments = json.loads(call.function.arguments)
        except (json.JSONDecodeError, TypeError) as exc:
            raise DeepSeekError("invalid_tool_arguments") from exc
        if not isinstance(arguments, dict):
            raise DeepSeekError("invalid_tool_arguments")
        calls.append(
            ToolCallRequest(
                id=call.id,
                name=call.function.name,
                arguments=arguments,
            )
        )

    usage = response.usage
    return ModelTurn(
        content=message.content or "",
        reasoning_content=getattr(message, "reasoning_content", None),
        tool_calls=tuple(calls),
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        stop_reason=choice.finish_reason,
    )


def _is_retryable(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
        return True
    name = type(exc).__name__.lower()
    return "timeout" in name or "connection" in name
