# PyRepair Evaluation v2 使用指南

本轮交付：独立验收、18 个开发任务包、重复试验与严格续跑。**不包含真实开源缺陷、Docker、冻结 holdout 或新的模型效果结论。**

## 1. 为什么保留两套评测

v1 的历史 15/15 是原修复链路在固定人工样例上的单次结果，没有外部隐藏验收。v2 增加了公开合同和独立验收，输入与评分协议不同，不应直接把两套成功率作效果提升比较。旧入口、原始题目、历史 JSONL 和 `docs/benchmark-results.md` 均保留。

## 2. 一次 trial 怎么运行

```text
任务包预检：buggy 失败 / gold 全过 / wrong 可见过但隐藏失败
    ↓ 只有合格任务进入实验
公开模板 + TASK.md → 新 Agent 输入副本
    ↓ 原 coordinator：最多 3 attempt，每 attempt 最多 8 工具调用
永久记录 report.json / trace.jsonl / pytest.log / fix.patch
    ↓ 不复制 Agent 的工作目录
原始模板 → 全新 grader 副本 → 校验补丁格式、路径和原 Policy
    ↓ 可见测试确实执行且全过
安装隐藏测试 → 隐藏与回归断言确实执行且全过
    ↓
写 grade.json → trial 终态追加 trials.jsonl → report.md
```

**trial** 是一次从头启动的完整实验，**attempt** 是这个实验内的一次修复尝试，**turn** 是 attempt 内的一轮模型回复。

公开合同会通过评测适配器进入初始上下文，并保留原 16k 字符预算；不改双层循环。只有公开文件能被正常工具读取。隐藏失败不会传给下一次 trial。

## 3. 环境和命令

要求 Python 3.11+、Git、项目 dev 依赖（`python -m pip install -e ".[dev]"`）。请在当前 checkout 的根目录执行。普通 Windows 环境直接使用以下命令，无须调整系统权限：

```powershell
python benchmarks/run_evaluation.py validate
python benchmarks/run_evaluation.py validate --case multi_orders
python benchmarks/run_evaluation.py grade --case case_04 --patch path/to/fix.patch
```

这三个命令不调用模型、不需要 API Key。validate 的日志目录会显示在终端；`validation-summary.json` 明确标注这是题目验证，不是模型评测。

只有以下命令调用付费模型，先确认密钥已在当前终端可用：

```powershell
python benchmarks/run_evaluation.py run --case case_04 --trials 1 --model deepseek-v4-flash
python benchmarks/run_evaluation.py run --trials 3 --model deepseek-v4-flash
python benchmarks/run_evaluation.py run --resume path/to/experiment
python benchmarks/run_evaluation.py report --experiment path/to/experiment
```

默认 1 trial，正式看重复稳定性时显式选 3。全部 18 题 × 3 trial = 54 次完整 Agent 运行，不是 54 次 API 调用。每次可能含多个 repair/review 请求。不要仅为重试失败而覆盖旧实验。

所有生成命令可通过 `--output` 指定一个**不存在**的目录；已存在时拒绝覆盖。自定义任务用 `--manifest path/to/manifest_v2.json`，续跑自定义任务时仍需指定该 manifest。

运行时提示缺少密钥会在创建实验、发请求之前退出。`validate`/`grade`：0 为通过、1 为不合格/验收失败、2 为配置或基础设施错误。`run` 返回 0 只表示调度结束，不能当作每题成功；看报告里的总体通过列。配置/执行器错误返回 2。

## 4. 看哪些文件

默认目录为 `benchmarks/results/v2/<类型-时间-随机ID>/`，内部 `experiment.json` 另有不可变 experiment_id。

```text
experiment.json                 配置、预算、任务/源码/环境指纹
validation/<case>/              buggy、reference、mutant 三套预检证据
trials.jsonl                    started / agent_finished / trial_finished 追加事件
trials/<case>/<trial>/execution-<n>/
  agent/worker.log
  agent/agent-result.json
  agent/.pyrepair/runs/evaluation/
    report.json  trace.jsonl  pytest.log  fix.patch
  grade-<id>/
    visible.log  visible.probe.json
    hidden.log   hidden.probe.json
    grade.json
summary.json
report.md
```

没有进入某阶段就没有相应阶段日志。单独 `grade` 是补丁诊断，不能作为正式模型 trial 混入统计。

## 5. 指标如何解释

最终成功 = Agent 状态 success **并且**独立 grader passed。错误、超时、没有补丁均保留在分母中。尚有 pending 时只报告完成部分成功率，最终成功率为 N/A。

| 指标 | 含义 |
| --- | --- |
| 完成度 C/N | 已终结 trial / 原计划 trial |
| 当前通过率 S/C | 只描述已结束部分，有 pending 时不是最终成绩 |
| 最终通过率 S/N | 仅全部 trial 结束时可称最终 |
| 首 attempt 通过率 | 总体通过且 attempt_count=1 / 已终结 trial |
| 全部 trial 成功题数 | 同一题的指定重复次数均完成且通过；单次不声称重复稳定 |
| Agent 误报 | Agent success、grader 可判定失败；环境和 grader 错误单列 |
| Token 已知数 | 日志可确认的下界；中断/API 异常可能缺失，不能把未知记成零 |

Repair 与 Review 的 Token 分开。原运行时没有记录到的中断请求成本无法凭空补齐。模型/工具调用计数也以已保存的证据为准。

## 6. 续跑与中断

- 检查模型、trial 数、预算、源码内容（含未提交更改）、Python/依赖、任务及私有资产指纹，任一改变就应新建实验。
- 已终结的成功、失败、错误均跳过；不以“最后成功一次”覆盖失败。
- Agent 完成证据已落盘但验收中断：只重做验收，保留此前部分 grader 目录。
- Agent 未完成：新增 execution 编号，保留旧执行证据和未知成本标记。
- 每个实验有 writer.lock 防止并发写入。进程强制结束可能残留锁；确认没有活动评测进程后才可手动删除该实验的锁文件。损坏的 JSONL 不会自动截断或忽略。
- 已写证据可用 `report` 离线重新汇总，不请求模型。

## 7. 数据集与安全边界

`manifest_v2.json` 中原 15 题为 regression/dev，新增 3 题为 capability/dev，全部 synthetic。`eval_private` 是“对 Agent 输入隐藏”，**不是 GitHub 私有目录**。仓库公开后模型可能接触过资产，因此不能称真正未见集。

每个任务都有 F2P（修复前失败、修复后通过）和 P2P（原本通过、不能回归）的 node id。探针记录采集、setup/call/teardown；缺失、空采集、skip、xfail、超时均不算通过。参考补丁只验证任务质量，不要求候选逐字相同。

第一阶段仅支持已有白名单 .py/.pyi 的普通 unified diff。禁止测试/配置修改、重命名、新建/删除、符号链接、二进制和文件模式修改；继承最多 3 文件、80 行增删规则。临时源码副本统一文本换行以兼容 Windows，原题字节不变。

grader 环境不带 API Key，并检查执行前后文件哈希。但同一用户下执行 Python **不是安全沙盒**；当前只运行审核过的自建任务。不要接入不可信代码或把此模式描述为抗恶意执行。后续真实缺陷需要容器、固定依赖与来源许可审核。

## 8. 源码阅读顺序

`run_evaluation.py → cases.py → grading.py → experiment.py → reporting.py`。

补充看 `patching.py` 的补丁拒绝边界、`pytest_probe.py` 的全阶段证据、`agent_worker.py` 的原引擎装配适配。`src/pyrepair/` 的双层循环未改动。
