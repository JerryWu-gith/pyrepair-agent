# 公平工作流对照：离线能力与使用说明

日期：2026-10-23。当前状态：本轮离线升级完成，**新版20题核心校准、冻结身份核对和120槽位CLI脚本模拟完成**；最终869项完整离线回归、1项显式实际Docker/FakeLLM双方法分层验收通过。没有真实模型修复成绩，不包含付费运行授权。旧准备失败和运行时间波动证据保留。

## 1. 这次增加的能力

| 能力 | 具体作用 |
| --- | --- |
| 同一初始事实 | 从公开缺陷副本的实际pytest失败构建FailureReport和ContextBundle，两组复用同一份任务、报错和代码片段 |
| 单次生成基线 | 只接受一次响应的一份普通diff或唯一diff/patch围栏；不提供工具、测试反馈或格式纠错追问 |
| 完整工作流 | 复用现有Coordinator、工具、Policy、Review和Verifier，只在评测侧装配冻结输入与额度包装 |
| 冻结包 | 固定题目/私有验收指纹、公开副本/证据、运行源码、环境、提示词、预算参数及配对顺序，漂移即拒绝 |
| 保守调用额度 | 调用前持久化预留；响应返回即落盘；各角色共用额度，评测侧关闭自动重试，普通CLI不变 |
| 恢复与判分 | 已开始槽位不自动再次调模型；有候选只继续本地判分，single-shot还可从唯一已存响应本地恢复补丁 |
| 可解释报告 | 计划分母、合成/真实分组、逐trial结果、逐题配对差异、内部成功但外部拒绝、技术错误/未运行及分角色已知/未知用量 |

公共描述/证据不含隐藏测试、隐藏节点、gold/wrong或私有目录；这些仅由可信控制器用于独立校准/验收。完整Agent后续可以通过工具获取更多公开证据，单次生成组不能。两组指令/工具输出规则不同，不能错误宣称“完全相同提示词”。

对照回答的是**整体工作流是否更有价值以及代价多少**，不是等算力比较，也不能从结果单独证明Review、上下文检索或Agent Loop某个组件的因果贡献。两道真实任务仍是已读dev，不是holdout。

## 2. 120槽位到底是什么

正式目标：18道synthetic v3＋2道真实opensource v3，每组每题3次。任务仍是20道；opensource v3中的more为r2、boltons仍为r2，合成case_15仍为r2，其他任务版本不变。

```text
20题 × 3次 × 2方法 = 120个计划槽位
  ├─ single-shot 60次，每次最多1个模型响应
  └─ full-agent 60次，每次可有多个Repair/Review响应
```

120次方法运行不等于120次API请求，不是已获批准的人民币或调用预算。`simulate`只用固定脚本结果测试这120个槽位的顺序、追加记录和报告，**不是120次模型修复，也不是120次完整FakeLLM修复链**。它的报告明确写SIMULATION / NOT real model performance，成功率为未测量。

完整FakeLLM双方法、实际Docker执行和独立公开/隐藏判分另由自编小任务集成测试验证，不与调度模拟混成性能成绩。真实预算与live入口须下一阶段单独确认。

## 3. 新命令只做离线工作

在evaluation-v2工作区运行，而不是尚未合并的main目录。命令不读取.env，也不需要API key。输出目录必须是全新目录；旧准备失败和旧报告保留。

```powershell
# 使用已有且通过安全核验的环境，不隐式构建/拉取镜像。
$lock = "benchmarks/results/opensource/environment-agent-v2-fixed-20261022-9e13c980/environment-lock.json"
$pack = "benchmarks/results/comparison/my-new-pack"

# 实际Docker公开基线＋独立baseline/gold/wrong校准，不调用模型。
python benchmarks/run_comparison.py prepare --environment-lock $lock --output $pack --model deepseek-flash --trials 3

# 核对题目、公开材料、源码、配置和环境摘要，不调用模型。
python benchmarks/run_comparison.py verify --pack $pack

# 120个脚本化调度槽位，不进行模型推理。
python benchmarks/run_comparison.py simulate --pack $pack --output benchmarks/results/comparison/my-new-simulation
```

不提供`run`、`live`或`repair`子命令。旧`run_evaluation.py`及开源live拒绝保持原状。默认选择两份新清单；指定`--manifest`可重复传入显式清单，选择在准备时固定，不能看成绩后改题/顺序。

## 4. 输出数据在哪里

