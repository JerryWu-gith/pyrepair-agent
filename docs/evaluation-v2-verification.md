# Evaluation v2 第一阶段验收记录

日期：2026-10-15。基于 `28f472c` 的独立托管 worktree；本文记录工程验证，不是模型评测成绩。

## 已完成

| 项目 | 证据 |
| --- | --- |
| 全量离线测试 | **288 passed, 1 deselected**，138.57 秒；live 未执行 |
| 原项目回归基线 | 升级前 227 passed, 1 deselected；原业务源码未改 |
| 任务包预检 | **18/18 valid**；15 个 regression/dev + 3 个 capability/dev，均为 synthetic |
| 参考修复 | 所有题通过可见 + 隐藏验收；3 个多文件参考补丁均修改至少两个业务模块 |
| 错误补丁 | 所有题均存在通过可见测试、被隐藏测试拒绝的过拟合补丁 |
| 运行器静态检查 | 新增 evaluation 模块、CLI 及测试通过 Ruff；任务素材为故意含缺陷的输入 fixture，不作为该次 Ruff 检查范围 |
| 旧命令兼容 | `benchmarks/run_benchmark.py --help` 正常 |
| 只读代码审查 | 已修复全部 Important 项；最终复审无 Critical/Important 遗留 |

测试采用 Python 3.13.5 与已有项目虚拟环境。当前受限宿主需要专用临时目录：测试进程的 TEMP/TMP/PYTEST_DEBUG_TEMPROOT 指向新建目录，PYTEST_ADDOPTS 固定 rootdir，PYTHONPATH 优先使用当前 worktree；未改用户级环境变量、所有权或系统权限。

## 重点回归覆盖

- 非法补丁、保护路径、重命名、二进制、不能应用的上下文在测试前拒绝。
- 空补丁、空采集、缺失 node、skip/xfail、候选导入错误、超时、运行时文件篡改均不能算通过。
- grader 子进程不继承模型 Key，原始模板字节不被修改。
- 一题三个 trial 的成功、隐藏失败、模型错误均保留；续跑不会覆盖终态。
- Agent 完成后验收中断，不重复执行 Agent；仅原始 report/patch/trace 完成而摘要未写入，也可以恢复。
- 不完整 Agent 执行保留历史并增加 execution_index；报告展示 pending 的已知成本下界，而非精确零成本。
- 原客户端将缺失 usage 映射为 0/0 时保守标为未知；API 异常原始记录恢复为 error/未知成本。
- 配置、任务资产、源码（包括内部 pytest 插件）、环境指纹变化拒绝混合续跑。
- 缺失候选产物记录为 grader_error；显式 `--trials 0` 在执行器前拒绝。
- 真实 worker/coordinator 装配离线测试只替换模型客户端，实际生成补丁并通过独立 grader；原输入未被改动。

## 本地证据

完整逐题 baseline/reference/mutant 日志保存在 worktree 的：

`benchmarks/results/v2/offline-validation-20261015/`

`validation-summary.json` 记录 candidate_tasks=18、valid=18、invalid=[]。生成产物按设计忽略，不提交到 Git；可用 `python benchmarks/run_evaluation.py validate` 重新生成。源码与测试已足够重现这些离线检查。

## 尚未完成、不能声称的成果

- 未调用付费模型，因此没有 v2 模型通过率、稳定性或成本成绩。
- 未接入真实开源缺陷、Docker、冻结 holdout 或消融实验。
- 本地复制目录不是操作系统安全沙盒；只适用于审核过的可信自建任务。
- 隐藏资产不进入 Agent 输入，不代表公开模型从未见过这些资产。
- 未合并 main、未推送 GitHub。旧 v1 结果与个人材料保持不变。
