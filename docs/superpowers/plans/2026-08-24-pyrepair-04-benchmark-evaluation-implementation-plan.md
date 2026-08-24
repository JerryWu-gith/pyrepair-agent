# PyRepair Phase 4 Benchmark and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Benchmark 扩展为 30 个分层任务，提供 control/context/state/full 四组累积式消融、可恢复重复运行和脱敏公开结果。

**Architecture:** `HarnessFeatures` 将 arm 映射为确定性功能开关；Benchmark runner 用 experiment fingerprint 和 `case_id/repeat_index` 唯一键保证恢复正确。`benchmark_evaluation.py` 负责指标、环境指纹与公开脱敏，case 项目只包含一个人工 Bug，参考补丁不会复制给 Agent。

**Tech Stack:** Python 3.11+、argparse、JSONL、hashlib、subprocess、pytest、Ruff、DeepSeek V4 Flash。

## Global Constraints

- 先完成 Phase 1–3；control 也必须使用新的 pytest 结构化采集器。
- 四组固定为：control；context=control+ContextBuilder+结构化工具；state=context+AgentStatus+LoopGuard；full=state+StructuredAttemptFeedback。
- 固定模型、最大 attempt=3、工具预算=8、Policy、Review、Verifier 和数据集版本；不得把混合配置聚合。
- 数据集总数 30：原 Level 1 为 15，新增 Level 2 为 10、Level 3 为 5；每个任务恰好一个失败测试和一个人工注入 Bug。
- 原始结果位于 `benchmarks/results/raw/` 且不提交；公开结果位于 `benchmarks/results/public/`。
- 公开数据不得包含密钥、绝对路径、环境变量、用户项目代码或 reasoning content。
- 先运行所有 arm 单次全量，再仅对 context/full 关键组运行三次；报告明确样本量，不外推普遍结论。

---

### Task 1: HarnessFeatures 与四种 Arm 装配

**Files:**
- Create: `src/pyrepair/features.py`
- Create: `tests/test_features.py`
- Modify: `src/pyrepair/models.py`
- Modify: `src/pyrepair/coordinator.py`
- Modify: `src/pyrepair/tools.py`
- Modify: `src/pyrepair/repair_agent.py`
- Modify: `src/pyrepair/cli.py`
- Modify: `tests/test_coordinator.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `HarnessArm = Literal["control", "context", "state", "full"]`。
- Produces: `HarnessFeatures.for_arm(arm) -> HarnessFeatures`。
- Extends: `RepairRequest.harness_arm: HarnessArm = "full"`；普通 CLI 始终使用 full。
- Extends: registry factory 为 `(session, node_id, enhanced_tools) -> ToolRegistry`。

- [ ] **Step 1: 写累积开关失败测试**

```python
@pytest.mark.parametrize(("arm", "expected"), [
    ("control", (False, False, False)),
    ("context", (True, False, False)),
    ("state", (True, True, False)),
    ("full", (True, True, True)),
])
def test_harness_features_are_cumulative(arm, expected):
    features = HarnessFeatures.for_arm(arm)
    assert (
        features.context_enabled,
        features.state_enabled,
        features.feedback_enabled,
    ) == expected


def test_normal_repair_request_defaults_to_full_harness():
    assert RepairRequest(Path("."), dry_run=True).harness_arm == "full"
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p4-t1 tests/test_features.py tests/test_coordinator.py tests/test_cli.py -v`

Expected: FAIL，feature 模块和 request 字段尚不存在。

- [ ] **Step 3: 实现不可变功能配置**

```python
HarnessArm = Literal["control", "context", "state", "full"]


@dataclass(frozen=True)
class HarnessFeatures:
    context_enabled: bool
    state_enabled: bool
    feedback_enabled: bool

    @classmethod
    def for_arm(cls, arm: HarnessArm) -> "HarnessFeatures":
        mapping = {
            "control": cls(False, False, False),
            "context": cls(True, False, False),
            "state": cls(True, True, False),
            "full": cls(True, True, True),
        }
        try:
            return mapping[arm]
        except KeyError as exc:
            raise ValueError(f"unknown_harness_arm:{arm}") from exc
