# 受控真实对照入口：离线验收记录

日期：2026-10-23。范围：用户批准的入口实现和离线验收，不是新增模型成绩。本轮没有读取.env或真实密钥、没有真实API调用、没有付费执行授权，也没有Git提交/合并/推送/PR。实施工作区为原evaluation-v2独立worktree，main不变。

本页“本轮”仅指已完成的离线入口阶段。之后用户单独批准并执行的单题双方法真实冒烟，另见[真实冒烟及问题记录](controlled-live-comparison-smoke.md)；不把后续调用混入本页的离线数字。

后续换行修复已通过[单独离线验收](replace-text-newlines-offline.md)。因此本页冻结包仅代表修复前的历史版本，不能用于当前源码的新运行；没有覆盖旧包或回填smoke结果。

当前源码已另建[新的离线冻结包](report-scope-refreeze-offline.md)，包含换行和smoke文案修复，20题校准及120槽位脚本模拟/恢复通过；真实调用仍须单独批准。本页原930项测试及旧冻结身份不改写。

规范：[已批准设计](superpowers/specs/2026-10-23-controlled-live-comparison-design.md)，[实施计划](superpowers/plans/2026-10-23-controlled-live-comparison.md)。历史[分层题包报告](fair-workflow-comparison-offline.md)仍保留原快照。

## 1. 本次新增什么

```text
默认inspect：核对包/源码/环境/任务 → 返回未批准计划；不读key、不建额度

未来另获明确批准后，才允许显式execute/resume：
验证执行清单与全部冻结身份 → 已绑定的共享额度
  → 按冻结顺序启动当前公开job的独立worker（≤1800s）
       ├─ single-shot → ≤1次响应 → 候选补丁
       └─ full-agent → 现有双层循环 → Repair+Review合计≤36次 → 候选补丁
  → 确认进程结束及所属容器清理
  → 控制器独立核心验收 + 独立扩展回归 → journal + 报告
```

旧run_comparison.py仍只有prepare/verify/simulate，旧开源live拒绝不删除。新增run_live_comparison.py是独立受控入口，不是给simulate加一个隐式真实开关。生产src/pyrepair、修复策略、8工具/3attempt/11turn上限和Docker可信harness均不改。

## 2. 关键边界

- 执行清单绑定包身份/文件摘要、运行源码、环境、模式、精确顺序、模型/端点、额度、零重试和新输出目录。默认检查不会生成approved清单，更不能代替人的明确授权。
- 固定deepseek-flash、https://api.deepseek.com、thinking enabled/high。温度/seed/max_tokens保持提供方默认而非固定随机性。
- worker只接公开仓库、PublicTaskSpec、冻结公开证据、当前slot、固定配置及输出/额度/环境锁位置；隐藏测试、参考/错误补丁、私有指纹/判分材料只留控制器。评分结果不回灌修复会话。
- 每个新槽位前重新核对冻结包；构造job时再次核对spec/evidence摘要和修订。不能初次校验后换成另一份合法但未获授权的证据或包。
- 真实凭据仅在授权与所有验证通过后从DEEPSEEK_API_KEY读取，经子进程环境传递；不读.env、不写命令/job/日志。缺少密钥即停止，不发试探请求。
- 所有角色共用既有持久化预留，客户端与SDK额外重试为0；每槽位只启动一次。ModelClient预留额度不是人民币硬限额，也不是实测HTTP请求数；未知token/费用保留unknown。
- 上游Python只在已验Docker内执行，无网络、无key、不回退宿主。父进程仅检查自身目录记录的完整CID，核对request、环境hash、容器Name、image/profile/mount，再停止并移除。
- 若create中断且尚无确切CID，或无法确认worker结束/容器清理，按未知技术错误暂停，不声称清理完成，不全局扫描/删除。硬终止遗留writer.lock不自动移除。
- API/协议/worker/清理故障暂停后续调度，不补发请求。已写候选仅作为技术错误证据保留，不因文件存在就改判正常完成；恢复重放必须与同一候选/终态一致。

## 3. 离线验证进展

