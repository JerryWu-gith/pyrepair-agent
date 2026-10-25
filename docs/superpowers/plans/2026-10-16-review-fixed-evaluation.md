# Fixed Review Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 固定三题六候选，提供离线 prepare/report 与显式 live 的一次性 Review A/B 入口。

**Architecture:** fixture 准备与模型运行分开，模型输入只从公开故障、补丁、说明构建；标签只供本地评分。为控制文件规模，将设计中的评测逻辑拆为 review_fixtures.py（离线资产与验收）、review_evaluation.py（运行与持久化）、review_reporting.py（纯统计），CLI 保持薄入口。

**Tech Stack:** Python 3.11+、pytest、现有 ModelClient、独立 grader 和原子写入器，无新依赖。

**后续执行状态（2026-10-17）：** 以下离线计划已完成；用户随后另行批准的 36 次真实 Review 对照也已完成并离线复核，见[结果记录](../../review-contract-live-results.md)。本计划的“未来/待确认”描述是当时的费用边界，不代表当前还有调用待执行；没有自动追加预算或改变固定候选。

## Global Constraints

- 沿用当前 evaluation-v2 worktree、Inline Execution，不提交、不推送、不 PR、不修改 main。
- 用户已批准 case_15 人工校准正例及仅供本 Review 评测的精度边界验证；仍为 3 题、6 候选。
- 保留旧成绩和所有旧资产。case_15 历史 Decimal 候选仅作诊断反例，不是第 7 个模型评测样本。
- 不调用真实 API；未来 6 × 2 × 3 = 36 次调用仍需独立预算确认。
- 两组采用相同新提示词，只有 task_contract.content 不同。无工具、无共享历史、无参考答案/隐藏测试/标签输入。
- 请求预算不足零调用；模型客户端重试为 0；无自动续跑；已有目录拒绝覆盖。
- 输入上限 4,000 字符；旧 Repair 16,000 字符预算不变。所有模型错误及 0/0 usage 保守记未知成本。
- 每步记录 RED/GREEN 与问题；正式资产/历史产物实施前后做哈希对比。

## Task 1: 冻结候选与离线准备

**Files:** 新增 benchmarks/review_cases/{manifest.json,README.md,六份patch,diagnostics/case_15_historical.patch,precision_tests/test_money_precision.py}；新增 benchmarks/evaluation/review_fixtures.py、tests/test_review_evaluation.py；.gitignore 忽略 results/review/；pytest norecursedirs 排除 review_cases（其测试只能装入专用副本运行）。

**Interfaces:** `prepare_review(cases_manifest: Path, fixtures: Path, output: Path) -> Path`；`load_prepared(path: Path, *, check_runtime: bool = True) -> dict`；`review_runtime() -> dict`。

- [x] 先写 RED：真实应用原历史 patch 后，精度边界必须失败；人工校准 patch 必须通过；prepare 六候选标签成立，输入不含 private canary；重复输出目录拒绝；篡改输入、源码或 fixture 摘要拒绝。

```python
@pytest.mark.parametrize("precision", [2, 28, 64])
def test_exact_cents(precision):
    with localcontext() as context:
        context.prec = precision
        assert dollars_to_cents("12345678901234567890123456789.01") == 1234567890123456789012345678901
```

- [x] 跑新测试，确认未实现接口/历史精度错误而不是环境错误导致失败。
- [x] 固定补丁：case03/multi_time 正例来自历史 trial1；金额人工 patch 使用以下实现，其他反例复制已有 wrong.patch（保留源哈希与通用换行说明）。

```python
from decimal import Decimal

def dollars_to_cents(value: str) -> int:
    numerator, denominator = Decimal(value.strip()).as_integer_ratio()
    return numerator * 100 // denominator
```

- [x] prepare 在公共副本运行 visible，要求故障可复现；用 parse_text_failures/PytestParser 生成 FailureReport。新副本应用每份 patch，以规范化旧/新源码构造 FileChange/PatchSnapshot，避免 CRLF 制造假 diff。
- [x] grade_patch 独立验收正例 passed、反例 hidden_failed，且反例真实断言失败而不是收集/环境错误；金额额外复制 precision_tests 到独立副本运行，positive 必须全通过，历史 diagnostic 必须断言失败。测试前后副本树哈希一致，防候选执行中改验收文件。
- [x] 冻结 prepared.json：协议、runtime（含新 CLI/fixture/提示词摘要）、六份公开输入、单独 labels/provenance/grading 元数据，digest 覆盖整个包。只有全部准备通过才写 ready 包；失败保留诊断，不能 live。
- [x] GREEN：新测试 + 实际六候选 prepare；后续复现只依赖仓库内固定 fixture 和原任务，不依赖旧 results 路径。