```

- [ ] **Step 4: 在 Coordinator 的三个接入点应用开关**

```python
features = HarnessFeatures.for_arm(request.harness_arm)
context_bundle = (
    self.context_builder.build(session.baseline, failure_report)
    if features.context_enabled else empty_context_bundle()
)
registry = self.registry_factory(
    session, failure_report.node_id, features.context_enabled
)
agent_run = self.agent_factory(registry).run(
    failure_report,
    tuple(feedbacks) if features.feedback_enabled else (),
    context=context_bundle,
    attempt=attempt,
    max_attempts=request.max_attempts,
    status_enabled=features.state_enabled,
)
```

`ToolRegistry(enhanced_tools=False)` 只注册 read/search/replace/diff/test，但结果仍使用稳定 JSON；true 时增加 symbol/reference/module。control 不构建 Context、状态栏或反馈；所有 arm 都运行 Policy、Review、目标测试和全量回归。

- [ ] **Step 5: 添加按 arm 的装配测试**

```python
class CountingContextBuilder:
    def __init__(self):
        self.calls = 0

    def build(self, root, report):
        del root, report
        self.calls += 1
        return empty_context_bundle()


class RecordingAgent:
    def __init__(self):
        self.calls = []

    def run(self, report, previous_feedback=(), **kwargs):
        del report
        self.calls.append((tuple(previous_feedback), kwargs["status_enabled"]))
        return AgentRun(True, ())


@pytest.mark.parametrize(("arm", "context_calls", "status", "feedback_count"), [
    ("control", 0, False, 0), ("context", 1, False, 0),
    ("state", 1, True, 0), ("full", 1, True, 1),
])
def test_coordinator_assembles_requested_arm(
    tmp_path, arm, context_calls, status, feedback_count
):
    repo = make_buggy_repo(tmp_path)
    context_builder = CountingContextBuilder()
    agent = RecordingAgent()
    coordinator = build_coordinator(
        repo, lambda registry: agent, lambda: None,
        context_builder=context_builder,
    )
    coordinator.run(RepairRequest(repo, harness_arm=arm, max_attempts=2))
    assert context_builder.calls == context_calls
    assert agent.calls[-1][1] is status
    assert len(agent.calls[-1][0]) == feedback_count
```

- [ ] **Step 6: 完成绿灯、Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p4-t1 tests/test_features.py tests/test_coordinator.py tests/test_cli.py tests/test_tools.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src tests`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/features.py src/pyrepair/models.py src/pyrepair/coordinator.py src/pyrepair/tools.py src/pyrepair/repair_agent.py src/pyrepair/cli.py tests/test_features.py tests/test_coordinator.py tests/test_cli.py
git commit -m "feat: configure cumulative benchmark harness arms"
```

---

### Task 2: 可恢复重复实验、指纹与指标

**Files:**
- Create: `benchmarks/benchmark_evaluation.py`
- Modify: `benchmarks/run_benchmark.py`
- Modify: `tests/test_benchmark_runner.py`

**Interfaces:**
- Produces: `ExperimentFingerprint(model, arm, dataset_version, git_commit, python_version, pytest_version)`。
- Produces: `run_key(case_id, repeat_index) -> str`。
- Produces: CLI `--arm control|context|state|full`、`--repeat N`。
- Produces: `raw_result_path = raw_dir / f"{timestamp}-{model}-{arm}.jsonl"`。

- [ ] **Step 1: 写参数、run key 和混合配置拒绝测试**

```python
def test_benchmark_cli_exposes_arm_repeat_and_resume():
    args = parse_args(["--arm", "state", "--repeat", "3"])
    assert args.arm == "state"
    assert args.repeat == 3


def test_expand_runs_creates_stable_case_repeat_keys():
    runs = expand_runs([{"id": "case_01"}, {"id": "case_02"}], repeat=2)
    assert [item.run_key for item in runs] == [
        "case_01#1", "case_01#2", "case_02#1", "case_02#2"
    ]


