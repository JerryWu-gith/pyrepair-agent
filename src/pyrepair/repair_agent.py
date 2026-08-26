from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .agent_state import AgentRuntimeState
from .context_builder import ContextBundle, empty_context_bundle
from .deepseek import ModelClient
from .loop_guard import CompletionPolicy, GuardDecision, LoopGuard
from .models import AgentRun, FailureReport, ModelTurn
from .tools import ToolRegistry

SYSTEM_PROMPT = """你是 PyRepair 的修复角色。你的目标是找到 pytest 失败的根因并生成最小源码修改。
只能通过已提供的工具读取、搜索、精确替换、查看 Diff 和运行已识别的目标测试。
禁止修改测试、环境文件、CI、依赖锁文件或密钥；禁止 skip、xfail、删除断言或弱化断言。
先收集证据再修改；修改后必须查看 Diff 并运行目标测试。工具返回错误时应调整方案，不能伪造成功。
最终回复只总结根因和已执行操作，最终成功由外部规则与 pytest 判定。"""


class RepairAgent:
    def __init__(
        self,
        client: ModelClient,
        registry: ToolRegistry,
        max_tool_calls: int = 8,
    ) -> None:
        self.client = client
        self.registry = registry
        self.max_tool_calls = max_tool_calls

    def run(
        self,
        report: FailureReport,
        previous_evidence: tuple[Any, ...] = (),
        *,
        context: ContextBundle | None = None,
        attempt: int = 1,
        max_attempts: int = 3,
        status_enabled: bool = True,
    ) -> AgentRun:
        messages = _initial_messages(
            report,
            previous_evidence,
            context or empty_context_bundle(),
        )
        turns: list[ModelTurn] = []
        runtime = AgentRuntimeState(attempt, max_attempts, self.max_tool_calls)
        guard = LoopGuard()
        completion = CompletionPolicy()
        guard_events: list[str] = []
        max_model_turns = self.max_tool_calls + 3

        while len(turns) < max_model_turns:
            status_message = _status_message(runtime) if status_enabled else None
            if status_message is not None:
                messages.append(status_message)
            try:
                turn = self.client.complete(messages, self.registry.schemas())
            finally:
                if status_message is not None:
                    messages.pop()

            turns.append(turn)
            messages.append(_assistant_message(turn))
            if not turn.tool_calls:
                decision = completion.evaluate(
                    runtime.snapshot(),
                    bool(runtime.changed_files),
                    self.max_tool_calls - runtime.tool_calls_used,
                )
                if decision.complete:
                    return _agent_run(True, turns, runtime, guard_events)
                if decision.continue_loop:
                    messages.append(_guidance_message(decision.guidance or "Continue."))
                    continue
                return _agent_run(
                    False,
                    turns,
                    runtime,
                    guard_events,
                    decision.reason,
                )

            guidance: list[str] = []
            for call in turn.tool_calls:
                if runtime.tool_calls_used >= self.max_tool_calls:
                    return _agent_run(
                        False,
                        turns,
                        runtime,
                        guard_events,
                        "max_tool_calls_exceeded",
                    )

                before = guard.before_tool(call.name, call.arguments, runtime)
                if before.blocked:
                    return _guarded_run(before, turns, runtime, guard_events)
                if before.guidance:
                    guidance.append(before.guidance)

                result = self.registry.execute(call.name, call.arguments)
                progress = runtime.record_tool(call.name, call.arguments, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result.to_json(),
                    }
                )

                after = guard.after_tool(progress, runtime)
                if after.blocked:
                    return _guarded_run(after, turns, runtime, guard_events)
                if after.guidance:
                    guidance.append(after.guidance)

            if guidance:
                messages.append(_guidance_message(" ".join(dict.fromkeys(guidance))))

        return _agent_run(
            False,
            turns,
            runtime,
            guard_events,
            "max_model_turns_exceeded",
        )


def _initial_messages(
    report: FailureReport,
    previous_evidence: tuple[Any, ...],
    context: ContextBundle,
) -> list[dict[str, Any]]:
    payload = {
        "failure": {
            "node_id": report.node_id,
            "exception_type": report.exception_type,
            "traceback": report.traceback,
            "summary": report.summary,
            "related_files": list(report.related_files),
        },
        "context": {
            "repo_overview": context.repo_overview,
            "snippets": [
                {
                    "path": item.path,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "symbol": item.symbol,
                    "reason": item.reason,
                    "score": item.score,
                    "trusted": False,
                    "content": item.content,
                }
                for item in context.snippets
            ],
            "related_files": list(context.related_files),
            "truncated": context.truncated,
        },
        "previous_evidence": list(previous_evidence),
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _assistant_message(turn: ModelTurn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.content,
        "reasoning_content": turn.reasoning_content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in turn.tool_calls
        ],
    }


def _status_message(runtime: AgentRuntimeState) -> dict[str, str]:
    status = json.dumps(asdict(runtime.snapshot()), ensure_ascii=False, sort_keys=True)
    return {"role": "user", "content": f"<agent_status>{status}</agent_status>"}


def _guidance_message(guidance: str) -> dict[str, str]:
    return {"role": "user", "content": f"<harness_guidance>{guidance}</harness_guidance>"}


def _guarded_run(
    decision: GuardDecision,
    turns: list[ModelTurn],
    runtime: AgentRuntimeState,
    guard_events: list[str],
) -> AgentRun:
    reason = decision.reason or "loop_guard_blocked"
    guard_events.append(reason)
    return _agent_run(False, turns, runtime, guard_events, reason)


def _agent_run(
    completed: bool,
    turns: list[ModelTurn],
    runtime: AgentRuntimeState,
    guard_events: list[str],
    failure_reason: str | None = None,
) -> AgentRun:
    return AgentRun(
        completed=completed,
        turns=tuple(turns),
        failure_reason=failure_reason,
        final_status=runtime.snapshot(),
        guard_events=tuple(guard_events),
    )