## Task 2: 固定调度、输入白名单、失败停机

**Files:** 新增 benchmarks/evaluation/review_evaluation.py、benchmarks/run_review_evaluation.py；扩充 tests/test_review_evaluation.py。

**Interfaces:** `schedule(candidate_ids: list[str], repeats: int) -> list[dict]`；`run_review(prepared: Path, output: Path, *, live: bool, model: str, repeats: int, request_cap: int, client_factory=None) -> Path`；`save_json(path: Path, value: dict) -> None`。

- [x] 写 RED：6 候选 repeats3 计划36，18对中9AB/9BA；不同组请求仅说明不同；labels canary 不进入请求；live=False/cap35 时工厂零初始化；API错仅一次调用；started 写入失败零调用、响应写入失败停止下一次，留下 started；已存在输出拒绝、无续跑。

```python
orders = schedule([str(i) for i in range(6)], 3)
assert len(orders) == 36
assert sum(row["arm"] == "A" for row in orders[::2]) == 9
```

- [x] 跑 RED。实现顺序按 `(candidate_index + repeat_index) % 2`，每对相邻。验证全部输入身份及预算后才初始化 `DeepSeekClient(..., max_retries=0)`；默认 client_factory 是本地 lazy 函数，prepare/report 不调用。
- [x] 模型调用边界只接收已构造的两条消息与空工具列表，使用原 `_review_messages` / `_parse_review`，不重写生产解析规则。每个请求新建消息，不把整份 prepared 包传给客户端。
- [x] 使用 recorder._atomic_write 保存 manifest、每请求 request/started/result；请求前 started 保存成功才发；保存失败传播，停止后续调用。API错误记录类型和脱敏短消息，响应 content 脱敏保存，不记录 reasoning_content/key/headers；未知结束保留 pending。
- [x] CLI 子命令 prepare/run/report，run 的 --live、--model、--repeats、--request-cap 必须显式指定；校验在初始化前。脚本路径优先当前 checkout。
- [x] GREEN + CLI 帮助/拒绝行为测试；只使用 FakeLLM，不进行网络调用。

## Task 3: 独立分母、配对统计与验收文档

**Files:** 新增 benchmarks/evaluation/review_reporting.py；扩充 tests/test_review_evaluation.py；更新 README、工程日志、设计状态。

**Interfaces:** `summarize_review(manifest: dict, results: dict[str, dict], started: set[str]) -> dict`；`write_report(experiment: Path) -> dict`。

- [x] 写预设 RED：positive A 拒/B 过是 B_fixes_A；negative A/B 都批是 both_wrong；parse error 不算有效拒绝，API error 不剔除全计划分母；pending 区分未开始/已开始无结果；0/0 标未知，已知 tokens 仅为下界。

```python
assert summary["paired"]["b_fixes_a"] == 1
assert summary["arms"]["A"]["correct"]["denominator"] == planned_per_arm
assert summary["arms"]["A"]["false_reject"]["denominator"] == valid_positive_count
```

- [x] 跑 RED。实现 arms 的 false_reject/false_accept/correct/valid、api/parse/pending；候选组必须 repeats 个全有效才计 flips，缺失组单列；pair 双有效才比较，其他 missing。
- [x] report 仅读已保存 manifest/started/result，拒绝未知/重复请求 ID 与身份摘要不一致；不依赖当前 runtime（允许以后离线重建旧报告），结果和 started 一致性需核验。重复 report 不产生模型调用。
- [x] GREEN 后跑全量 non-live、相关 ruff、git diff --check、历史哈希对照；按 requesting-code-review 做独立只读审查并解决重要问题。
- [x] 文档解释 A 是新共同提示词控制组、样本是已知问题开发集、人工校准非模型成绩；仅报告离线工程成果。真实36次对照尚未运行，先交付并单独确认预算。

## 审查后的实施补充

只读审查 P2 已用三项 RED 复现：call-phase FileNotFoundError、缺失 required 节点、报告缺少证据不足提示。为不改变旧 grader 的默认行为，新增 keyword-only extra_plugins=() / test_runner=run_tests 注入点，并用 Review-only review_probe.py 捕获真实 AssertionError。默认 v2 执行不加载该插件，旧任务资产和旧结果不变。这是本计划标签校验的补强，不是新增评测范围；最终复验另记工程日志步骤 19。

## 自查结论

- 输入链路由前一计划覆盖；本计划覆盖固定资产、精度补充、调度/费用保护、记录、统计、文档及审查。
- 金额修正是已批准变更；候选数量、隔离边界、旧结果保留约束未变。
- 接口名与文件分工固定；测试先于实现。无需再次询问执行方式，沿用用户 Inline 偏好。
