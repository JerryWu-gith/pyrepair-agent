# Evaluation v2 单题真实运行记录

日期：2026-10-15。范围：`case_04` × 1 trial。用途是确认真实模型、补丁产出与独立验收之间的端到端链路；**不是全数据集评测，也不是重复稳定性评测**。

后续进展：已另建实验完成 [18 题各 1 次的实跑](evaluation-v2-first-full-run.md)。本文保留单题验证当时的结果，不把它混入后续实验统计；下文的“下一步”描述的是当时的状态。

## 运行前修正

- 官方 `/models` 接口鉴权成功，并返回 `deepseek-flash` 与 `deepseek-v4-pro`。
- 本次把 `deepseek-flash` 加入模型白名单，更新 v2 评测入口默认模型和示例命令；不改 Agent 循环、提示词、工具预算、补丁规则与验收标准。
- 旧 CLI / v1 runner 的默认值保持不变；使用当前 Flash 接口时显式传入 `--model deepseek-flash`。
- 新增 5 项离线回归测试，先观察到 5 项预期失败，再修正；配置、客户端、CLI 和新增用例共 24 项通过。
- 修正后全量离线回归：**293 passed, 1 deselected**，148.62 秒；排除了 live 测试。本次修改涉及的 Python 文件通过 Ruff，`git diff --check` 通过。
- 密钥保存在本机 Windows 用户环境变量，不写入代码、实验配置或本文。

## 本次实验

实验 ID：`928e1df5191c41238a38286269ef8d15`。

```powershell
python benchmarks/run_evaluation.py run --case case_04 --trials 1 --model deepseek-flash
```

本次实际执行另使用 `--output` 指定独立的新目录：

`benchmarks/results/v2/live-smoke-flash-case04-20261015-572a70c0/`

其中 `experiment.json` 保存模型、预算、任务、源码和环境指纹；`trials.jsonl` 保存本次终态。此目录按项目规则被 Git 忽略，原始证据目前只在本地，不应把该路径当作 GitHub 上可下载的产物。

| 项目 | 观察结果 |
| --- | --- |
| 任务 | 分页有效范围的上边界错误，synthetic / regression / dev |
| Agent 状态 | success |
| 修复次数 | 1 attempt |
| 独立 grader 状态 | passed |
| 可见测试 | 2 passed |
| 隐藏测试 | 2 passed |
| 修改文件 | 仅 `src/pagination.py` |
| 工具调用 | 5 次 |
| 模型调用 | Repair 4 次，Review 1 次 |
| Agent 执行耗时 | 15.74 秒 |
| 独立验收耗时 | 1.01 秒 |

耗时不含任务预检和整个命令启动开销。补丁把 `1 <= page < total_pages` 改为 `1 <= page <= total_pages`；没有修改测试文件。

### 返回的 Token 用量

| 角色 | 输入 | 输出 | 合计 |
| --- | ---: | ---: | ---: |
| Repair | 8,342 | 460 | 8,802 |
| Review | 335 | 461 | 796 |
| 总计 | 8,677 | 921 | 9,598 |

本次完成轨迹的 usage 覆盖完整。这里统计 API 返回的 Token，不按猜测单价换算费用，也不包含之前错误实验中无法确认的用量。

## 原始证据怎么读

- `report.md` / `summary.json`：本次单题实验的结果与用量。
- `trials/case_04/1/execution-1/agent/.pyrepair/runs/evaluation/report.json`：策略检查、Review、目标测试与全量回归。
- 同目录 `trace.jsonl`：4 次 Repair 与 1 次 Review 的逐次用量。
- 同目录 `fix.patch`：模型生成的候选补丁。
- `trials/case_04/1/execution-1/grade-*/grade.json` 及日志、探针：全新副本上的独立可见、隐藏测试证据。

## 错误实验仍保留

较早实验 `37dd6fa05f7249adbda456e2ea4bec1a` 使用旧模型标识，结果为 `Agent error / grader not_run`，原因记录为 `deepseek_error`，Token 用量未知。之后的只读鉴权检查曾返回 401。其目录 `live-smoke-case04-20261015-3639d20d/` 保留，不覆盖、不删除，也不把它改写为成功。

更新凭据与模型标识后新建了本次实验。两个实验身份不同，不合并成重复稳定性统计。

## 结论边界和下一步

可以说：**v2 已在一道人为构造的开发任务上完成真实模型调用、候选补丁生成与独立隐藏验收。**

不能说：18 题全部通过、重复运行稳定、真实开源缺陷成功率提升、SWE-bench 官方成绩或安全沙盒已完成。

后续可先评测包含 3 个多文件任务的全部 18 题，再在预算明确后做每题 3 次独立 trial；尚未执行这些批量付费实验。本次没有合并 main、推送 GitHub 或创建 PR。