def test_resume_rejects_mixed_experiment_fingerprint():
    expected = ExperimentFingerprint(
        "deepseek-v4-flash", "full", 2, "abc", "3.13.5", "9.1.1"
    )
    record = {"experiment": {**asdict(expected), "arm": "control"}}
    with pytest.raises(ValueError, match="different experiment fingerprint"):
        validate_resume_records([record], expected)
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p4-t2 tests/test_benchmark_runner.py -v`

Expected: FAIL，新参数与评测模块尚不存在。

- [ ] **Step 3: 实现实验身份和待运行选择**

```python
@dataclass(frozen=True)
class ExperimentFingerprint:
    model: str
    arm: HarnessArm
    dataset_version: int
    git_commit: str
    python_version: str
    pytest_version: str


@dataclass(frozen=True)
class BenchmarkRun:
    case: dict[str, Any]
    repeat_index: int

    @property
    def run_key(self) -> str:
        return f"{self.case['id']}#{self.repeat_index}"
```

`git_commit` 使用 `git rev-parse HEAD`，失败时为 `unknown` 并禁止生成 public 结果；Python 与 pytest 版本来自 `platform.python_version()` 和 `pytest.__version__`。resume 逐条比较完整 experiment 对象，只跳过 status 为 success/failed 的相同 run key；error 可重试。

- [ ] **Step 4: 扩展 artifacts 指标和报告**

```python
record.update({
    "run_key": f"{case['id']}#{repeat_index}",
    "repeat_index": repeat_index,
    "experiment": asdict(experiment),
    "context_chars": sum(e.get("total_chars", 0) for e in context_events),
    "context_snippets": sum(e.get("snippet_count", 0) for e in context_events),
    "tool_calls": sum(a.get("tool_calls_used", 0) for a in attempts),
    "repeated_calls": sum(a.get("repeated_call_count", 0) for a in attempts),
    "no_progress_steps": sum(a.get("no_progress_steps", 0) for a in attempts),
    "loop_guard_blocks": sum(bool(a.get("guard_events")) for a in attempts),
    "target_test_runs": sum(a.get("target_test_runs", 0) for a in attempts),
})
```

`summarize()` 增加平均工具数、上下文字符、LoopGuard 阻止数；`render_markdown()` 展示 fingerprint、arm 和 repeats。不得将不同 experiment 传入同一次 summarize。

- [ ] **Step 5: 完成 CLI、恢复、指标绿灯与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p4-t2 tests/test_benchmark_runner.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --help`

Expected: 输出包含 `--case --model --arm --repeat --resume`。

Run: `.\.venv\Scripts\python.exe -m ruff check benchmarks tests/test_benchmark_runner.py`

Expected: `All checks passed!`

```powershell
git add benchmarks/benchmark_evaluation.py benchmarks/run_benchmark.py tests/test_benchmark_runner.py
git commit -m "feat: run resumable benchmark ablations"
```

---

### Task 3: 新增 15 个 Level 2/3 可复现任务

**Files:**
- Modify: `benchmarks/manifest.json`
- Modify: `benchmarks/run_benchmark.py`
- Create: directories `benchmarks/cases/case_16` through `benchmarks/cases/case_30`
- Modify: `tests/test_benchmark_manifest.py`

**Interfaces:**
- Produces: manifest `version=2` 和 30 个 case。
- 每个新 case 产生：`case.json`、`reference.patch`、`pyproject.toml`、源码、测试。
- `copy_case_for_run` 排除 `case.json` 和 `reference.patch`。

- [ ] **Step 1: 写数据集规模、难度和泄漏失败测试**

