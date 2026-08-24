# PyRepair Phase 3 Agent State and Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 由 Python Harness 维护 Agent 实时状态、阻止重复与无进展循环，并把每次候选补丁的真实门禁与测试证据结构化传给下一轮。

**Architecture:** `AgentRuntimeState` 从工具调用和结果计算不可变 `AgentStatus`；`LoopGuard` 与 `CompletionPolicy` 只做确定性判断。`FeedbackBuilder` 从 Snapshot、Policy、Review、Verifier 结果构建 `AttemptFeedback`，Coordinator 每轮仍从 baseline 恢复。

**Tech Stack:** Python 3.11+、dataclass、JSON fingerprint、pytest、Ruff。

## Global Constraints

- 先完成 Phase 1–2；本计划消费稳定 JSON `ToolResult` 和固定 `ContextBundle`。
- 每次源码成功修改后，`diff_inspected` 与 `target_test_run` 必须重置为 false。
- 完全相同调用第二次允许并警告，第三次连续调用前阻止；连续 3 次无进展提示，连续 4 次停止。
- 同一调用得到相同错误两次后不得再次原样调用。
- 有源码修改时，RepairAgent 结束必须满足“看过修改后 Diff + 跑过修改后目标测试”。
- 状态由 Python 轨迹生成，不调用 LLM 总结；Review findings 仅作为不可信审查证据。
- Feedback 上限：Diff 6000 字符、测试输出 4000 字符、Review findings 5 条。
- 最多 3 个修复 attempt；每个 attempt 的 working 副本从 baseline 恢复，失败补丁不叠加。

---

### Task 1: AgentStatus 与 AgentRuntimeState

**Files:**
- Modify: `src/pyrepair/models.py`
- Create: `src/pyrepair/agent_state.py`
- Create: `tests/test_agent_state.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Produces: `AgentStatus` 与 `AgentRun.final_status/guard_events`。
- Produces: `AgentRuntimeState(attempt, max_attempts, max_tool_calls)`。
- Produces: `record_tool(name, arguments, result) -> ToolProgress`、`snapshot() -> AgentStatus` 与 `call_fingerprint(name, arguments) -> str`。

- [ ] **Step 1: 写状态变迁失败测试**

```python
def ok_result(data: dict) -> ToolResult:
    return ToolResult(True, data)


def test_successful_edit_resets_post_edit_verification():
    state = AgentRuntimeState(1, 3, 8)
    state.record_tool("show_diff", {}, ok_result({"diff": ""}))
    state.record_tool("run_target_test", {}, ok_result({"passed": False}))
    state.record_tool("replace_text", {"path": "app.py"},
                      ok_result({"path": "app.py", "replacements": 1}))
    status = state.snapshot()
    assert status.changed_files == ("app.py",)
    assert status.diff_inspected is False
    assert status.target_test_run is False


def test_new_read_is_progress_but_identical_result_is_not():
    state = AgentRuntimeState(1, 3, 8)
    first = state.record_tool(
        "read_file", {"path": "app.py", "start_line": 1, "end_line": 10},
        ok_result({"path": "app.py", "content": "x"})
    )
    second = state.record_tool(
        "read_file", {"end_line": 10, "path": "app.py", "start_line": 1},
        ok_result({"path": "app.py", "content": "x"})
    )
    assert first.progressed is True
    assert second.progressed is False
    assert state.snapshot().no_progress_steps == 1
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p3-t1 tests/test_agent_state.py tests/test_models.py -v`

Expected: FAIL，状态类型尚不存在。

- [ ] **Step 3: 添加不可变公开状态和运行时状态**

```python
@dataclass(frozen=True)
class AgentStatus:
    attempt: int
    max_attempts: int
    tool_calls_used: int
    max_tool_calls: int
    files_read: tuple[str, ...]
    changed_files: tuple[str, ...]
    last_tool: str | None
    last_error: str | None
    repeated_call_count: int
    no_progress_steps: int
    diff_inspected: bool
    target_test_run: bool


@dataclass(frozen=True)
class AgentRun:
    completed: bool
    turns: tuple[ModelTurn, ...]
    failure_reason: str | None = None
    final_status: AgentStatus | None = None
    guard_events: tuple[str, ...] = ()
