from __future__ import annotations

import json
from typing import Any

from .context_builder import ContextBundle, empty_context_bundle
from .deepseek import ModelClient
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
        previous_evidence: tuple[str, ...] = (),
        *,
        context: ContextBundle | None = None,
    ) -> AgentRun:
        messages = _initial_messages(
            report,
            previous_evidence,
            context or empty_context_bundle(),
        )  # 初始消息
        turns: list[ModelTurn] = []   # 记录所有轮次
        calls_used = 0

        while calls_used < self.max_tool_calls:
            turn = self.client.complete(messages, self.registry.schemas())
            turns.append(turn)
            messages.append(_assistant_message(turn))
            if not turn.tool_calls:  # LLM 不用工具了
                return AgentRun(completed=True, turns=tuple(turns))

            for call in turn.tool_calls:  # 逐个执行工具
                if calls_used >= self.max_tool_calls:
                    return AgentRun(False, tuple(turns), "max_tool_calls_exceeded")
                calls_used += 1
                result = self.registry.execute(call.name, call.arguments)  # 执行
                messages.append(   # 工具结果放回对话
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result.to_json(),
                    }
                )

        return AgentRun(False, tuple(turns), "max_tool_calls_exceeded")


def _initial_messages(
    report: FailureReport,
    previous_evidence: tuple[str, ...],
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
