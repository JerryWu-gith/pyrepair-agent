# Agent 测试容器适配：离线验收报告

日期：2026-10-22。**本阶段工程验收完成；没有新增真实模型修复成绩。** 本轮模型 API 请求为 0，真实开源任务的模型入口仍关闭。默认本地 CLI、修复提示词、双层循环和预算策略不变。

## 1. 本次补齐了什么

此前只有独立评分器在 Docker 中运行，Agent 自己的测试仍走宿主 TestRunner。本次在评测装配中注入同一个 DockerAgentTestRunner，使以下三处统一进入经验证的新容器：

1. Coordinator 的公开基线测试。
2. `run_target_test` 的原始失败 node 精确测试。
3. Verifier 的目标测试与选定公开回归测试。

模型通信、流程控制和文件读写工具仍在宿主，但不导入或执行上游 Python。每次测试使用当时工作副本的过滤快照、独立容器和可追踪证据；容器/协议/清理故障直接停止，不回退宿主。正常断言失败或有完整证据的补丁导入错误作为 TestRun 反馈。

公开描述只含版本、题目ID/revision、来源类别、公开测试文件、超时、过滤策略和初始输入摘要，不含隐藏测试、私有节点或参考答案。初始输入与后续快照统一过滤已知指令形文件、`.env*` 和缓存等；这不是对所有提示注入的免疫保证。

## 2. 实际验收结果

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| 完整离线工程回归 | 774 passed，6 deselected，274.66秒，exit0 | XML：774 tests / 0 failures / 0 errors / 0 skipped；排除 live/docker，不将排除项算通过 |
| 显式实际 Docker 集成 | 5 passed，59.69秒，exit0 | 4项新 Agent 集成＋1项既有安全集成；XML无失败/错误/跳过 |
| 新镜像环境检查 | 9/9 true | 非root、只读根/输入、凭据缺席、外网阻断/loopback可用、seccomp、inspect配置、实际超时停止 |
| Agent 执行证据 | 14个阶段、14个独立CID | 输入完整性均保持、无清理错误；已核对公开快照不含隐藏目录 |
| 同一新环境的独立评分器重校准 | 2/2 valid，10个阶段/独立CID | 两题 baseline/gold/wrong 语义保持，无完整性/清理错误 |
| 静态检查 | 24文件Ruff检查、19文件格式检查通过 | 仅检查/格式化本轮范围，不批量改写旧生产文件 |
| 旧资产保护 | 核对4,130文件，5个授权差异，未授权差异0 | 其余4,125文件保持摘要；新模块与已计划harness改动单列，不声称全部旧源码零变化 |

实际 Agent Docker 测试包括：自编断言失败→导入 SyntaxError→修复后目标/回归通过；FakeLLM 驱动真实 Coordinator、工具、Policy、Review、Verifier 导出补丁且原仓库不变；两道上游任务的公开原版与参考补丁执行。FakeLLM 的回答和用量均为夹具，不是付费模型表现。

| 上游公开执行校准 | 缺陷原版公开基线 | 参考补丁目标 | 参考补丁公开回归 |
| --- | --- | --- | --- |
| more-itertools / seekable r1 | 766节点，2失败 | 1通过 | 766通过 |
| boltons / addlist r2 | 157节点，1失败 | 1通过 | 157通过 |

上表只含 Agent 可见的选定公开集合，不是整个上游测试库，也不是包含隐藏测试的独立评分器 baseline。参考补丁由可信控制器用于离线校准，不交给模型，不计为 Agent 自主修复成功。独立评分器仍从干净缺陷版本应用候选并另行验收。

## 3. 证据位置与版本

以下环境/校准目录相对于 evaluation-v2 工作区，按 Git 规则忽略；它们是本地原始证据，不是 GitHub 下载链接：

- 最终环境：`benchmarks/results/opensource/environment-agent-v2-fixed-20261022-9e13c980/`，含 preparation、lock、check 与9项实际检查证据。
- 镜像：`sha256:5100ada08d532bb34b324a27f0981ba1572a83e5790490f36777139909829e21`。
- 环境锁SHA256：`919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af`。
- 固定基础镜像：`docker.io/library/python@sha256:a7cb177dc60dfa77b223192cd0d9e6ce1aac7cf9a569023d68e7c91b6371a718`；Python3.13.5、pytest9.1.1及哈希锁定依赖。
- 新环境独立校准：`benchmarks/results/opensource/av2-20261022-e57c894b/`，汇总2/2 valid，各题validation与reference/mutant分阶段证据。
- 两题指纹未变：more r1=`756aed0bdfe07d906ec2759375c5fdd58e00147da4a4e73aa7701fff30f9da7e`；boltons r2=`bdb632a776ca7d91f222855bfff24cb12cc40edbeb3c52ca6480c35e476d4446`。