```

```python
@dataclass(frozen=True)
class ToolProgress:
    call_fingerprint: str
    result_fingerprint: str
    progressed: bool
    error_code: str | None


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
```

`AgentRuntimeState` 用 set 保存 files read、changed files 和已见 `(call_fingerprint, result_fingerprint)`；`record_tool` 增加工具计数，更新连续重复数、错误、无进展数和验证位。read 的路径+行范围、search 的 query+scope+offset、Diff 内容、测试 passed/exit code 都参与指纹；首次出现的新结果算进展，相同结果不算。

- [ ] **Step 4: 添加稳定排序测试并完成绿灯**

```python
def test_status_snapshot_sorts_file_sets():
    state = AgentRuntimeState(2, 3, 8)
    state.record_tool("read_file", {"path": "z.py"}, ok_result({"path": "z.py"}))
    state.record_tool("read_file", {"path": "a.py"}, ok_result({"path": "a.py"}))
    assert state.snapshot().files_read == ("a.py", "z.py")
```

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p3-t1 tests/test_agent_state.py tests/test_models.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/models.py src/pyrepair/agent_state.py tests/test_agent_state.py tests/test_models.py`

Expected: `All checks passed!`

- [ ] **Step 5: 提交 Task 1**

```powershell
git add src/pyrepair/models.py src/pyrepair/agent_state.py tests/test_agent_state.py tests/test_models.py
git commit -m "feat: track deterministic agent runtime state"
```

---

### Task 2: LoopGuard 与 CompletionPolicy

**Files:**
- Create: `src/pyrepair/loop_guard.py`
- Create: `tests/test_loop_guard.py`

**Interfaces:**
- Produces: `GuardDecision(blocked, reason, guidance)`。
- Produces: `LoopGuard.before_tool(name, arguments, state)` 与 `after_tool(progress, state)`。
- Produces: `CompletionPolicy.evaluate(status, has_changes, budget_remaining)`。

- [ ] **Step 1: 写重复、错误、无进展和完成策略测试**

```python
def test_third_consecutive_identical_call_is_blocked():
    state = AgentRuntimeState(1, 3, 8)
    guard = LoopGuard()
    call = {"path": "app.py"}
    for _ in range(2):
        assert guard.before_tool("read_file", call, state).blocked is False
        progress = state.record_tool("read_file", call, ok_result({"content": "x"}))
        guard.after_tool(progress, state)
    assert guard.before_tool("read_file", call, state) == GuardDecision(
        True, "repeated_tool_call", None
    )


def status_with_change() -> AgentStatus:
    return AgentStatus(
        1, 3, 1, 8, (), ("app.py",), "replace_text", None,
        1, 0, False, False,
    )


def test_completion_requires_diff_and_target_test_after_change():
    status = replace(status_with_change(), diff_inspected=True,
                     target_test_run=False)
    decision = CompletionPolicy().evaluate(status, True, 2)
    assert decision.continue_loop is True
    assert "run_target_test" in decision.guidance
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p3-t2 tests/test_loop_guard.py -v`

Expected: FAIL，guard 模块尚不存在。

- [ ] **Step 3: 实现明确阈值规则**

```python
@dataclass(frozen=True)
class GuardDecision:
    blocked: bool
    reason: str | None = None
    guidance: str | None = None


class LoopGuard:
    def before_tool(self, name, arguments, state):
        fingerprint = call_fingerprint(name, arguments)
        if fingerprint == state.last_call_fingerprint and state.repeated_call_count >= 2:
            return GuardDecision(True, "repeated_tool_call")
        if state.identical_error_count(fingerprint) >= 2:
            return GuardDecision(True, "repeated_tool_error")
        return GuardDecision(False)

    def after_tool(self, progress, state):
        if state.no_progress_steps >= 4:
            return GuardDecision(True, "no_progress")
        if state.no_progress_steps == 3:
            return GuardDecision(False, guidance="Change strategy; gather new evidence.")
        if state.max_tool_calls - state.tool_calls_used <= 2:
            return GuardDecision(False, guidance="Inspect diff and run the target test.")
        return GuardDecision(False)
```

