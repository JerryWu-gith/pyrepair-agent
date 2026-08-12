from collections import deque
from types import SimpleNamespace

import pytest

from pyrepair.deepseek import DeepSeekClient, DeepSeekError
from pyrepair.models import ModelTurn
from tests.fakes import FakeLLM, model_text_turn


class FakeCompletions:
    def __init__(self) -> None:
        self.responses = deque()
        self.requests = []

    def queue(self, *responses) -> None:
        self.responses.extend(responses)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class FakeOpenAI:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class RetryableApiError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def tool_response(
    *,
    reasoning_content: str,
    call_id: str,
    name: str,
    arguments: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
):
    tool_call = SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    message = SimpleNamespace(
        content="",
        reasoning_content=reasoning_content,
        tool_calls=[tool_call],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def text_response(content: str):
    message = SimpleNamespace(content=content, reasoning_content=None, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=None,
    )


def make_client(monkeypatch, fake_openai, **kwargs):
    captured = {}

    def factory(**factory_kwargs):
        captured.update(factory_kwargs)
        return fake_openai

    monkeypatch.setattr("pyrepair.deepseek.OpenAI", factory)
    client = DeepSeekClient(
        api_key=kwargs.get("api_key", "sk-test-key"),
        model=kwargs.get("model", "deepseek-v4-flash"),
        base_url="https://api.deepseek.com",
        timeout=30,
        max_retries=kwargs.get("max_retries", 2),
        sleep=kwargs.get("sleep", lambda seconds: None),
    )
    return client, captured


def test_complete_maps_tool_call_reasoning_and_usage(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(
        tool_response(
            reasoning_content="inspect file",
            call_id="call-1",
            name="read_file",
            arguments='{"path":"app.py"}',
            prompt_tokens=12,
            completion_tokens=7,
        )
    )
    client, _ = make_client(monkeypatch, fake)

    turn = client.complete([{"role": "user", "content": "fix"}], [])

    assert turn.reasoning_content == "inspect file"
    assert turn.tool_calls[0].id == "call-1"
    assert turn.tool_calls[0].name == "read_file"
    assert turn.tool_calls[0].arguments == {"path": "app.py"}
    assert turn.prompt_tokens == 12
    assert turn.completion_tokens == 7


def test_complete_enables_thinking_and_disables_sdk_retries(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(text_response("done"))
    client, factory_kwargs = make_client(monkeypatch, fake, model="deepseek-v4-pro")

    client.complete([{"role": "user", "content": "fix"}], [{"type": "function"}])

    request = fake.completions.requests[0]
    assert request["model"] == "deepseek-v4-pro"
    assert request["reasoning_effort"] == "high"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request["tools"] == [{"type": "function"}]
    assert "temperature" not in request
    assert factory_kwargs["max_retries"] == 0


def test_complete_omits_tools_when_review_has_none(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(text_response("done"))
    client, _ = make_client(monkeypatch, fake)

    client.complete([{"role": "user", "content": "review"}], [])

    assert "tools" not in fake.completions.requests[0]


def test_complete_rejects_invalid_tool_arguments_json(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(
        tool_response(
            reasoning_content="inspect",
            call_id="call-1",
            name="read_file",
            arguments="not-json",
        )
    )
    client, _ = make_client(monkeypatch, fake)

    with pytest.raises(DeepSeekError, match="invalid_tool_arguments"):
        client.complete([], [])


def test_complete_retries_429_twice_with_bounded_backoff(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(RetryableApiError(429), RetryableApiError(429), text_response("done"))
    sleeps = []
    client, _ = make_client(monkeypatch, fake, sleep=sleeps.append)

    result = client.complete([], [])

    assert result.content == "done"
    assert len(fake.completions.requests) == 3
    assert sleeps == [1.0, 2.0]


def test_complete_redacts_api_key_from_terminal_error(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(RuntimeError("request failed with sk-secret-value"))
    client, _ = make_client(monkeypatch, fake, api_key="sk-secret-value")

    with pytest.raises(DeepSeekError) as captured:
        client.complete([], [])

    assert "sk-secret-value" not in str(captured.value)
    assert "[REDACTED]" in str(captured.value)
    assert len(fake.completions.requests) == 1


def test_client_rejects_unknown_model(monkeypatch):
    with pytest.raises(DeepSeekError, match="unsupported_model"):
        make_client(monkeypatch, FakeOpenAI(), model="deepseek-chat")


def test_fake_llm_records_deep_copied_requests_and_exhausts():
    turn = model_text_turn("done")
    fake = FakeLLM([turn])
    messages = [{"role": "user", "content": "fix"}]

    assert fake.complete(messages, []) == turn
    messages[0]["content"] = "changed"
    assert fake.requests[0][0][0]["content"] == "fix"
    with pytest.raises(AssertionError, match="没有剩余响应"):
        fake.complete([], [])


def test_text_response_maps_to_model_turn(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(text_response("done"))
    client, _ = make_client(monkeypatch, fake)

    result = client.complete([], [])

    assert result == ModelTurn("done", None, (), stop_reason="stop")