| 位置 | 内容 | 是否进入模型 |
| --- | --- | --- |
| pack.json | 控制器冻结身份：源码、环境、题目/验收指纹、公开证据摘要与计划槽位 | 否 |
| p/cNN/r/ | 过滤后的公开缺陷仓库 | 是，限受控文件工具 |
| p/cNN/spec.json | 8字段公开执行描述，无隐藏验收信息 | 是，可信执行装配使用 |
| p/cNN/evidence.json | 冻结的公开FailureReport与ContextBundle | 是，两组初始事实一致 |
| control/cNN/a/ | Agent公开基线的容器证据 | 控制器保存；模型只拿结构化公开故障 |
| control/cNN/v/、calibration.json | 独立缺陷/参考/错误补丁校准；more固定3轮核心校准＋扩展基线/参考各一次，紧凑索引与原始大证据分开 | 否 |
| control/cNN/regression.json、collection.json | 扩展测试文件范围及从可信缺陷基线实际收集的完整节点名单；摘要进入包身份 | 否 |
| journal.jsonl、sNNNN/ | 每槽位阶段、候选、独立判分、响应及恢复依据 | 评分结果不回灌同次修复 |
| summary.json、report.md | 调度/分组/配对/用量报告 | 否 |

存储目录名使用短cNN/sNNNN，以降低Windows路径长度风险；完整题目ID/方法/trial仍在身份和journal中。已验证环境只能在可信harness摘要不变时复用；变更后须重新准备和安全核验，不通过改系统注册表、删除任务文件或宿主回退规避问题。

## 5. 如何理解错误与用量

- 补丁格式、规则、可见或隐藏业务测试未通过：普通方法结果，按冻结顺序继续，不追问模型。
- API/响应协议/容器/判分基础设施错误：保存证据并暂停，不选择性补跑。
- 新版核心与扩展分开记录：已安全清理的扩展阶段超时为未验证，不计通过且不抹掉核心结果；核心技术错误、OOM/清理失败或证据矛盾仍暂停。完整扩展名单必须精确匹配，少节点也不能通过。
- 中断后有候选：只恢复本地判分。single-shot有唯一已存响应也可本地解析；完整Agent没有候选的部分轨迹不能直接当成可恢复执行。
- journal终态必须与独立保存的候选/判分一致，且严格遵守全局冻结顺序；不能通过改内嵌状态“修成通过”。
- comparison v2终态只存候选和评分摘要，完整补丁保留在candidate.json；评分身份绑定patch、任务、范围及完整收集名单。原始core-grade.json/extended-regression.json各自保存并hash，防止搬用另一补丁的成绩或大日志撑爆恢复上限。
- `reserved_calls`是保守预留数；`responses`是已记录返回数。Repair/Review未知token保持unknown，同时保留已知下界；不把ModelClient预留数冒充已测HTTP重试次数或精确费用。
- 标准库绝对栈路径保留在原始诊断文本中，但不列为仓库文件工具目标。日期、金额、源码和断言字面量不被泛化替换。

## 6. 验证与剩余边界

| 当前代码验证 | 实际结果 |
| --- | --- |
| 完整离线回归 | 最终869passed、7deselected，358.98秒，exit0；XML869tests/0failures/0errors/0skipped。此前844passed保留为上一阶段检查点 |
| 相关筛选测试 | 存储修复后44passed，47.65秒；此前57项相关检查及最大候选120槽位恢复反例均通过，数量不相加 |
| 显式实际Docker双方法/独立分层验收 | 最终1passed，66.25秒；自编任务与FakeLLM，不是模型分数 |
| 静态核验 | 当前10个新增/修改代码及测试文件Ruff及格式检查通过 |
| 源码保护 | 本轮起始记录的22个生产Python文件摘要不变；174旧任务资产聚合摘要相同；4,130旧保护项仍只有此前批准的5个生产差异 |
| 集中审查 | 本轮3个Important＋最大候选日志上限问题经反例修复及限定复审；实际4MiB大证据写入另有RED/GREEN和限定审查 |

本轮XML和测试目录：`D:/Project/PyRepair Agent/tmp/layered-9c8476e9/`，最终使用`full-regression-final.xml`与`layered-docker-final.xml`。初次分层Docker检查的`layered-docker.xml`（72.74秒）是审查前检查点。上一阶段`comparison-289b72883f204ec2bc92d1a2a92afab8/`及其844项XML仍保留，不冒充当前快照结果。

两次实际20题准备均未生成可用`pack.json`：

