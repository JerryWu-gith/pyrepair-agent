# 共享公开文件修改范围：离线实施记录

日期：2026-10-24。状态：共享输入修正、离线回归、实际Docker、新20题冻结与120槽位模拟/恢复均完成。真实模型调用为0；不是新模型性能报告。

## 改了什么

原来模型看到的TASK只讲功能需求，评分器却另有精确文件允许清单。现在在新公开TASK顶部同时向single-shot、Repair与Review公开该清单，明确只能修改列出的现有文件。多文件任务完整列出多个路径，不移除其它可读源码。

以more任务为例：允许修改`more_itertools/more.py`，而不是任意包内文件。规则来自原评分清单，不是从gold或隐藏测试推导；任务正文仍完整保留。公开范围提供文件级线索，因此该版本测量“已告知修改范围后的修复能力”，不宣称未知仓库定位能力。

## 改动边界

- `benchmarks/evaluation/agent_input.py`：生成公共TASK，完整组合说明最多4,000字符；空白、非法UTF-8、路径无效/重复/大小写碰撞、超限在复制前拒绝。输入策略r2，描述结构仍version1。
- `benchmarks/evaluation/comparison_pack.py`：prepare/verify将TASK、Repair概览与Review任务文本直接绑定到评分器原范围；重算摘要不能替代语义一致性。事实策略r2。
- 沿用既有共享ContextBundle链路，不新增Agent参数，不修改生产`src/pyrepair/`、系统提示词、工具预算、完成条件或评分器。
- 4k任务说明与16k上下文限制不变，必要时只按原逻辑减少代码片段，不截规则或扩大预算。隐藏/gold仍不进入模型消息。

## 已取得的证据

| 检查 | 实际结果 |
| --- | --- |
| 改前相关基线 | 68passed，10.84秒，exit0 |
| 修正测试夹具后的RED | 21failed/4passed，6.92秒；失败证实缺口，不计产品成绩 |
| 仅输入修复后的聚焦GREEN | 71passed/4deselected，6.69秒；4个未完成冻结反例不计通过 |
| 冻结语义绑定RED | 5failed，2.69秒；重算摘要仍可掩盖原不一致 |
| 集中GREEN | 141passed，14.75秒，exit0 |
| 本轮8文件静态/格式 | Ruff check与format通过 |
| 一次限定只读审查 | 无P1/P2发现；不替代执行验证 |
| 完整离线回归 | 982passed/9deselected，460.02秒，exit0；JUnit failures0/errors0/skipped0 |
| 显式Docker双方法及Review链路 | 1passed，105.72秒，exit0；28独立CID，完整性/清理错误0；6次调用均为FakeLLM |

证据目录：`D:/Project/PyRepair Agent/tmp/scope-1024-66ec3736`。本轮未与完整宿主回归并行执行上游校准，未重复运行完整套件。首次RED的一个FailureReport夹具漏填字段，修正后重新观察到真实缺口；首次Ruff指出两处导入顺序，整理后通过。问题与产品验证分开，见工程日志步骤65。

## 新冻结包与实际校准

新包：`D:/Project/PyRepair Agent/tmp/scopepack-1024-66ec3736`。prepare与verify实际exit0，authorization仍为offline-only，不是可执行的真实模型批准。

| 身份 | 实际值 |
| --- | --- |
| 新pack identity_hash | `8a728ccde3a7fd4c37ff05ce0f4738c58fba7bdceca6d0f56d5a1d2f583c769f` |
| 新运行源码摘要 | `eb39d6b85185831a30b290936ddc1d8197fa4edce1c7fda505f5fec8753c35c1` |
| 沿用环境锁 | `919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af` |
| 输入/事实策略 | `agent-public-r2` / `exact-public-facts-r2` |

- 18合成＋2开源，20/20核心校准valid；more预定3轮核心均valid，参考补丁766节点扩展通过。
- 132份supervisor/132独立CID，完整性与清理错误0；阶段67passed/65failed中的失败是预定缺陷或错误补丁校准，不是65次模型失败。
- 含前面的Docker链路验收，共检查160个确切CID，实际Docker列表中本轮残留0，没有清理其它人的容器。
- 20题fingerprint/revision/source_kind/split及回归范围/collection摘要与旧包逐项一致。输入说明339–669字符，多文件任务完整公开2–3个允许路径。
- 改前426个运行/任务/harness文件仅两个预期评测运行文件改变，生产src、评分器、旧资产、可信harness与环境锁未变。首次源码摘要`af78066...`及旧包`2027d10c...`原样保留，不覆盖身份。

机器检查见检查目录`pack-audit.json`，其中只记录公开范围长度、指纹和状态，不把参考答案送入模型。

## 120槽位脚本模拟与恢复

模拟：`D:/Project/PyRepair Agent/tmp/scopesim-1024-66ec3736`，实际120/120脚本槽位完成，real_model_trials=0、4组core_acceptance_rate全部null。扩展适用6/不适用114、fully_verified=null。不是120次真实修复，也不是100%模型成功率。

再次同参数simulate实际exit0；journal、summary、report三份字节摘要均不变，没有补发或重执行。journal SHA256为`cafa809ed1e4c98b62a0f2e12446d2de9f0b728ace7f0af3c9d766531c2b183d`。`simulation-resume.json`保留三份摘要和实际状态。

## 历史与下一步

旧两轮真实smoke的各四份核心结果摘要均保持原样，调用预留仍21/8；没有重判旧候选、删除失败或使用旧剩余额度。公开路径约束的离线缺口已补齐，但尚无该新协议的真实模型结果。

下一步可另行批准新冻结版本的单题双方法真实冒烟，再决定正式重复评测。现阶段不新增授权文件、不创建真实执行目录、不自动使用剩余29/16次，也不启动正式120次方法运行/最多2,220次预留。

## 还不意味着什么

本轮真实API请求0，FakeLLM结果不是模型性能。旧21次/新8次真实冒烟与分数不改写，不把旧single-shot越界候选改成成功。修复规则事先公开不保证模型遵从，也尚不能宣称成功率提高。

新运行源码和输入身份必须使用新冻结包，不续跑旧包。真实smoke和正式120方法运行/最多2,220次预留仍需单独授权，不使用旧剩余29/16次，不自动上传GitHub。

设计见[批准方案](superpowers/specs/2026-10-24-public-edit-scope-design.md)，步骤见[实施计划](superpowers/plans/2026-10-24-public-edit-scope.md)，逐步问题见[工程日志](evaluation-v2-engineering-log.md)步骤64–66。旧真实结果见[前轮冒烟](controlled-live-comparison-smoke-after-fixes.md)。