```python
def test_manifest_has_thirty_tiered_non_leaking_cases():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    assert manifest["version"] == 2
    assert len(cases) == 30
    assert Counter(case["difficulty"] for case in cases) == {
        "level_1": 15, "level_2": 10, "level_3": 5,
    }
    assert all((MANIFEST_PATH.parent / case["path"] / "reference.patch").is_file()
               for case in cases[15:])


def test_copy_case_excludes_reference_answer(tmp_path):
    case_16 = MANIFEST_PATH.parent / "cases" / "case_16"
    destination = copy_case_for_run(case_16, tmp_path / "staged")
    assert not (destination / "case.json").exists()
    assert not (destination / "reference.patch").exists()
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p4-t3 tests/test_benchmark_manifest.py tests/test_benchmark_runner.py -v`

Expected: FAIL，manifest 仍是 15 个 version 1 case。

- [ ] **Step 3: 按精确任务矩阵创建 case 16–30**

| Case | Level | 源码目标 | 人工 Bug → 参考修复 | 唯一失败测试 |
| --- | --- | --- | --- | --- |
| 16 | 2 | `src/pricing/service.py` | `subtotal - tax` → `subtotal + tax` | `test_total_adds_tax` |
| 17 | 2 | `src/auth/service.py` | `normalize_email(raw)` → `normalize_email(raw.strip())` | `test_login_ignores_outer_spaces` |
| 18 | 2 | `src/shipping/service.py` | `zone(postal[-1])` → `zone(postal[0])` | `test_northern_zone_rate` |
| 19 | 2 | `src/inventory/service.py` | `stock < qty` → `stock <= qty` | `test_reserve_last_item` |
| 20 | 2 | `src/dates/formatter.py` | `%m-%d-%Y` → `%Y-%m-%d` | `test_iso_display` |
| 21 | 2 | `src/orders/total.py` | `discount_rate(user)` → `discount_rate(user.tier)` | `test_gold_order_discount` |
| 22 | 2 | `src/money/service.py` | `quantize(CENT, 2)` → `quantize(CENT, ROUND_HALF_UP)` | `test_half_cent_rounds_up` |
| 23 | 2 | `src/api/translator.py` | `except KeyError` → `except ValueError` | `test_invalid_payload_is_400` |
| 24 | 2 | `src/cache/session.py` | `clear()` 漏清 timestamps → 同时清空 timestamps | `test_cache_fixture_starts_empty` |
| 25 | 2 | `src/text/slug.py` | `replace(" ", "-")` → `re.sub(r"\\s+", "-", text)` | `test_slug_cases[hello--world]` |
| 26 | 3 | `src/users/normalize.py` | 错调用 `src/logs/normalize.py` 同名函数 → 用户 normalize | `test_user_name_normalization` |
| 27 | 3 | `src/billing/calculate.py` | service import shipping calculate → billing calculate | `test_invoice_total` |
| 28 | 3 | `src/renderers/table.py` | header 取 values → 取 keys；`legacy/table.py` 为干扰 | `test_table_header_order` |
| 29 | 3 | `src/checkout/service.py` | 先 discount 后 convert → 先 convert 后 discount | `test_foreign_currency_discount` |
| 30 | 3 | `src/schedule/service.py` | naive datetime 重复加 offset → 只应用一次 timezone | `test_local_schedule_to_utc` |

case 16–25 至少跨两个源码文件，26–30 包含同名符号或干扰文件。参考补丁只改“源码目标”列，不修改 tests。

- [ ] **Step 4: 写统一 metadata 并补齐 manifest**

```json
{
  "id": "case_16",
  "title": "Cross-file tax composition",
  "difficulty": "level_2",
  "tags": ["cross_file", "import"],
  "expected_source_files": ["src/pricing/service.py"],
  "primary_test": "tests/test_pricing.py::test_total_adds_tax",
  "requires_cross_file_context": true
}
```

其余 case 使用矩阵对应 id、源码目标和 test node；manifest 只保存 `id/category/path/title/difficulty/tags`，不保存修复行。原 15 个 case 补 `difficulty="level_1"` 和现有 category tag。

- [ ] **Step 5: 验证 baseline 与参考补丁**

