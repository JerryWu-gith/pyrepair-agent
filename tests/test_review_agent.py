import json

import pytest

from pyrepair.models import FailureReport, FileChange, PatchSnapshot
from pyrepair.review_agent import ReviewAgent
from tests.fakes import FakeLLM, model_text_turn


def failure_report() -> FailureReport:
    return FailureReport(
        node_id="tests/test_app.py::test_add",
        exception_type="AssertionError",
        traceback="E assert -1 == 5",
        summary="assert -1 == 5",
        related_files=("app.py",),
    )


def patch_snapshot() -> PatchSnapshot:
    return PatchSnapshot(
        (
            FileChange(
                path="app.py",
                old_text="return a - b\n",
                new_text="return a + b\n",
                diff="--- a/app.py\n+++ b/app.py\n-return a - b\n+return a + b\n",
                added_lines=1,
                deleted_lines=1,
            ),
        )
    )


def test_review_approves_low_risk_root_cause_fix_without_tools():
    llm = FakeLLM(
        [
            model_text_turn(
                json.dumps(
                    {
                        "approved": True,
                        "risk": "low",
                        "findings": [],
                        "reason": "修复了加法实现中的运算符错误",
                    },
                    ensure_ascii=False,
                )
            )
        ]
    )

    result = ReviewAgent(llm).review(failure_report(), patch_snapshot())

    assert result.approved is True
    assert result.risk == "low"
    assert result.findings == ()
    assert llm.requests[0][1] == []


def test_review_preserves_semantic_rejection():
    llm = FakeLLM(
        [
            model_text_turn(
                json.dumps(
                    {
                        "approved": False,
                        "risk": "high",
                        "findings": ["修改没有处理根因", "可能破坏减法调用"],
                        "reason": "补丁副作用过大",
                    },
                    ensure_ascii=False,
                )
            )
        ]
    )

    result = ReviewAgent(llm).review(failure_report(), patch_snapshot())

    assert result.approved is False
    assert result.findings == ("修改没有处理根因", "可能破坏减法调用")


@pytest.mark.parametrize(
    "content",
    [
        "looks fine",
        '{"approved":"yes","risk":"low","findings":[],"reason":"ok"}',
        '{"approved":true,"risk":"unknown","findings":[],"reason":"ok"}',
        '{"approved":true,"risk":"low","findings":"none","reason":"ok"}',
        '{"approved":true,"risk":"low","findings":[],"reason":""}',
    ],
)
def test_review_rejects_invalid_json_or_fields(content):
    result = ReviewAgent(FakeLLM([model_text_turn(content)])).review(
        failure_report(), patch_snapshot()
    )

    assert result.approved is False
    assert result.risk == "high"
    assert result.findings == ("invalid_review_json",)


def test_review_cannot_modify_snapshot_and_each_call_has_fresh_context():
    snapshot = patch_snapshot()
    original = snapshot.text
    response = model_text_turn(
        '{"approved":true,"risk":"low","findings":[],"reason":"ok"}'
    )
    llm = FakeLLM([response, response])
    reviewer = ReviewAgent(llm)

    reviewer.review(failure_report(), snapshot)
    reviewer.review(failure_report(), snapshot)

    assert snapshot.text == original
    assert len(llm.requests[0][0]) == 2
    assert len(llm.requests[1][0]) == 2
    assert llm.requests[0][0][0]["role"] == "system"
    assert llm.requests[1][0][0]["role"] == "system"
