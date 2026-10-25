# 两道真实开源缺陷：离线校准报告

日期：2026-10-22。结论：more-itertools revision 1 与 boltons revision 2 均通过实际 Docker 校准（2/2 valid）。**这是任务包与独立评分器的验收，不是 Agent 修复率；本轮模型请求为 0。**

## 1. 校准矩阵

| 固定真实缺陷 | 缺陷原版 | gold 参考补丁 | 人工 wrong 补丁 | 校准 |
| --- | --- | --- | --- | --- |
| more-itertools / seekable r1 | 770 个主测试节点：4 个预期业务断言失败，766 通过 | 公开 766 + 隐藏 4 全通过 | 公开通过；隐藏 falsey 元素保留断言失败，其余 3 通过 | valid |
| boltons / addlist r2 | 161 个主测试节点：4 个预期业务断言失败，157 通过 | 公开 157 + 隐藏 4 全通过 | 公开通过；隐藏“已有 key 追加生成器”断言失败，其余 3 通过 | valid |

more-itertools 的 unittest 子测试结果另外保存在 probe 的 `subtests`，不能把它们当成额外独立缺陷或 trial。全部指定 F2P 在 baseline 中以 AssertionError 失败，指定 P2P 保持通过；两个 gold 的独立公开、隐藏验收均通过；两个 wrong 均被隐藏业务断言拒绝。两题 `system_error=false`。

校准入口：`benchmarks/run_evaluation.py validate`，清单 `benchmarks/manifest_opensource_v2.json`。实际返回 0，汇总 `candidate_tasks=2, valid=2, invalid=[]`。

## 2. 可核验证据

以下原始目录位于 evaluation-v2 工作区内，按规则忽略、不在 GitHub 发布；不要覆盖旧目录。

- 最终校准：`benchmarks/results/opensource/validation-v2-20261022-e14d6e81/`；每题 `validation.json`、reference/mutant 的 `grade.json` 和各阶段 `.docker/` 目录。
- 修复后环境：`benchmarks/results/opensource/environment-subtests-20261022-503bf74c/`；包含 `preparation.json`、`environment-lock.json`、`environment-check.json`、官方元数据、版本探针、安全/超时阶段。
- 首次失败校准保留：`benchmarks/results/opensource/validation-v1-20261022-aa3df89a/`，两题均 invalid，不拼入最终结果。
- 最终清单 SHA-256：`3c84510a5255bb51ecec3671302376c7f3d289c130a312c1ec8bcb6597914f83`。
- more-itertools 任务指纹：`756aed0bdfe07d906ec2759375c5fdd58e00147da4a4e73aa7701fff30f9da7e`。
- boltons r2 任务指纹：`bdb632a776ca7d91f222855bfff24cb12cc40edbeb3c52ca6480c35e476d4446`。

固定基础镜像：`docker.io/library/python@sha256:a7cb177dc60dfa77b223192cd0d9e6ce1aac7cf9a569023d68e7c91b6371a718`。

实际本地评测镜像：`sha256:0951c20dce645dc80c68a6e09af229be762611201891016f9aa00f4d215fd32e`，Python 3.13.5 / pytest 9.1.1，依赖 wheel 哈希和可信执行文件摘要记录在锁中。锁只适用于当前文件、profile 和已验证环境；不能手改旧锁来接受新的 harness。

实际执行了 10 个校准阶段、10 个不同容器；每阶段完整性不变，清理错误为 0。4 个公开验收阶段的输入均不含 `hidden_tests` 目录。全部执行使用同一已核验后端，不退回宿主。

## 3. 环境与工程验证

- 自有真实探针：非 root、只读根/输入、无密钥哨兵、禁外网、loopback 可用、Seccomp 2、资源设置核对，以及已启动容器超时后停止/删除，全部通过。
- 修复后镜像显式 Docker 集成：1 passed（3.30 秒）；不是默认 deselected。
- 最终普通离线回归：684 passed、2 deselected（253.81 秒，exit 0）；XML 为 684 tests / 0 failures / 0 errors。两项未运行项不算真实 API 或 Docker 通过。
- 4,130 个受保护旧文件摘要无差异；v1 清单及两题公开/私有资产的 164 个文件在追加 r2 前后无变化。
- 历史 54 次合成任务报告只在新副本中重建，summary 与 Markdown 均与原文件逐字节一致；没有把旧成绩换成新协议成绩。
- Ruff 对评测执行代码等 25 文件检查通过；本轮相关 9 文件格式检查通过。扩大格式检查时，两个未改动的历史文件 `agent_worker.py`、`review_fixtures.py` 存在格式差异，未顺带修改。

## 4. 为什么保留第一次失败

more-itertools 首次 gold 的 pytest 日志已通过，但 pytest 9 为主测试发出的额外子测试 call 报告被误当成重复主阶段，严格协议拒绝。修复只在评测插件区分并保留子报告，再把失败/异常/跳过安全归并到主节点；没有移除重复阶段检查。先用自编小夹具观察 6 个失败反例，再通过相关 70 项检查，重建镜像/锁并重新验收；未在宿主运行上游源码。

boltons r1 的人工 wrong 只修 dictutils，而正常包导入时 urlutils 实际复用该类，因此它也通过公开与隐藏测试。不能把它继续标为错误；v1 保留为 invalid。r2 仅追加新的人工漏修候选：只对新 key 物化迭代器，已有 key 的生成器追加仍有缺陷。公开任务、隐藏测试、gold、源码与提交均不变，由已有隐藏断言抓住漏修。

完整问题与处理顺序见 [工程日志](evaluation-v2-engineering-log.md)。

## 5. 结论边界与下一步

两题都是开发者已阅读的 capability/dev 小补丁试点，不是 holdout、不是 SWE-bench，也不是复杂真实任务泛化证明。more-itertools 只覆盖选定的 pytest 文件，未执行 unittest `load_tests` 注入的全部 doctest；boltons 只覆盖 dictutils/urlutils 相关回归，不是全仓回归。gold 修改两个 boltons 文件不代表正常包路径的正确候选必然必须改两文件。

当前 Docker 后端仅用于**独立评分器**。Agent 自己的 baseline、工具测试和最终验证尚未容器化，因此真实开源任务的模型入口继续拒绝；不能仅凭评分器已容器化就启动 Agent 运行上游代码。

后续仍需：case_15 精度边界的新合成修复协议与离线校准；Agent 测试执行容器适配的具体设计/确认；公平单次生成基线与正式冻结包；单独确认预算后运行分组重复实验，再出性能/成本报告。详见 [评测收尾检查表](evaluation-completion-checklist.md)。未提交、合并、推送或创建 PR。