```python
def pytest_exit(root: Path) -> tuple[int | None, int]:
    run = PytestRunner(10).run(root)
    return run.exit_code, len(run.failures)


def test_each_case_has_one_failure_and_reference_patch_passes(tmp_path):
    for case in load_cases():
        root = MANIFEST_PATH.parent / case["path"]
        assert pytest_exit(root) == (1, 1)
        if case["difficulty"] != "level_1":
            staged = copy_case_for_run(root, tmp_path / case["id"])
            applied = subprocess.run(
                ["git", "apply", str((root / "reference.patch").resolve())],
                cwd=staged, capture_output=True, text=True, shell=False,
                encoding="utf-8", errors="replace", check=False,
            )
            assert applied.returncode == 0, applied.stderr
            assert pytest_exit(staged) == (0, 0)
```

`pytest_exit` 返回 `(returncode, len(TestRun.failures))`，不再匹配 `"1 failed"`。测试内 unified patch applier 只接受 `a/path`、`b/path` 和行 hunk，路径越界立即失败。

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p4-t3 tests/test_benchmark_manifest.py -v`

Expected: PASS，30 个 baseline 各 1 个 failure，15 个新参考补丁应用后通过。

- [ ] **Step 6: Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m ruff check benchmarks tests/test_benchmark_manifest.py`

Expected: `All checks passed!`

```powershell
git add benchmarks/manifest.json benchmarks/run_benchmark.py benchmarks/cases/case_16 benchmarks/cases/case_17 benchmarks/cases/case_18 benchmarks/cases/case_19 benchmarks/cases/case_20 benchmarks/cases/case_21 benchmarks/cases/case_22 benchmarks/cases/case_23 benchmarks/cases/case_24 benchmarks/cases/case_25 benchmarks/cases/case_26 benchmarks/cases/case_27 benchmarks/cases/case_28 benchmarks/cases/case_29 benchmarks/cases/case_30 tests/test_benchmark_manifest.py
git commit -m "test: add cross-file repair benchmark cases"
```

---

### Task 4: 公开结果脱敏、文档与最终实验

**Files:**
- Modify: `.gitignore`
- Modify: `benchmarks/benchmark_evaluation.py`
- Modify: `benchmarks/run_benchmark.py`
- Create: `benchmarks/results/public/.gitkeep`
- Modify: `tests/test_benchmark_runner.py`
- Modify: `README.md`
- Create: `docs/context-harness-architecture.md`
- Modify: `docs/benchmark-results.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `sanitize_public_record(record) -> dict[str, Any]`。
- Produces: `publish_results(raw_path, public_path) -> None`。
- Produces: CLI `--publish-results`，在一个实验完成后自动写对应 public JSONL。
- CI 只运行离线测试、Ruff 和 30 case baseline/reference 验证，不调用 LLM。

- [ ] **Step 1: 写脱敏和路径拒绝失败测试**

```python
def test_public_record_removes_patch_paths_secrets_and_reasoning():
    raw = {
        "case_id": "case_16", "candidate_patch": "secret patch",
        "artifact_dir": "D:/Users/Jerry/private", "reasoning_content": "hidden",
        "api_key": "sk-secret", "changed_files": ["src/pricing/service.py"],
    }
    public = sanitize_public_record(raw)
    assert "candidate_patch" not in public
    assert public["candidate_patch_sha256"] == hashlib.sha256(
        b"secret patch"
    ).hexdigest()
    assert "artifact_dir" not in public
    assert "reasoning_content" not in public
    assert "api_key" not in public


def write_jsonl(root: Path, records: list[dict]) -> Path:
    path = root / "raw.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in records),
                    encoding="utf-8")
    return path


