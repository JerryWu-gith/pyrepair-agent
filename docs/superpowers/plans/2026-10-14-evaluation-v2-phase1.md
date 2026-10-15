# Evaluation v2 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现独立隐藏验收、任务预检、重复试验及证据持久化，并验证 15 个旧题验收包与 3 个多文件试点。

**Architecture:** 新建 `benchmarks/evaluation/`，任务准备、补丁检查、pytest 执行、实验调度和汇总分开。旧 Agent 与旧 benchmark 原样保留；Agent worker 在单独进程中运行，grader 只使用新副本和评测方测试。参考修复只验证任务，绝不传入 Agent 输入树。

**Tech Stack:** Python 3.11+、stdlib dataclasses/JSON/hashlib/subprocess、Git apply、pytest、现有 PyRepair。

## 执行结果（2026-10-15）

任务 1–5 已实现；任务 6 的离线回归、18 题预检和独立代码审查已完成。以下步骤保留为原始计划，实际验收记录以 `docs/evaluation-v2-verification.md` 为准。采用 Inline Execution；只在最终审查使用只读 reviewer，没有委派实现。

- 全量离线回归：288 passed, 1 deselected（未运行 live）。
- 任务预检：18/18 valid，包括 15 个原题验收包与 3 个多文件人工任务。
- 审查修复：未知用量保守标记、原始完成证据恢复、pending 成本可见、API 异常恢复保持 error/未知成本；均补回归测试。
- 保持原 Agent 双层循环、v1 入口和历史结果不变；尚未合并 main 或发布 GitHub。

## Global Constraints

- 设计来源：`docs/superpowers/specs/2026-10-14-evaluation-v2-design.md`，用户已确认。
- 第一阶段不修改 `coordinator.py` / `repair_agent.py` 的双层循环，不放宽 Policy Gate，不修改现有修复 CLI 的默认行为。
- 默认 1 trial；正式重复评测显式传 `--trials 3`。每 trial 最多 3 attempt，每 attempt 最多 8 工具调用。
- 不自动运行付费模型测试、不 Push、不合并 main，不修改个人材料。
- 仅本地可信任务；不宣称目录副本为安全沙盒。真实缺陷、Docker、消融属于后续阶段。
- pytest 必需测试缺失、空采集、skip、xfail、超时、日志损坏都不能算通过。
- 保留 v1 命令、历史成绩和结果格式；新成绩另存，失败不得覆盖成成功。
- 使用当前会话 Inline Execution；不派发实现子代理。

## 工作区与验证环境

独立 worktree：由 Codex 创建的 `evaluation-v2`，基于 `28f472c`。使用原项目 `.venv/Scripts/python.exe`，进程级 `PYTHONPATH` 优先指向该 worktree 的 `src` 和根目录，避免导入主工作区源码。

测试命令使用新建的专用临时目录，TEMP、TMP、PYTEST_DEBUG_TEMPROOT 仅对该进程生效，`PYTEST_ADDOPTS=--rootdir=.`；禁用 live 测试。目录创建前检查最终绝对路径，pytest basetemp 必须未存在。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `benchmarks/evaluation/cases.py` | Case 数据、严格 manifest 验证、任务指纹、公开输入副本 |
| `benchmarks/evaluation/patching.py` | 窄格式 unified diff 校验、Git apply、原策略复验 |
| `benchmarks/evaluation/pytest_probe.py` | 评测用 pytest 插件；记录采集及所有阶段状态 |
| `benchmarks/evaluation/grading.py` | 干净环境执行、隐藏资产安装、独立评分及预检 |
| `benchmarks/evaluation/experiment.py` | 实验身份、trial 状态、严格续跑、worker 调用与产物保存 |
| `benchmarks/evaluation/agent_worker.py` | 唯一 live 入口适配；调用原 coordinator 并持久化原始证据 |
| `benchmarks/evaluation/reporting.py` | 纯函数汇总与报告 |
| `benchmarks/run_evaluation.py` | validate / grade / run / report 命令 |
| `benchmarks/manifest_v2.json` | 18 个版本化开发任务 |
| `benchmarks/eval_private/<id>/` | hidden_tests、gold.patch、wrong.patch |
| `benchmarks/eval_descriptions/<id>.md` | 公开合同（准备输入时命名 TASK.md） |
| `benchmarks/eval_cases/multi_*/` | 3 个多文件任务的源码和可见测试 |

