from __future__ import annotations

import json
from typing import Any, Literal, cast

from .deepseek import ModelClient
from .models import FailureReport, PatchSnapshot, ReviewResult

REVIEW_SYSTEM_PROMPT = """你是 PyRepair 的独立只读代码审查角色。
你只能根据原始 pytest 故障和候选 Diff 判断：修改是否针对根因、是否有明显副作用、是否是最小必要修改。
不要提出或执行工具调用，不要修改代码。只返回一个 JSON 对象，不要使用 Markdown 代码块。
JSON 必须包含 approved(boolean)、risk(low|medium|high)、findings(string[])、reason(non-empty string)。"""


class ReviewAgent:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def review(
        self,
        report: FailureReport,
        snapshot: PatchSnapshot,
    ) -> ReviewResult:
        messages = _review_messages(report, snapshot)
        turn = self.client.complete(messages, [])
        return _parse_review(turn.content)


def _review_messages(
    report: FailureReport,
    snapshot: PatchSnapshot,
) -> list[dict[str, Any]]:
    payload = {
        "failure": {
            "node_id": report.node_id,
            "exception_type": report.exception_type,
            "traceback": report.traceback,
            "summary": report.summary,
        },
        "patch": {
            "diff": snapshot.text,
            "changed_files": [change.path for change in snapshot.changes],
            "added_lines": sum(change.added_lines for change in snapshot.changes),
            "deleted_lines": sum(change.deleted_lines for change in snapshot.changes),
        },
    }
    return [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _parse_review(content: str) -> ReviewResult:
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            raise TypeError("review must be an object")
        approved = data.get("approved")
        risk = data.get("risk")
        findings = data.get("findings")
        reason = data.get("reason")
        valid = (
            isinstance(approved, bool)
            and risk in {"low", "medium", "high"}
            and isinstance(findings, list)
            and all(isinstance(item, str) for item in findings)
            and isinstance(reason, str)
            and bool(reason.strip())
        )
        if not valid:
            raise ValueError("invalid review fields")
        return ReviewResult(
            approved=approved,
            risk=cast(Literal["low", "medium", "high"], risk),
            findings=tuple(findings),
            reason=reason,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return ReviewResult(
            approved=False,
            risk="high",
            findings=("invalid_review_json",),
            reason="Review 输出无法安全解析",
        )