```python
class CompletionPolicy:
    def evaluate(self, status, has_changes, budget_remaining):
        if not has_changes:
            return CompletionDecision(True, False, None, None)
        missing = []
        if not status.diff_inspected:
            missing.append("show_diff")
        if not status.target_test_run:
            missing.append("run_target_test")
        if not missing:
            return CompletionDecision(True, False, None, None)
        if budget_remaining > 0:
            return CompletionDecision(
                False, True, None, "Required before finishing: " + ", ".join(missing)
            )
        return CompletionDecision(False, False,
                                  "required_verification_missing", None)
```

- [ ] **Step 4: 完成边界绿灯、Ruff 与提交**

增加“第二次重复允许且给 warning”“相同错误两次后阻止”“第三次无进展提示、第四次停止”“获得新证据后计数清零”“无修改可正常结束”“预算耗尽失败”测试。

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p3-t2 tests/test_agent_state.py tests/test_loop_guard.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/loop_guard.py tests/test_loop_guard.py`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/loop_guard.py tests/test_loop_guard.py
git commit -m "feat: stop repeated and unverified agent loops"
```

---

### Task 3: RepairAgent 状态栏与门禁集成

**Files:**
- Modify: `src/pyrepair/repair_agent.py`
- Modify: `tests/test_repair_agent.py`
- Modify: `tests/fakes.py`

**Interfaces:**
- Extends: `RepairAgent.run(report, previous_feedback=(), *, context=None, attempt=1, max_attempts=3, status_enabled=True)`。
- Consumes: `AgentRuntimeState`、`LoopGuard`、`CompletionPolicy`。
- Produces: 每次模型请求末尾的 agent_status XML 标签；标签正文是 `json.dumps(asdict(status), ensure_ascii=False, sort_keys=True)`。

- [ ] **Step 1: 写状态注入和修改后验证门禁失败测试**

```python
def extract_status(messages: list[dict]) -> dict:
    content = messages[-1]["content"]
    return json.loads(content.removeprefix("<agent_status>")
                     .removesuffix("</agent_status>"))


def edit_turn():
    return model_tool_turn("edit", "replace_text", {
        "path": "app.py", "old_text": "return a - b",
        "new_text": "return a + b",
    })


def test_agent_injects_fresh_status_before_every_model_call(registry):
    llm = FakeLLM([
        model_tool_turn("read", "read_file", {"path": "app.py"}),
        model_text_turn("stop"),
    ])
    result = RepairAgent(llm, registry, max_tool_calls=3).run(
        failure_report(), attempt=2, max_attempts=3
    )
    first = extract_status(llm.requests[0][0])
    second = extract_status(llm.requests[1][0])
    assert first["attempt"] == 2
    assert first["tool_calls_used"] == 0
    assert second["tool_calls_used"] == 1
    assert second["files_read"] == ["app.py"]
    assert result.final_status.tool_calls_used == 1


def test_agent_cannot_finish_after_edit_without_diff_and_test(registry):
    llm = FakeLLM([
        edit_turn(), model_text_turn("done"), model_text_turn("still done"),
    ])
    result = RepairAgent(llm, registry, max_tool_calls=1).run(failure_report())
    assert result.completed is False
    assert result.failure_reason == "required_verification_missing"
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p3-t3 tests/test_repair_agent.py -v`

Expected: FAIL，状态未注入且旧 Agent 可直接结束。

- [ ] **Step 3: 重构 Agent Loop**

```python
runtime = AgentRuntimeState(attempt, max_attempts, self.max_tool_calls)
guard = LoopGuard()
completion = CompletionPolicy()
max_model_turns = self.max_tool_calls + 3

while len(turns) < max_model_turns:
    status_message = _status_message(runtime.snapshot()) if status_enabled else None
    if status_message:
        messages.append(status_message)
    turn = self.client.complete(messages, self.registry.schemas())
    if status_message:
        messages.pop()
    turns.append(turn)
    messages.append(_assistant_message(turn))
    if not turn.tool_calls:
        decision = completion.evaluate(
            runtime.snapshot(), bool(runtime.changed_files),
            self.max_tool_calls - runtime.tool_calls_used,
        )
        if decision.complete:
            return _agent_run(True, turns, runtime, guard_events)
        if decision.continue_loop:
            messages.append({"role": "user", "content": decision.guidance})
            continue
        return _agent_run(False, turns, runtime, guard_events, decision.reason)
```