## Task 1: 任务协议与公开输入准备

**Files:** Create `cases.py`、`__init__.py`、`tests/test_evaluation_cases.py`、`tests/evaluation_helpers.py`；Modify `pyproject.toml` 的 fixture 排除目录。

**Interfaces:** `EvaluationCase` 含设计中的任务字段及 `root: Path`；`load_cases(manifest: Path) -> list[EvaluationCase]`；`prepare_case(case, destination: Path) -> Path`；`case_fingerprint(case) -> str`。

- [ ] 写独立手工 fixture：app.py 的 `add(a,b)` 错写为减法；公开测试 `add(2,3)==5`，隐藏测试 `add(3,4)==7`；参考补丁改加法，错误补丁返回常数 5。
- [ ] 写失败测试并执行：

```python
def test_prepare_keeps_private_assets_outside_agent_tree(case, tmp_path):
    repo = prepare_case(case, tmp_path / 'agent')
    assert (repo / 'src/app.py').is_file()
    assert (repo / 'TASK.md').is_file()
    assert not (repo / 'gold.patch').exists()
    assert not list(repo.rglob('test_hidden*.py'))
```

- [ ] 验证 `../`、绝对路径、盘符、反斜杠歧义、重复编号、未知 suite/split、空测试集合、bool 型 timeout、非法 node id、符号链接被拒绝。
- [ ] 实现冻结 dataclass、显式类型校验和路径解析；对公开与私有树分开散列，忽略缓存，拒绝链接；输入复制排除 case.json/缓存/.git/.pyrepair，并附公开合同。
- [ ] 用改变隐藏断言、公开合同、源码后的哈希差异验证指纹失效。
- [ ] 执行 `pytest tests/test_evaluation_cases.py -q`，检查真实文件副作用后提交。

## Task 2: 独立补丁执行和全测试状态捕获

**Files:** Create `patching.py`、`pytest_probe.py`、`grading.py`、`tests/test_evaluation_grading.py`。

**Interfaces:** `apply_patch_checked(case, repo, patch_text) -> tuple[str,...]`，违规抛 `PatchRejected`；`run_tests(repo, paths, output, timeout) -> dict`；`grade_patch(case, patch_text, output) -> dict`。

- [ ] 先运行以下测试观察失败：

```python
def test_constant_patch_passes_visible_but_fails_hidden(case, tmp_path):
    result = grade_patch(case, case.wrong_patch.read_text(), tmp_path / 'grade')
    assert result['status'] == 'hidden_failed'
    assert result['visible']['passed'] is True
    assert result['hidden']['passed'] is False
```

- [ ] 参考补丁应为 `passed`；空补丁为 `no_patch`；测试/配置修改、路径穿越、二进制、重命名、链接以及不匹配上下文为 `patch_rejected`。
- [ ] 限定 `--- a/path` / `+++ b/path` 与标准 hunk 格式；拒绝元数据操作，用 Git `apply --check` 再 `apply`，不允许 unsafe paths；应用后重建 FileChange 并调用 PatchPolicyGate。
- [ ] pytest 插件记录 collection 和每个 node 的 setup/call/teardown，不只记录 failures。评测命令固定 rootdir、清空外部 PYTEST_ADDOPTS、关闭自动加载插件，用受控 PYTHONPATH 加载 probe，不传 API Key。
- [ ] 生成报告必须包含 session 退出码、实际 collected node 列表、phase outcomes。测试全 skip、xfail、空采集、缺失指定节点与非法 JSON 必须失败或 grader_error。
- [ ] 每个评分从原始模板新建副本，隐藏测试只在这里安装；测试与配置文件在执行前后哈希一致。
- [ ] 通过 subprocess TimeoutExpired / OSError 的边界测试验证 timeout/environment_error；真实导入失败不误记为环境故障。
- [ ] 执行 `pytest tests/test_evaluation_grading.py -q`；确认原题字节未改变，提交。