def test_publish_rejects_unknown_git_commit(tmp_path):
    raw = write_jsonl(tmp_path, [{"experiment": {"git_commit": "unknown"}}])
    with pytest.raises(ValueError, match="verified git commit"):
        publish_results(raw, tmp_path / "public.jsonl")
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p4-t4 tests/test_benchmark_runner.py -v`

Expected: FAIL，公开结果函数尚不存在。

- [ ] **Step 3: 实现白名单式公开记录**

```python
PUBLIC_FIELDS = {
    "recorded_at", "run_key", "case_id", "category", "difficulty",
    "status", "attempts", "duration_seconds", "prompt_tokens",
    "completion_tokens", "regression_count", "policy_rejection_count",
    "failure_reason", "changed_files", "repeat_index", "experiment",
    "context_chars", "context_snippets", "tool_calls", "repeated_calls",
    "no_progress_steps", "loop_guard_blocks", "target_test_runs",
}


def sanitize_public_record(record):
    public = {key: record[key] for key in PUBLIC_FIELDS if key in record}
    patch = record.get("candidate_patch", "")
    public["candidate_patch_sha256"] = hashlib.sha256(
        patch.encode("utf-8")
    ).hexdigest()
    _reject_absolute_paths_or_secrets(public)
    return public
```

白名单会丢弃 `api_key/authorization/token/secret/reasoning_content/artifact_dir` 等非公开字段；`_reject_absolute_paths_or_secrets` 再递归检查所有保留字段的 Windows drive、UNC、POSIX absolute path 和 secret value pattern，命中时拒绝发布。

- [ ] **Step 4: 更新安全边界、架构、CI 与忽略规则**

```gitignore
benchmarks/results/raw/
!benchmarks/results/public/
!benchmarks/results/public/.gitkeep
```

README 明确：临时工作区只隔离修改，pytest 在宿主 Python 执行，可访问宿主权限，因此仅用于可信本地项目；Docker、MCP、自动 PR、多故障修复不在本版本。架构文档画出 FailureReport→ContextBundle→AgentStatus/Tools→Policy→Review→Verifier→Feedback；CI 命令使用 `pytest -p no:cacheprovider --basetemp .\tmp\pytest-ci`，不读取 `DEEPSEEK_API_KEY`。

- [ ] **Step 5: 运行全部离线质量门禁**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-final --cov=pyrepair --cov-report=term-missing`

Expected: 所有非 live 测试 PASS，覆盖率不低于 91%。

Run: `.\.venv\Scripts\python.exe -m ruff check src tests benchmarks`

Expected: `All checks passed!`

- [ ] **Step 6: 提交代码和文档，不包含实验结果**

```powershell
git add .gitignore benchmarks/benchmark_evaluation.py benchmarks/run_benchmark.py benchmarks/results/public/.gitkeep tests/test_benchmark_runner.py README.md docs/context-harness-architecture.md docs/benchmark-results.md .github/workflows/ci.yml
git commit -m "docs: document context harness evaluation workflow"
```

- [ ] **Step 7: 运行四组单次全量实验**

```powershell
.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --model deepseek-v4-flash --arm control --repeat 1 --publish-results
.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --model deepseek-v4-flash --arm context --repeat 1 --publish-results
.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --model deepseek-v4-flash --arm state --repeat 1 --publish-results
.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --model deepseek-v4-flash --arm full --repeat 1 --publish-results
```

Expected: 每个 raw/public JSONL 含 30 个终态 run key；技术 error 使用命令打印的精确 raw 路径配合 `--resume` 重试，不把 error 计为修复失败。

- [ ] **Step 8: 对 context/full 重复三次**

```powershell
.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --model deepseek-v4-flash --arm context --repeat 3 --publish-results
.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --model deepseek-v4-flash --arm full --repeat 3 --publish-results
```

Expected: 两个 public 文件分别有 90 条记录，脚本在写入前验证同一 fingerprint；禁止用通配符选择历史 raw 文件。

- [ ] **Step 9: 生成报告并提交公开结果**

```powershell
.\.venv\Scripts\python.exe benchmarks/run_benchmark.py --report benchmarks/results/public
git add benchmarks/results/public docs/benchmark-results.md
git commit -m "docs: publish PyRepair harness ablation results"
```

Expected: 报告包含每组样本量、成功率、首轮成功率、工具数、Token、上下文字符、LoopGuard、失败归因和局限；不得只报告最优 run。
