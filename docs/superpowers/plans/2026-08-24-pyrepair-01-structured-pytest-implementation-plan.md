# PyRepair Phase 1 Structured pytest Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加 pytest 结构化采集、pytest 8/9 文本降级和稳定的主要失败选择，消除 `case_05`、`case_08` 在调用模型前的解析失败。

**Architecture:** `TestRunner` 加载内置 `pyrepair.pytest_plugin`，将报告写入工作副本的 `.pyrepair/internal/pytest-report.json` 并转换为 `PytestFailure`。报告缺失或损坏时使用文本解析；`PytestParser` 只选择主要失败并生成 `FailureReport`。

**Tech Stack:** Python 3.11+、pytest 8–9 hooks、dataclass、subprocess、JSON、pytest、Ruff。

## Global Constraints

- 从提交 `e89716f` 创建隔离 worktree 和 `codex/pyrepair-context-harness-upgrade` 分支；不得覆盖主工作区中的学习注释和简历文件。
- 不新增第三方运行依赖；内部模型继续使用 `dataclass`。
- 插件失败必须降级到文本解析，不能改变 pytest 原始退出码。
- 插件报告固定写入 `.pyrepair/internal/pytest-report.json`；`.pyrepair` 不得进入候选 Diff。
- 测试统一增加 `-p no:cacheprovider` 和仓库内 `--basetemp`，规避 Windows 临时目录权限问题。
- 每个任务执行红灯、最小实现、绿灯、Ruff、提交。

---

### Task 1: 结构化数据模型与报告读取器

**Files:**
- Modify: `src/pyrepair/models.py`
- Create: `src/pyrepair/pytest_capture.py`
- Modify: `tests/test_models.py`
- Create: `tests/test_pytest_capture.py`

**Interfaces:**
- Produces: `PytestFailure(node_id, phase, outcome, exception_type, summary, traceback, duration_ms)`。
- Produces: `load_capture_report(path: Path) -> tuple[PytestFailure, ...]`；无效报告抛 `CaptureReportError`。
- Produces: `TestRun.failures` 与 `TestRun.capture_source`，都有兼容默认值。

- [ ] **Step 1: 写模型与合法报告的失败测试**

```python
def test_test_run_keeps_structured_failures_with_legacy_defaults():
    failure = PytestFailure(
        "tests/test_app.py::test_add", "call", "failed",
        "AssertionError", "assert -1 == 5", "E assert -1 == 5", 7,
    )
    run = TestRun(("python", "-m", "pytest"), 1, "", "", 10,
                  failures=(failure,), capture_source="plugin")
    legacy = TestRun(("python", "-m", "pytest"), 1, "", "", 10)
    assert run.failures == (failure,)
    assert run.capture_source == "plugin"
    assert legacy.failures == ()
    assert legacy.capture_source == "none"


def test_load_capture_report_converts_valid_json(tmp_path):
    path = tmp_path / "pytest-report.json"
    path.write_text(json.dumps({"failures": [{
        "node_id": "tests/test_app.py::test_add", "phase": "call",
        "outcome": "failed", "exception_type": "AssertionError",
        "summary": "assert -1 == 5", "traceback": "E assert -1 == 5",
        "duration_ms": 7,
    }]}), encoding="utf-8")
    assert load_capture_report(path)[0].phase == "call"
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p1-t1 tests/test_models.py tests/test_pytest_capture.py -v`

Expected: FAIL，无法导入 `PytestFailure` 或 `load_capture_report`。

- [ ] **Step 3: 添加最小实现**

```python
@dataclass(frozen=True)
class PytestFailure:
    node_id: str
    phase: Literal["setup", "call", "teardown", "collection"]
    outcome: str
    exception_type: str | None
    summary: str
    traceback: str
    duration_ms: int


@dataclass(frozen=True)
class TestRun:
    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    launch_error: str | None = None
    failures: tuple[PytestFailure, ...] = ()
    capture_source: Literal["plugin", "text", "none"] = "none"
```

```python
class CaptureReportError(RuntimeError):
    pass


def load_capture_report(path: Path) -> tuple[PytestFailure, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload["failures"]
        if not isinstance(items, list):
            raise TypeError("failures must be a list")
        return tuple(_parse_failure(item) for item in items)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CaptureReportError("invalid_pytest_capture_report") from exc
```

`_parse_failure()` 逐字段验证：字符串字段、可空异常类型、非负整数耗时和四种 phase；拒绝额外字段。