## Task 3: Gold set 预检与任务资产

**Files:** Extend `grading.py`；Create manifest、18 份公开描述、18 份私有测试/补丁包、3 个多文件任务、`tests/test_evaluation_dataset.py`。

**Interfaces:** `validate_case(case, output) -> dict`，返回 `valid` / `invalid_task`、指纹、baseline/reference/mutant 证据；仅 `valid` 允许进入模型运行。

- [ ] 用 fixture 写失败测试：buggy F2P 为真实 call failure、P2P 为 passed；gold 全部 passed；wrong 可见 passed 且隐藏 failed。
- [ ] 负向用例：参考补丁仍失败、错误补丁也全通过、基线不失败、缺少必需节点、P2P 原本失败，都为 invalid_task。
- [ ] 原 15 题保持可见源码不变。合同范围分别为：tier 默认折扣、active/admin 真值表、urgent 物流、页码上下界、非负库存量、90 分边界、缺失配置领域异常、支付超时转换且保留其他异常、ID 格式领域异常、累积购物车数量、退出登录幂等、订单状态及历史、true/false 标准文本、DD-MM-YYYY、两位小数金额精确转分。
- [ ] 每题至少写 3 个独立隐藏断言；参考实现依据合同；错误补丁对可见输入过拟合而在隐藏输入失败。隐藏合同不得要求未说明的新功能。
- [ ] 订单多文件任务：以分为整数单位，商品小计按 quantity 累加，折扣按 tier 决定；服务入口组合两模块。gold 修复小计和 vip 折扣两个模块，公开检查一个订单，隐藏检查多商品、默认 tier、零数量。
- [ ] 库存多文件任务：仓库预留/释放按数量更新；服务记录 reservation 并保证重复取消不再释放。gold 同时修复 reserve 数量和 cancel 标记，隐藏检查连续调用和不足库存无副作用。
- [ ] 时间多文件任务：ISO 带偏移输入按 UTC 归一化；输出严格 `YYYY-MM-DDTHH:MM:SSZ`。gold 修复时区换算及输出格式，隐藏检查跨日、负偏移、UTC 输入。输入保证有时区，避免添加未定义的 naive 语义。
- [ ] 预检 18 题；所有 gold 受当前 3 文件/80 行策略约束。至少两个 multi gold 必须修改两个业务模块；记录该特征而不硬编码要求候选必须模仿 gold。
- [ ] 执行 `pytest tests/test_evaluation_dataset.py -q`，保存离线验证报告（标明不是 LLM 成绩），提交。

## Task 4: 实验持久化、严格续跑和 worker

**Files:** Create `experiment.py`、`agent_worker.py`、`tests/test_evaluation_experiment.py`。

**Interfaces:** `create_experiment(cases, output, model, trials) -> Path`；`run_experiment(path, cases, agent_executor=None) -> list[dict]`；`run_agent(case, agent_dir, model) -> dict`；`load_events(path) -> list[dict]`。

- [ ] 失败测试使用仅替代付费 LLM 的 executor：在真实输入副本运行/生成原格式证据，让真实 grader 判分。

```python
def test_trials_survive_and_finished_failures_are_not_retried(case, tmp_path):
    path = create_experiment([case], tmp_path / 'exp', 'deepseek-v4-flash', 3)
    records = run_experiment(path, [case], agent_executor=scripted_agent)
    assert [r['trial_index'] for r in records] == [1, 2, 3]
    before = (path / 'trials.jsonl').read_bytes()
    run_experiment(path, [case], agent_executor=must_not_run)
    assert (path / 'trials.jsonl').read_bytes() == before
```