本机测试根目录：`D:/Project/PyRepair Agent/tmp/agent-adapter-9073493777ce46ae849e5c5bf02edd78/`。

- `full-regression.xml`：最终774项离线回归。
- `real-docker-v2.xml`：最终5项实际Docker集成。
- `pytest-of-Jerry/pytest-27/`：最终实际Docker集成的逐阶段原始证据。后续完整回归产生了更新的临时目录，不能凭“最新目录”替代本次证据。
- 每次 `test-*/adapter-result.json` 给出精确 `docker_artifacts`，后者含请求、probe、integrity、容器状态及supervisor结果；`selection.json`保存过滤清单、公开输入摘要与测试选择。

第一次环境 `environment-agent-v2-20261022-853293aa/`、`real-docker.xml`及`pytest-22/`保留。该次3通过/2失败，只是历史排错记录，不混入最终通过结果，也不复用其旧锁验证已变更的可信协议。

## 4. 遇到的问题与解决办法

| 问题 | 已验证原因与处理 | 保留边界 |
| --- | --- | --- |
| pytest9 子测试异常类型丢失 | 终端格式化会改写父report；提前在hookwrapper记录原report，再合并同node/phase诊断 | 不靠汇总文案猜测成功或异常类型 |
| 部分模块收集失败被误判协议故障 | 其他已收集节点可尚未运行；仅在真实collection错误下允许完全空phase | 部分phase、伪造/矛盾证据仍拒绝 |
| `.envrc`等遗漏过滤 | 统一过滤任意`.env`前缀路径分量，补反例测试 | 不读取/输出真实凭据 |
| 精确node的SyntaxError返回4 | 实际probe证明pytest在无法导入所选node时返回4；只在目标文件真实collection失败且诊断完整时返回普通失败 | 普通missing-node/usage仍fatal；grader v1不放宽 |
| Windows暂存路径过长 | more的嵌套文档目标265字符且LongPathsEnabled=0；缩短阶段名/日志名，并记录完整证据位置 | 不改系统设置、不删除任务文件；任意深输出目录仍可能超限 |
| 工具崩溃后最新模型用量丢失 | coordinator尚未来得及落turn；评测包装器在响应返回后立即刷盘独立台账 | 与trace替代核对，不重复相加；ModelClient调用数不冒充含HTTP重试的传输请求数，未知用量不写0 |

上述修复均先用自编反例记录RED，再针对性GREEN。一次集中独立审查发现的2项问题及随后实际Docker修复均经限定复审；无待解决的具体审查问题。过程见[工程日志步骤44–45](evaluation-v2-engineering-log.md)。

## 5. 对应源码

| 位置 | 责任 |
| --- | --- |
| `src/pyrepair/testing.py`、`cli.py` | TestExecutor与可选装配注入；coordinator/tools/verifier仅相应类型调整 |
| `benchmarks/evaluation/agent_input.py` | 公开描述、初始摘要验证、过滤快照 |
| `agent_container_protocol.py`、`agent_pytest_capture.py` | 独立Agent v2协议、精确node与结构化诊断 |
| `agent_test_runner.py` | 验证环境、每次新快照/容器、转TestRun、基础设施错误终止 |
| `agent_worker.py`、`agent_usage.py` | 评测装配、模型响应即时用量台账与完整trace核对 |
| `docker_runner.py`、`docker_environment.py`、`container_entry.py`及Dockerfile | 受控执行、可信文件白名单/摘要、显式协议分派；独立grader v1保持严格 |

## 6. 尚未完成的事

1. 公平single-shot基线及冻结运行包：固定公开输入、评分器、版本与预算差异；先离线验收。
2. 单独确认新请求/费用边界，再运行分组重复实验。18道合成题＋2道真实题各3次是60次修复运行，不是60次API请求；single-shot基线另计，提供方内部重试也需计入边界。
3. 用真实产物生成成功率、逐题稳定性、误报成功、错误类别及Repair/Review耗时/用量报告；历史54/54单列，不能替代新协议成绩。

仍不支持把“初始只有收集错误且没有可执行失败node”的项目作为通用修复起点。两道真实题是已读开发集，不是holdout；当前验收仅覆盖本机Windows Docker Desktop/Linux容器环境，不是跨平台或恶意宿主安全证明。普通CLI没有新增Docker开关，真实开源模型入口不提前放开，工作区不提交/合并/推送/PR。