- [ ] **Step 4: 增加损坏报告测试并完成绿灯**

```python
@pytest.mark.parametrize("payload", ["{", '{"failures": {}}',
                                     '{"failures": [{"phase": "unknown"}]}'])
def test_load_capture_report_rejects_invalid_payload(tmp_path, payload):
    path = tmp_path / "pytest-report.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CaptureReportError, match="invalid_pytest_capture_report"):
        load_capture_report(path)
```

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p1-t1 tests/test_models.py tests/test_pytest_capture.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/models.py src/pyrepair/pytest_capture.py tests/test_models.py tests/test_pytest_capture.py`

Expected: `All checks passed!`

- [ ] **Step 5: 提交 Task 1**

```powershell
git add src/pyrepair/models.py src/pyrepair/pytest_capture.py tests/test_models.py tests/test_pytest_capture.py
git commit -m "feat: add structured pytest capture models"
```

---

### Task 2: 内置 pytest 插件与 TestRunner 接入

**Files:**
- Create: `src/pyrepair/pytest_plugin.py`
- Modify: `src/pyrepair/testing.py`
- Modify: `tests/test_testing.py`
- Create: `tests/fixtures/pytest_capture_project/test_phases.py`

**Interfaces:**
- Consumes: `load_capture_report(path)`。
- Produces: 环境变量 `PYREPAIR_PYTEST_REPORT` 和 `capture_source="plugin"`。

- [ ] **Step 1: 写 call/setup/teardown 采集失败测试**

```python
def test_runner_loads_structured_call_failure():
    result = PytestRunner(5).run(FIXTURES / "failing_project")
    assert result.capture_source == "plugin"
    assert result.failures[0].node_id == "test_fail.py::test_failure"
    assert result.failures[0].phase == "call"


def test_runner_captures_setup_and_teardown_failures():
    result = PytestRunner(5).run(FIXTURES / "pytest_capture_project")
    assert {(item.node_id, item.phase) for item in result.failures} == {
        ("test_phases.py::test_setup_error", "setup"),
        ("test_phases.py::test_teardown_error", "teardown"),
    }
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p1-t2 tests/test_testing.py -v`

Expected: FAIL，`capture_source` 仍为 `none`。

- [ ] **Step 3: 实现只写报告的插件**

```python
_FAILURES: list[dict[str, object]] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.failed:
        _FAILURES.append(_serialize_report(report, report.when))


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.failed:
        _FAILURES.append(_serialize_report(report, "collection"))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session
    destination = os.environ.get("PYREPAIR_PYTEST_REPORT")
    if not destination:
        return
    try:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": 1, "exit_code": int(exitstatus), "failures": _FAILURES,
        }, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return
```

`_serialize_report()` 使用 `nodeid/when/outcome/longreprtext/duration`；summary 取最后非空行并限制 1000 字符，traceback 保留末尾 12000 字符，exception type 从 `TypeName: message` 行提取。插件不得修改测试结果、fixture 或 stdout。

- [ ] **Step 4: 在 TestRunner 设置路径并读取报告**

```python
report_path = repo / ".pyrepair" / "internal" / "pytest-report.json"
report_path.unlink(missing_ok=True)
environment = os.environ.copy()
environment["PYREPAIR_PYTEST_REPORT"] = str(report_path)
command.extend(["-p", "pyrepair.pytest_plugin"])
completed = subprocess.run(
    command,
    cwd=repo,
    env=environment,
    capture_output=True,
    text=True,
    timeout=self.timeout_seconds,
    shell=False,
    encoding="utf-8",
    errors="replace",
    check=False,
)
try:
    failures = load_capture_report(report_path)
    capture_source = "plugin"
except CaptureReportError:
    failures, capture_source = (), "none"