- `D:/Project/PyRepair Agent/tmp/cp-1023-9df85faa/`：前13题有效，第14题因标准库绝对栈路径被当成仓库路径而停止。已修复，原证据不覆盖。
- `D:/Project/PyRepair Agent/tmp/cp-1023-ef535ed2/`：18道合成题均valid；more-itertools参考/错误补丁的公开阶段均真实超时，`system_error=true`；boltons在该次准备中未执行。无OOM、清理错误，不能写成20/20或模型失败。

more-itertools参考输入摘要`512f6361bc0180cdb1f121850285771cc8451ca48e61e53a6e2c1ce18f3d6d4f`、环境摘要`919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af`与此前成功校准相同。受控串行重放两次均通过，但容器存活时间分别约10.63秒和115.27秒；另有独立诊断运行及单节点检查，均不作为任务成绩。证据在`D:/Project/PyRepair Agent/tmp/cd-1023-375f6981/`、`cd-trace-1023-069254f3/`、`cd-node-1023-5a26e2d2/`。原超时日志停在多线程压力测试附近；该测试包含100线程×100,000元素，单独运行却约2.35秒通过。**尚不能把全套抖动的根因确认为这一个测试或宿主负载。**

用户随后批准[分层修订设计](superpowers/specs/2026-10-23-layered-acceptance-design.md)，现已实施：more r2核心为19个相关上游测试＋3个原公开测试＋4个原隐藏测试，共26主节点，不是新增26道任务。原r1的test_more/test_recipes/repro完整文件集保留为扩展回归；它不包含所有上游测试入口，因此不能称整个项目全库全部测试通过。

第三次准备目录`D:/Project/PyRepair Agent/tmp/lp-1023-c3103570/`中，18合成valid，more三轮核心均valid/26节点，扩展缺陷版本766节点预期失败、参考766节点全通过；但保存完整校准对象超过通用4MiB写入上限而停止，boltons未执行、无pack.json。根因经自编大证据反例验证后，改为原始控制器证据单独保存（沿用协议16MiB读写上限）、校准索引保持紧凑；模型/配额通用4MiB限制不放宽。旧目录保留，不覆盖或填成成功。

## 7. 本报告快照的冻结与模拟证据（保留历史身份）

此后新增受控入口，运行源码身份已改变；以下包与869项回归属于分层阶段的历史快照，不冒充新入口当前身份。新入口与新冻结验收另见[受控入口离线报告](controlled-live-comparison-offline.md)，旧文件和成绩不覆盖。

- 全新冻结目录：`D:/Project/PyRepair Agent/tmp/lp-1023-74d56f08/`。20/20核心任务校准valid，包含18合成＋2真实dev；more固定3轮均valid，参考核心公开/隐藏通过、wrong被隐藏拒绝。扩展实际建立766节点名单，缺陷版本预期failed，参考passed，节点严格一致。
- 批次实际132个独立容器/132份supervisor结果；独立CID132，清理错误0，environment_error/grader_error/timeout共0。这是校准执行，不是模型调用数。
- pack身份：`1d86e7989256fc497d2ded19eac70f0590cbb9a265244977c48fddf9bca2a887`；运行源码摘要`0ba4523364fff55023b73917cffe97114e4084e0162fe3cef994f3a07f852afb`；环境锁摘要仍为`919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af`。包约641,660字节，控制器身份与公开输入分开。
- 最终CLI verify通过。`D:/Project/PyRepair Agent/tmp/ls-1023-fe4ef31f/`完成120/120脚本槽位；再次相同simulate恢复时journal摘要不变，无重执行。real_model_trials=0，各组核心比例均未测量，fully_verified为null。扩展适用6槽位（more×3×2），其他114为not_applicable，不当作通过。

这里完成的是离线工程、题包和调度验收；不代表120次真实模型修复，也不更新旧54/54。more原范围的历史运行时间波动根因仍未解决；本轮参考通过不能抹掉此前超时，更不能声称该波动已经根治。

后续仍需：确认真实调用/费用边界，审查并启用受控真实入口，执行固定双组重复实验，最后基于原始结果报告性能/成本与局限。不自动提交、合并、推送或创建PR。

对应源码：`benchmarks/evaluation/comparison_evidence.py`、`comparison_budget.py`、`comparison_methods.py`、`comparison_pack.py`、`comparison_journal.py`、`comparison_reporting.py`、`layered_assets.py`、`layered_grading.py`与`benchmarks/run_comparison.py`。过程记录见[工程日志](evaluation-v2-engineering-log.md)步骤47–51及后续收尾记录；规范见[原批准设计](superpowers/specs/2026-10-23-fair-workflow-comparison-design.md)及[分层修订](superpowers/specs/2026-10-23-layered-acceptance-design.md)。
