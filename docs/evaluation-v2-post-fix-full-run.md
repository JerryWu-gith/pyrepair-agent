# Evaluation v2：记录器修复后的 18 题独立实跑

日期：2026-10-15。模型标识：`deepseek-flash`。范围：全部 18 个 synthetic/dev 任务，每题 1 个 trial。

后续进展：2026-10-16 已另建 [每题三次的重复实验](evaluation-v2-repeat3-run.md)，结果为 54/54。本文仍记录本次单轮实验，下文“尚未执行三次评测”指当时状态，历史结果不改写、不混合统计。

## 结果

**18/18 通过独立可见与隐藏验收（100%）；17/18 在首个 attempt 通过（94.4%）。** 本轮没有记录器错误、未验收任务、中断恢复或额外重开 trial。

| 分组 | 通过 / 总数 | 说明 |
| --- | --- | --- |
| 原有单 Bug 开发任务 | 15/15 | case_15 用了 2 个 attempt，其他均为 1 个 |
| 多文件开发任务 | 3/3 | 订单、库存、时区均修改 2 个业务模块，均在首 attempt 通过 |
| 全部任务 | 18/18 | 仅是一次开发集运行，不是真实开源缺陷成绩 |

逐一核对独立 grader 的 `grade.json` 和 pytest 探针后，确认 **32 项可见测试、37 项隐藏测试**通过；采集、setup/call/teardown 证据一致，没有把 skip/xfail 或未执行测试算成通过。Agent success 的 18 题均通过独立验收，误报观察值为 0/18，不代表未来误报风险为零。

## 实验身份与约束

- 实验 ID：`5e773511d3854e5ab141cea73f9d3a4b`。
- 本地目录：`benchmarks/results/v2/live-full18-after-recorder-fix-20261015-a8da31b6/`。
- 源码指纹：`ca9d7cf0a6c5dc7840a542e703a086c04d1da468c192c4c7193d140988d93504`。
- 运行命令：`python benchmarks/run_evaluation.py run --trials 1 --model deepseek-flash`；实际另指定上述新目录作为 `--output`。
- 18/18 任务预检有效，任务资产指纹与实验记录一致。
- 最多 3 个 attempt / trial、8 次工具调用 / attempt；未改变预算、模型提示词、补丁规则或测试标准。
- 日志共 54 条实验调度事件：每题恰好 started、agent_finished、trial_finished；所有 trial_index 和 execution_index 均为 1。
- 完成后按规范 JSON 摘要复核源码、Python、平台及依赖身份一致。运行中没有修改源码。
- 原始产物中没有发现本次所用 API Key 的精确字节匹配；没有残留 writer.lock。

新建实验是因为 [记录器离线修复](evaluation-v2-recorder-fix.md) 改变了源码指纹，不能续跑并改写旧实验的成绩。

## 耗时与 API 返回用量

| 指标 | 结果 |
| --- | ---: |
| 整个命令墙钟时间，含预检 | 431.05 秒，约 7 分 11 秒 |
| Agent 执行耗时中位数 | 15.03 秒 |
| 独立 grader 总耗时 | 16.20 秒 |
| Repair / Review 已记录模型回复 | 81 / 19 |
| 已记录工具调用 | 99 |

| 角色 | 输入 Token | 输出 Token | 合计 |
| --- | ---: | ---: | ---: |
| Repair | 192,042 | 12,799 | 204,841 |
| Review | 7,919 | 25,134 | 33,053 |
| 总计 | 199,961 | 37,933 | **237,894** |

本轮 `cost_complete=true`：完成轨迹中的 API 返回用量覆盖完整，无中断执行需要补计。这里是已记录的 Token 统计，不是服务商账单核对；不按猜测的价格换算金额，也不包含此前实验费用。

## 多文件修复证据

| 任务 | 最终修改文件 | attempt | 独立测试 |
| --- | --- | ---: | --- |
| multi_orders | src/discounts.py、src/pricing.py | 1 | 可见 1 项、隐藏 2 项通过 |
| multi_inventory | src/reservations.py、src/warehouse.py | 1 | 可见 1 项、隐藏 2 项通过 |
| multi_time | src/formatting.py、src/parsing.py | 1 | 可见 1 项、隐藏 2 项通过 |

这些是人工构造的多模块任务，不是跨大型真实仓库的缺陷修复。

## 一个真实的跨轮反馈案例：case_15

1. 任务是金额转换：原实现先 `int(float(value))` 再乘 100，丢失小数金额。
2. 第一次候选改为拆分整数和小数部分。Review 指出它对负数处理错误，而且可能静默接受部分非法输入，因此拒绝。
3. 外层保存 `review_rejected` 与具体审查意见，把它们传给第 2 个 attempt。
4. 第二次候选显式校验金额格式并处理正负号；Review 批准，目标测试、全量回归和独立可见/隐藏验收通过。

这能用于展示“修复 → 审查拒绝 → 结构化反馈 → 再修复”的实际执行，不构成 Review 提升通过率的消融证据。

边界也要保留：第二次 Review 仍提示新解析器更严格，可能影响原先接受的空白、科学计数法等格式。已有测试通过不能证明所有兼容性边界都正确；继续扩充任务合同与隐藏边界测试有价值。没有为本次成绩追加新断言或重判样例。

## 与上一轮的关系

| 实验 | 总体通过 | 技术错误 / 未验收 | 单题重复次数 |
| --- | --- | --- | ---: |
| [首次全量运行](evaluation-v2-first-full-run.md) | 15/18（83.3%） | 3 题 RecorderError / not_run | 1 |
| 本次修复后独立运行 | 18/18（100%） | 0 | 1 |

- 原来出错的 case_02、case_07、case_12 本轮都在首 attempt 通过。
- 旧实验的 **427 个文件**在本轮前后逐一校验 SHA-256，内容未改变；没有覆盖旧报告、补丁或临时文件。
- 本轮观察到记录链路完整运行，但不能断言所有 Windows 文件占用问题永远不会再发生。
- 两轮源码版本不同，不合并为“同一配置重复两次”的稳定性成绩；也不能把通过率变化直接归因为模型修复能力提升。

## 如何复核

新实验目录内：

1. `experiment.json`：模型、预算、任务与运行环境身份。
2. `summary.json`、`report.md`：总览与逐题结果。
3. `trials.jsonl`：每题唯一执行及终态。
4. `trials/<case>/1/execution-1/agent/.pyrepair/runs/evaluation/`：report.json、trace.jsonl、pytest.log、fix.patch。
5. 同执行目录下 `grade-*/`：grade.json、visible/hidden 日志和探针。

原始结果目录按 Git 规则忽略，目前只在本地。工作仍留在 evaluation-v2 独立 worktree，未合并 main、推送 GitHub 或创建 PR。

## 可以说与不能说

可以说：**在 18 个自建开发任务（含 3 个多文件任务）的一次独立评测中，18/18 通过可见与隐藏验收，17/18 首轮修复通过。**

不能说：真实开源缺陷成功率 100%、SWE-bench 官方成绩、已证明重复稳定、绝无回归，或者具备容器级安全隔离。

后续如需测稳定性，应保持源码、模型和任务不变，新建每题 3 个 trial 的实验；这会新增付费调用，尚未执行。真实开源缺陷、冻结 holdout 和消融评测仍未完成。