每个 tool call 执行前调用 `before_tool`，执行后先 `record_tool` 再 `after_tool`；block 立即结束 attempt，guidance 加入 Harness user message。工具预算逐调用扣减，批量 tool calls 不得越界；`max_model_turns` 防止模型连续输出文本造成死循环。

- [ ] **Step 4: 添加真实完成路径测试**

```python
def test_agent_finishes_after_edit_diff_and_target_test(registry):
    llm = FakeLLM([
        edit_turn(), model_tool_turn("diff", "show_diff", {}),
        model_tool_turn("test", "run_target_test", {}), model_text_turn("done"),
    ])
    result = RepairAgent(llm, registry, max_tool_calls=3).run(failure_report())
    assert result.completed is True
    assert result.final_status.diff_inspected is True
    assert result.final_status.target_test_run is True
```

无源码修改仍可正常结束；更新超预算、unknown tool、批量调用测试以断言 final status 和 guard events。

- [ ] **Step 5: 完成绿灯、Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p3-t3 tests/test_repair_agent.py tests/test_agent_state.py tests/test_loop_guard.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/repair_agent.py tests/test_repair_agent.py tests/fakes.py`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/repair_agent.py tests/test_repair_agent.py tests/fakes.py
git commit -m "feat: enforce stateful repair loop gates"
```

---

### Task 4: StructuredAttemptFeedback 与 Coordinator 接入

**Files:**
- Create: `src/pyrepair/feedback.py`
- Create: `tests/test_feedback.py`
- Modify: `src/pyrepair/coordinator.py`
- Modify: `src/pyrepair/cli.py`
- Modify: `src/pyrepair/repair_agent.py`
- Modify: `src/pyrepair/recorder.py`
- Modify: `tests/test_coordinator.py`
- Modify: `tests/test_repair_agent.py`
- Modify: `tests/test_recorder.py`

**Interfaces:**
- Produces: `FeedbackBuilder.build(*, attempt, outcome, snapshot, patch_check, review=None, verification=None) -> AttemptFeedback`。
- Replaces: 自由文本 evidence list 为 `feedbacks: list[AttemptFeedback]`。
- Produces: 下一轮输入的 `previous_attempts`，每项包含 `trusted=false`。

- [ ] **Step 1: 写反馈完整性和截断失败测试**

```python
def long_snapshot() -> PatchSnapshot:
    diff = "diff --git a/src/app.py b/src/app.py\n" + ("+x\n" * 4000)
    change = FileChange("src/app.py", "old\n", "new\n", diff, 4000, 1)
    return PatchSnapshot((change,))


def failed_verification(summary: str) -> VerificationResult:
    failure = PytestFailure("tests/test_app.py::test_add", "call", "failed",
                            "AssertionError", summary, summary, 1)
    run = TestRun(("python", "-m", "pytest"), 1, summary, "", 1,
                  failures=(failure,), capture_source="plugin")
    check = PatchCheck(True, (), ("src/app.py",), 1, 1)
    return VerificationResult(False, False, (), check, target_run=run)


def test_feedback_contains_patch_policy_review_and_test_evidence():
    feedback = FeedbackBuilder().build(
        attempt=1, outcome="verification_failed", snapshot=long_snapshot(),
        patch_check=PatchCheck(True, (), ("src/app.py",), 1, 1),
        review=ReviewResult(False, "high", ("side effect",), "reject"),
        verification=failed_verification("new assertion"),
    )
    assert feedback.changed_files == ("src/app.py",)
    assert "src/app.py" in feedback.candidate_diff
    assert feedback.review_findings == ("side effect",)
    assert feedback.target_failure.summary == "new assertion"
    assert len(feedback.candidate_diff) <= 6_000
    assert len(feedback.target_failure.output_tail) <= 4_000
    assert feedback.truncated is True
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p3-t4 tests/test_feedback.py -v`

