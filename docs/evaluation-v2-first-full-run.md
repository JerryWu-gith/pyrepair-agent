# Evaluation v2 首次全量开发集实跑

日期：2026-10-15。模型标识：`deepseek-flash`。范围：18 个开发任务，每题 1 个独立 trial；未续跑、未为失败任务追加新 trial。

后续工程进展：已完成 [Windows 记录器离线修复](evaluation-v2-recorder-fix.md)，并新建 [修复后的独立全量实验](evaluation-v2-post-fix-full-run.md)，该次结果为 18/18。本文 15/18 的历史结果、当时证据和下文当时的下一步建议保持不变。

## 结论

**15/18 通过独立可见与隐藏验收，整体通过率 83.3%。另 3 题发生运行记录器错误，未进入独立验收；错误保留在分母，不能剔除后宣称 100%。**

| 分组 | 通过 / 总数 | 说明 |
| --- | --- | --- |
| 原有单 Bug 开发任务 | 12/15 | case_02、case_07、case_12 发生 RecorderError |
| 新增多文件开发任务 | 3/3 | 订单、库存、时区任务均实际修改 2 个业务文件 |
| 总计 | 15/18（83.3%） | 全部为 synthetic/dev，不是真实开源缺陷或冻结 holdout |

14/18 在首个 attempt 通过；`multi_time` 在第 2 个 attempt 通过。这里的 attempt 是同一个 trial 内的修复重试，不是额外重复评测。

## 实验身份与执行条件

- 实验 ID：`f71e2a4778134094a4b0b1869a36551c`。
- 本地目录：`benchmarks/results/v2/live-full18-flash-20261015-c709d975/`。
- 运行命令：`python benchmarks/run_evaluation.py run --trials 1 --model deepseek-flash`；实际执行额外指定上述新目录作为 `--output`。
- 预算：每 trial 最多 3 个 attempt，每 attempt 最多 8 次工具调用；没有中途扩大预算。
- 18/18 任务预检有效；buggy、gold、wrong patch 的可见/隐藏检查全部按原协议执行。
- 本轮源码与配置保持不变。结束后按规范 JSON 指纹复核，源码、Python、平台及依赖身份一致。
- 与此前单题冒烟和鉴权失败实验分开统计，不覆盖任何历史记录。

## 耗时和可确认用量

| 指标 | 数值 |
| --- | ---: |
| 整个命令墙钟时间（含预检） | 359.44 秒，约 6 分钟 |
| Agent 执行耗时中位数（含错误任务） | 12.72 秒 |
| 独立 grader 总耗时 | 14.20 秒 |
| 已记录模型回复数 | Repair 74，Review 17 |
| 已记录工具调用数 | 91 |
| Repair 已知输入 / 输出 Token | 175,893 / 10,955 |
| Review 已知输入 / 输出 Token | 7,436 / 15,051 |
| 已知 Token 合计 | **209,335（下界，不是精确总消耗）** |

3 个记录器错误导致部分模型回复或使用量未完整落盘，因此 `cost_complete=false`，完整 Token 总量未知。不能把缺失计为零，也不能据此计算精确人民币/美元费用。

## 多文件任务证据

| 任务 | 实际改动的业务文件 | 最终 attempt | 独立验收 |
| --- | --- | ---: | --- |
| multi_orders | src/discounts.py、src/pricing.py | 1 | 可见 1 项、隐藏 2 项通过 |
| multi_inventory | src/reservations.py、src/warehouse.py | 1 | 可见 1 项、隐藏 2 项通过 |
| multi_time | src/formatting.py、src/parsing.py | 2 | 可见 1 项、隐藏 2 项通过 |

### 可用于讲解的真实循环：multi_time

1. 第一次候选修复了带时区输入的 UTC 转换和输出后缀，但 Review 指出：对不带时区的时间直接调用 `astimezone` 会使用本机时区，改变原来“按 UTC 解释”的行为；格式化函数还可能把非 UTC 值直接标为 UTC。
2. 外层将 `review_rejected` 和具体风险作为结构化反馈传入下一次 attempt。
3. 第二次候选区分有/无时区输入，并在格式化前归一化到 UTC。
4. Review 批准，目标测试、全量回归、独立可见与隐藏验收均通过。

这是本轮“Review 拒绝 → 跨轮反馈 → 再修复 → 独立验收”的真实证据，不是手写演示轨迹。它证明该次运行中这条反馈链路发生并生效，不构成 Review 效果提升的消融结论。

## 三个错误任务：确认了什么，尚未确认什么

| 任务 | 最后可见阶段 | 错误证据 | 验收状态 |
| --- | --- | --- | --- |
| case_02 | attempt:1 | worker.log 记录 RecorderError；残留 trace.jsonl.tmp | not_run |
| case_07 | verify | worker.log 记录 RecorderError；残留 pytest.log.tmp | not_run |
| case_12 | attempt:1 | worker.log 记录 RecorderError；残留 trace.jsonl.tmp | not_run |

已确认：原 `RunRecorder._atomic_write` 写运行产物时发生错误。这三题不是“独立隐藏测试判定补丁错误”，也不能假定补丁已经正确。

尚未确认：具体底层 OSError、Windows 错误码及占用方。当前 worker 日志只保留异常类型，无法仅凭 `.tmp` 文件断言一定是杀毒软件、权限或文件占用。暂不把这些推测写成根因。

原始 `report.json` 未完成、`fix.patch` 为空的证据均保留；未把临时文件覆盖回正式日志，未修改原成绩，也没有为追求通过率重新请求模型。

建议下一步先在离线环境定位记录器原子写入失败，并补充脱敏错误详情和相应回归测试。修复后另建实验验证；保留本次 15/18 的历史结果。每题 3 次重复评测仍未执行。

## 证据核验与阅读顺序

1. 根目录 `report.md` / `summary.json`：18 个终态 trial，15 passed、3 not_run。
2. `trials.jsonl`：确认每题只有 trial_index=1、execution_index=1，无重复执行。
3. 每题 `agent/.pyrepair/runs/evaluation/`：report.json、trace.jsonl、pytest.log、fix.patch。
4. 每题 `grade-*/grade.json`、visible/hidden 日志及 probe：独立验收证据。

本轮对 15 个成功任务逐一交叉核对了 grade.json 和测试探针：合计 **27 项可见测试、30 项隐藏测试**通过，没有将 skip/xfail 当作通过。Agent success 的 15 题均通过独立 grader，本轮误报观察值为 0/15；仅限这批样例，不能推出误报风险为零。

原始结果目录按项目规则被 Git 忽略，目前仅在本地。未修改 main、未推送 GitHub、未创建 PR。所有结论仅针对本次人工开发集单轮运行，不与 v1 历史 15/15 直接比较，也不声称真实项目泛化或重复稳定性。