```

timeout 和 launch error 分支保留原始语义。更新 shell=False 测试，断言报告路径位于目标仓库的 `.pyrepair/internal`。

- [ ] **Step 5: 完成绿灯、Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p1-t2 tests/test_testing.py tests/test_pytest_capture.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/pytest_plugin.py src/pyrepair/testing.py tests/test_testing.py`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/pytest_plugin.py src/pyrepair/testing.py tests/test_testing.py tests/fixtures/pytest_capture_project
git commit -m "feat: capture pytest failures through internal plugin"
```

---

### Task 3: pytest 8/9 文本降级与主要失败选择

**Files:**
- Modify: `src/pyrepair/pytest_parser.py`
- Modify: `src/pyrepair/testing.py`
- Modify: `tests/test_pytest_parser.py`
- Modify: `tests/test_testing.py`
- Create: `tests/fixtures/pytest_outputs/pytest9_failed_without_suffix.txt`
- Create: `tests/fixtures/pytest_outputs/setup_error.txt`
- Create: `tests/fixtures/pytest_outputs/parameterized.txt`

**Interfaces:**
- Produces: `parse_text_failures(text: str) -> tuple[PytestFailure, ...]`。
- Produces: `select_primary_failure(failures, preferred_node_id=None) -> PytestFailure | None`。
- Produces: `PytestParser.parse(run, preferred_node_id=None) -> FailureReport`。

- [ ] **Step 1: 写摘要格式和优先级失败测试**

```python
@pytest.mark.parametrize("line", [
    "FAILED tests/test_a.py::test_x - AssertionError: boom",
    "FAILED tests/test_a.py::test_x",
    "ERROR tests/test_a.py::test_x",
    "tests/test_a.py::test_x FAILED",
])
def test_text_fallback_accepts_pytest_8_and_9_shapes(line):
    assert parse_text_failures(line)[0].node_id == "tests/test_a.py::test_x"


def make_failure(node_id: str, phase: str) -> PytestFailure:
    return PytestFailure(node_id, phase, "failed", "AssertionError",
                         "boom", "E AssertionError: boom", 1)


def test_primary_failure_prefers_call_then_setup_then_collection():
    failures = (
        make_failure("tests/test_a.py::test_collect", "collection"),
        make_failure("tests/test_a.py::test_setup", "setup"),
        make_failure("tests/test_a.py::test_call", "call"),
    )
    assert select_primary_failure(failures).phase == "call"
    assert select_primary_failure(
        failures, "tests/test_a.py::test_setup"
    ).phase == "setup"
```

- [ ] **Step 2: 确认红灯后实现稳定解析**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p1-t3 tests/test_pytest_parser.py -v`

Expected: FAIL，新函数尚不存在。

```python
SUMMARY_PATTERNS = (
    re.compile(r"^FAILED\s+(?P<node>\S+)(?:\s+-\s+(?P<detail>.*))?$"),
    re.compile(r"^ERROR\s+(?P<node>\S+)(?:\s+-\s+(?P<detail>.*))?$"),
    re.compile(r"^(?P<node>\S+::\S+)\s+(?P<kind>FAILED|ERROR)$"),
)
PHASE_PRIORITY = {"call": 0, "setup": 1, "teardown": 2, "collection": 3}


def select_primary_failure(failures, preferred_node_id=None):
    preferred = [item for item in failures if item.node_id == preferred_node_id]
    candidates = preferred or list(failures)
    return min(candidates,
               key=lambda item: (PHASE_PRIORITY[item.phase], item.node_id),
               default=None)
```

`parse_text_failures()` 去除 ANSI、保留参数化 node id 的 `[]`、把路径统一为 `/`，并从相邻 traceback 提取异常类型与摘要；无法识别时返回空 tuple。

- [ ] **Step 3: 让 Runner 降级并让 Parser 消费结构化失败**

```python
raw = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
try:
    failures = load_capture_report(report_path)
    capture_source = "plugin"
except CaptureReportError:
    failures = parse_text_failures(raw)
    capture_source = "text" if failures else "none"
```

```python
def parse(self, run: TestRun, preferred_node_id: str | None = None) -> FailureReport:
    raw = "\n".join(part for part in (run.stdout, run.stderr) if part)
    failure = select_primary_failure(run.failures, preferred_node_id)
    if failure is None:
        return FailureReport(None, None, raw[-6000:], raw[-500:], (), False)
    return FailureReport(
        failure.node_id, failure.exception_type, failure.traceback,
        failure.summary, _related_paths(failure.traceback), True,
    )
```

保留 `extract_failed_node_ids(text)` 兼容包装器，内部改为调用 `parse_text_failures`。增加 monkeypatch 测试让报告读取抛错，断言退出码仍为 1 且 `capture_source == "text"`。

- [ ] **Step 4: 运行绿灯、Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p1-t3 tests/test_pytest_parser.py tests/test_testing.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/pytest_parser.py src/pyrepair/testing.py tests/test_pytest_parser.py tests/test_testing.py`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/pytest_parser.py src/pyrepair/testing.py tests/test_pytest_parser.py tests/test_testing.py tests/fixtures/pytest_outputs
git commit -m "fix: support pytest 8 and 9 failure formats"
```