- [ ] 实验先写完整网格与指纹。trial 事件 append+flush+fsync，报告原子替换；全局实验锁防止两个 writer 同时运行。崩溃残留锁明确报错，不自动抢锁。
- [ ] agent worker 在独立进程通过原 build_coordinator 执行；设置 rootdir，保留现有预算。非模型诊断命令不创建 client。
- [ ] worker 的 recorder_factory 改为写入永久 agent 目录（仅装配适配，不改核心类），使进程中断仍保留已写证据；只有公开 repo 副本供 Agent 工具访问。
- [ ] 验证成功、失败、模型错误、缺失报告均有终态；Token 区分 repair/review，异常阶段可能不完整时标记未知。
- [ ] 续跑检查配置/源码/环境/任务指纹；已终结 trial 包括错误均不重跑。已写 agent 完成证据但 grader 中断时只重做 grader；不完整 agent 再启动需新的 execution_index，保留中断历史与成本。
- [ ] 真实 worker 总运行超时固定 1800 秒并写入实验配置；终止子进程树，持久保存已有日志，不判成功。只在显式 run 命令中可调用。
- [ ] 用 config mismatch、旧 v1 文件、损坏 JSONL、中断恢复和同题三个不同结果测试边界，提交。

## Task 5: 统计、CLI 与文档

**Files:** Create `reporting.py`、`run_evaluation.py`、`tests/test_evaluation_reporting.py`、`tests/test_evaluation_cli.py`、`docs/evaluation-v2.md`；Modify `.gitignore`、README。

**Interfaces:** `summarize(experiment, records) -> dict`；`render_report(experiment, records) -> str`；`main(argv=None) -> int`。

- [ ] 手算记录：计划 6、已完成 4、成功 2，则完成度 4/6、当前通过率 2/4、正式最终率尚不可用；一题 3/3 才稳定，2/2 未跑齐不能算稳定。
- [ ] 验证误报不包含 environment/grader error，未知 Token 不冒充 0，首 attempt 成功分母包含失败与错误。
- [ ] 实现 validate / grade / run / report；所有离线子命令无 API Key 可运行。run 明确告知调用真实模型，resume 从原实验配置继承且拒绝显式冲突。
- [ ] 退出码：0 表示命令成功完成且（validate/grade 时）验收成功；1 表示任务不合格/补丁被拒绝或测试失败；2 表示配置或基础设施错误。run 的模型失败仍保存完整报告并返回 0，配置/执行器故障返回 2；报告中不得混淆。
- [ ] CLI 测试实际 subprocess 执行 help、validate 单 fixture、grade gold/wrong、report 既有结果；真实 run 使用无密钥验证其先拒绝缺失凭据，不发请求。
- [ ] README 增加协议区别、离线预检示例、trial/attempt 区别和“18 题均为开发集，未完成新版 live 评测”的声明。
- [ ] `.gitignore` 只新增 v2 运行目录；不删除旧 JSONL 或个人文件。根 pytest 排除新增任务源码目录，完整测试不能意外执行故意失败的 fixture。
- [ ] 执行所有 evaluation 测试及原 benchmark/README 测试，提交。

## Task 6: 最终验证与交付

- [ ] 重新执行 18 题 validate；每题保留 buggy/gold/wrong 的真实日志。
- [ ] 运行完整离线 pytest、Ruff（只对本次新增/改动 Python 文件）及旧 benchmark `--help`。
- [ ] 检查 diff 不包含核心循环变更、旧成绩覆盖、个人材料或密钥；检索源代码危险 subprocess shell 参数与未验证删除路径。
- [ ] 按 requesting-code-review 获取最终审查；按 verification-before-completion 重新执行受修复影响的测试。
- [ ] 按 finishing-a-development-branch 报告 worktree、提交及验证事实。未收到合并或发布指令前不合并、不 Push。
- [ ] 交付命令、产物位置和已完成/未完成边界；不得把离线参考补丁验证写成模型成功率。

## 自审结果

任务 1 覆盖协议和输入隔离；任务 2 覆盖验收独立性和拒绝路径；任务 3 覆盖 18 个任务包；任务 4 覆盖重复运行、证据与续跑；任务 5 覆盖口径/CLI/兼容性；任务 6 覆盖集成验证。补丁处理和 pytest probe 从 grading 拆分是为了限制单模块复杂度，不扩展功能范围。