| 检查 | 当前证据 |
| --- | --- |
| 授权/公开job/worker/监督器 | 先观察失败测试，再最小实现；包含公开证据替换、限额、异常退出、无CID、无凭据副作用等反例 |
| 异常候选恢复专项与既有journal/分层保护 | 60passed，17.00秒；不与完整套件数量相加 |
| 实际Docker＋独立子进程＋FakeLLM | 2passed，136.58秒；两方法候选均独立core/extension通过；共享6次假模型预留=single1+Repair4+Review1；另一个测试实际超时并只移除所属1个CID |
| 初次实际Docker失败 | 1failed/1passed，124.46秒；失败在测试请求证据顶层数组不符合JSON对象协议。已改测试输出为对象，旧XML保留 |
| 静态检查 | 13个新增/修改评测代码与测试文件Ruff check、format --check通过 |
| 源码/历史保护 | 22个生产Python文件相对本轮起始摘要0差异；4,130旧保护项仍仅此前授权5个装配/类型文件不同，新增未授权差异0 |
| 集中完整回归 | 930passed、9deselected，436.03秒，exit0；排除live/docker，另行实际运行新增2项Docker测试 |
| 新20题包/120槽位 | 当前源码下20/20实际校准valid、冻结verify通过；120/120脚本槽位及再次恢复通过，journal摘要不变；不是模型成绩 |

测试证据根：D:/Project/PyRepair Agent/tmp/live-23c999c9/。docker-process.xml为初次失败；docker-process-final.xml为修复后两项通过。所有模型均为自编FakeLLM，不能把6次假模型调用或2份正确候选写成DeepSeek成绩。

限定独立只读审查发现1项Important：候选写出后worker异常退出导致技术终态与文件冲突。两个自编进程反例（退出2/清理失败）先失败，再修复journal异常路径保留候选、维持技术暂停；60项专项复验通过。不删除异常证据、不重新请求、不把其改成成功。

## 4. 后续真实执行仍需什么

本阶段只实现和离线验证入口，不创建实际付费授权或额度。之后单独确认more r2、trial1、两种方法的smoke：理论最多37次ModelClient预留，不是37元，结果单列且不混入正式实验。正式20题×3×2=120次方法运行，理论最多2,220次预留，同样需要另一份明确批准；不能用旧72次Review授权。

没有真实执行就没有本轮核心成功率、配对提升幅度或模型费用结论。真实调用前如要求人民币硬上限，必须另行核价和实现可验证的费用约束。当前本地授权清单只防误操作，不能抵御恶意宿主篡改。

## 5. 源码索引

| 文件 | 职责 |
| --- | --- |
| benchmarks/evaluation/live_plan.py | 未批准计划、严格批准核对、公开job和冻结证据边界 |
| benchmarks/evaluation/comparison_worker.py | 延迟模型装配、复用生产协调器与两方法；不执行上游宿主代码 |
| benchmarks/evaluation/worker_supervisor.py | 受控进程、超时证据、确切CID归属核对与清理 |
| benchmarks/evaluation/live_comparison.py | 授权后调度、共享预算、完整冻结集合的独立分层判分与报告 |
| benchmarks/run_live_comparison.py | 默认inspect；仅显式execute/resume读取批准清单 |
| comparison_pack.py / comparison_journal.py | 新CLI纳入源码身份；异常候选与技术终态一致恢复 |

问题与解决过程见[工程日志](evaluation-v2-engineering-log.md)步骤54及后续记录。

## 6. 当前源码的全新冻结与只读检查

- 新包：D:/Project/PyRepair Agent/tmp/lc-1023-f39590ec/。18合成＋2开源dev，20/20核心校准valid；实际132份supervisor证据/132个独立CID，清理错误0、环境/判分/超时错误0。more三轮核心均valid，独立扩展缺陷基线预期failed，参考通过完整766节点；不称上游所有测试入口通过，不抹掉历史时延波动。
- 包身份：179a568fe43142dc60c8e4caef0b209a09e18885e59ee68eb3211a7b6c9c0f07；运行源码摘要796a78060098df81a350840f69b8e804915406bcd853805541885a88dd596214。新增live CLI已纳入身份（摘要dc860906a2e9babf173f14b6ffa08397204de65c1cc09f0b28c107020deed50b）。包641,756字节，authorization仍为offline-only。
- 环境锁摘要保持919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af；可信harness未修改，无新安装/拉取/网络设置变更。
- 新脚本模拟：D:/Project/PyRepair Agent/tmp/lcs-1023-8fd52798/。120/120槽位，real_model_trials=0，4组核心比例均为null；扩展适用6槽位，其余114为not_applicable，fully_verified=null。恢复前后journal SHA256均为a70777f62cc26bbda6b5c1e356d362ed92f06c28f0fa0d29cbae9d7c839cba46，没有重新执行。
- 实际新CLI默认inspect对该包返回more r2的2槽位未批准提案；检查目标D:/Project/PyRepair Agent/tmp/future-smoke-1023-f39590ec/未创建，没有授权文件或预算。提案中的37是未来候选上限，不是当前授权，不是37元。

结论：已完成本轮受控入口的离线工程验收，保留原隔离工作区，不自动发布。真实smoke和正式对照仍未运行，须分别取得新明确授权；本页所有FakeLLM、参考补丁校准与脚本模拟均不可写成DeepSeek性能。