---

### Task 4: Coordinator、Verifier、Recorder 接入与阶段验收

**Files:**
- Modify: `src/pyrepair/coordinator.py`
- Modify: `src/pyrepair/verifier.py`
- Modify: `src/pyrepair/recorder.py`
- Modify: `tests/test_coordinator.py`
- Modify: `tests/test_verifier.py`
- Modify: `tests/test_recorder.py`
- Modify: `tests/test_benchmark_manifest.py`

**Interfaces:**
- Consumes: `TestRun.failures` 与 `capture_source`。
- Produces: baseline failure set 和 regression set 均来自结构化结果。
- Produces: 产物中的 `capture_source`、`failure_count`。

- [ ] **Step 1: 写结构化回归和已知用例测试**

```python
def make_failure(node_id: str, phase: str) -> PytestFailure:
    return PytestFailure(node_id, phase, "failed", "AssertionError",
                         "boom", "E AssertionError: boom", 1)


class SequenceRunner:
    def __init__(self, runs):
        self.runs = iter(runs)

    def run(self, repo, target=None):
        del repo, target
        return next(self.runs)


def passing_run() -> TestRun:
    return TestRun(("python", "-m", "pytest"), 0, "1 passed", "", 1,
                   capture_source="plugin")


def snapshot() -> PatchSnapshot:
    return PatchSnapshot(())


def test_verifier_uses_structured_failures_for_regression(tmp_path):
    full = TestRun(
        ("python", "-m", "pytest"), 1, "changed summary", "", 5,
        failures=(make_failure("tests/test_other.py::test_other", "call"),),
        capture_source="plugin",
    )
    result = Verifier(
        SequenceRunner([passing_run(), full]), PatchPolicyGate()
    ).verify(tmp_path, "tests/test_app.py::test_add",
             {"tests/test_app.py::test_add"}, snapshot())
    assert result.regression_failures == ("tests/test_other.py::test_other",)


@pytest.mark.parametrize("case_id", ["case_05", "case_08"])
def test_known_pytest9_cases_produce_parseable_failure(case_id):
    root = PROJECT_ROOT / "benchmarks" / "cases" / case_id
    run = PytestRunner(10).run(root)
    report = PytestParser().parse(run)
    assert run.capture_source in {"plugin", "text"}
    assert report.parseable is True
    assert report.node_id is not None
```

- [ ] **Step 2: 运行测试并确认核心链路红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p1-t4 tests/test_verifier.py tests/test_coordinator.py tests/test_recorder.py tests/test_benchmark_manifest.py -v`

Expected: FAIL，Verifier 或产物仍依赖文本摘要。

- [ ] **Step 3: 替换失败集合并记录来源**

```python
baseline_failures = {item.node_id for item in baseline.failures}
baseline_failures.add(failure_report.node_id)

current_failures = {item.node_id for item in full.failures}
regressions = tuple(sorted(current_failures - baseline_failures))
```

```python
recorder.append_event({
    "type": "baseline",
    "exit_code": baseline.exit_code,
    "duration_ms": baseline.duration_ms,
    "capture_source": baseline.capture_source,
    "failure_count": len(baseline.failures),
})
```

删除 Coordinator、Verifier 对 `extract_failed_node_ids` 的依赖；调用 `parser.parse(baseline, request.test_target)`。在 `pytest.log` 增加采集来源与失败数，不向 `report.json` 重复写完整 traceback。

- [ ] **Step 4: 运行 Phase 1 完整验收**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-phase1 --cov=pyrepair --cov-report=term-missing`

Expected: 所有非 live 测试 PASS，覆盖率不低于 91%。

Run: `.\.venv\Scripts\python.exe -m ruff check src tests benchmarks`

Expected: `All checks passed!`

- [ ] **Step 5: 提交 Task 4 并检查阶段历史**

```powershell
git add src/pyrepair/coordinator.py src/pyrepair/verifier.py src/pyrepair/recorder.py tests/test_coordinator.py tests/test_verifier.py tests/test_recorder.py tests/test_benchmark_manifest.py
git commit -m "refactor: consume structured pytest failures end to end"
git log --oneline -4
```

Expected: 最近四个提交依次对应 models、plugin、fallback、integration，工作树无本阶段遗漏。