Expected: FAIL，feedback 模块尚不存在。

- [ ] **Step 3: 实现反馈模型与 Builder**

```python
MAX_FEEDBACK_DIFF_CHARS = 6_000
MAX_TEST_OUTPUT_CHARS = 4_000
MAX_REVIEW_FINDINGS = 5


@dataclass(frozen=True)
class TestFailureEvidence:
    node_id: str | None
    exit_code: int | None
    summary: str
    output_tail: str
    timed_out: bool


@dataclass(frozen=True)
class AttemptFeedback:
    attempt: int
    outcome: str
    changed_files: tuple[str, ...]
    candidate_diff: str
    policy_violations: tuple[str, ...]
    review_findings: tuple[str, ...]
    target_failure: TestFailureEvidence | None
    regression_failures: tuple[str, ...]
    next_focus: str
    truncated: bool = False
```

`_truncate_diff` 保留头尾并插入 `[TRUNCATED]`；测试输出保留末尾；`next_focus` 固定映射：no patch→收集源码证据，policy→避开违规路径，review→处理首条 finding，target failure→依据新 traceback，regression→缩小修改范围，loop guard→改变搜索策略。

- [ ] **Step 4: Coordinator 每个失败出口构建反馈**

```python
feedbacks: list[AttemptFeedback] = []
agent_run = self.agent_factory(registry).run(
    failure_report, tuple(feedbacks), context=context_bundle,
    attempt=attempt, max_attempts=request.max_attempts,
)
```

```python
feedback = self.feedback_builder.build(
    attempt=attempt,
    outcome=attempt_record["outcome"],
    snapshot=snapshot,
    patch_check=check,
    review=review,
    verification=verification,
)
feedbacks.append(feedback)
attempt_record["feedback"] = asdict(feedback)
status = agent_run.final_status
attempt_record.update({
    "tool_calls_used": status.tool_calls_used if status else 0,
    "repeated_call_count": status.repeated_call_count if status else 0,
    "no_progress_steps": status.no_progress_steps if status else 0,
    "guard_events": list(agent_run.guard_events),
    "target_test_runs": sum(
        call.name == "run_target_test"
        for turn in agent_run.turns for call in turn.tool_calls
    ),
})
```

每个 `continue` 前调用统一 append-feedback 辅助函数，review/verification 可为 `None`。成功分支无需传入下一轮，但仍把最终反馈写入 report。CLI 注入 `FeedbackBuilder()`。

- [ ] **Step 5: 下一轮 prompt 使用结构化反馈**

```python
"previous_attempts": [{
    "attempt": item.attempt,
    "outcome": item.outcome,
    "changed_files": list(item.changed_files),
    "candidate_diff": item.candidate_diff,
    "policy_violations": list(item.policy_violations),
    "review_findings": list(item.review_findings),
    "target_failure": asdict(item.target_failure) if item.target_failure else None,
    "regression_failures": list(item.regression_failures),
    "next_focus": item.next_focus,
    "truncated": item.truncated,
    "trusted": False,
} for item in previous_feedback]
```

增加两轮 Coordinator 测试：第一轮目标测试失败，第二轮请求必须包含新 failure summary、候选 Diff、Policy/Review 字段；同时断言 working 已恢复 baseline。

- [ ] **Step 6: 运行 Phase 3 完整验收**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-phase3 --cov=pyrepair --cov-report=term-missing`

Expected: 所有非 live 测试 PASS，覆盖率不低于 91%。

Run: `.\.venv\Scripts\python.exe -m ruff check src tests benchmarks`

Expected: `All checks passed!`

- [ ] **Step 7: 提交 Task 4**

```powershell
git add src/pyrepair/feedback.py src/pyrepair/coordinator.py src/pyrepair/cli.py src/pyrepair/repair_agent.py src/pyrepair/recorder.py tests/test_feedback.py tests/test_coordinator.py tests/test_repair_agent.py tests/test_recorder.py
git commit -m "feat: feed structured attempt evidence into retries"
```
