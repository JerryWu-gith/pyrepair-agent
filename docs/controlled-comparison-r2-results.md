# 公开修改范围r2：真实对照最终报告（分阶段完成）

更新：2026-10-25。**原54次正常结果保留＋新66次真实续跑完成，共120/120次方法结果、未运行0。** 评测适配器在两个阶段之间修复，不能将本报告称为“同一未变化运行时的一次完整批次”。原技术错误及全部普通失败均保留；smoke、旧54/54和其它历史实验不混入成绩。B尚未开始。评测结束最初保留本地工作区，随后用户另行要求同步GitHub；仅发布项目代码、开发任务资产和汇总，原始运行日志/冻结包仍在本地。

## 1. 最终结果：独立核心验收

固定20道已读dev任务＝18道synthetic＋2道开源缺陷，每题每方法独立重复3次。每方法60次，不是60次API请求。通过指独立评分器在新副本应用候选后通过核心公开/隐藏验收，不以Agent自报成功代替。

| 方法 | 合成：18题×3 | 开源：2题×3 | 合计：20题×3 |
| --- | ---: | ---: | ---: |
| 完整Agent工作流 | 53/54（98.1%） | 6/6（100%） | **59/60（98.3%）** |
| 单次生成single-shot | 35/54（64.8%） | 1/6（16.7%） | **36/60（60.0%）** |

60个题目/trial配对均有双方法结果；Agent多交付23个核心可验收补丁。三次全部通过的任务数：Agent19/20、single-shot6/20；仅3次观测，不外推长期稳定性或未见任务表现。

**这是一项整体工作流比较，不是等预算、等算力或某个组件的因果消融。** 两方法收到相同初始公开任务/失败/代码事实及准确允许文件清单；Agent另有工具反馈、测试、Review和内部重试。单次生成的24次失败中22次尚未进入功能验收，不能将全部差距说成模型修复逻辑更强。

## 2. 两个阶段如何连接

| 阶段 | 保留/执行范围 | 方法结果 | 技术事件 | 预留/返回 |
| --- | --- | ---: | ---: | ---: |
| 原formal | case_01—case_09，每题3trial双方法 | 54正常：Agent27通过，single19通过 | 第55个slot在baseline出错，未请求模型 | 181/181 |
| 新continuation | 原slots[54:]，case_10起至最后一题 | 66/66正常：Agent32通过，single17通过 | 新增0 | 272/272 |
| 覆盖汇总 | 原54＋新66，20题双方法各3trial | 120/120，未运行0 | 原1次事件另保留，不伪造成第121道结果 | 453/453 |

原错误slot为case_10--1--full-agent：原错误原件未删除，它在单独批准的新阶段执行一次。没有重跑原54次，没有补跑原8次single-shot普通失败，也没有补跑本轮case_15隐藏验收失败。原journal、候选、grade、summary、report及6,632个旧运行文件总摘要经最终核对保持不变。

用户另批的新66次上限为1,221次ModelClient预留，实际272次；剩余949次不自动使用。旧smoke37和formal2,220的授权与新续跑计划分别保留，不把旧未用额度当作新计划许可。新旧实际合计加独立smoke为461次预留/返回，不是人民币或HTTP计数。

## 3. 核心与扩展回归分别报告

开源核心逐题：more-itertools r2为Agent3/3、single0/3；boltons r2为Agent3/3、single1/3。

| more-itertools扩展（原选定上游文件） | 计划 | 通过 | 因核心未过而未运行 | 超时/错误 |
| --- | ---: | ---: | ---: | ---: |
| 完整Agent | 3 | 3：每轮766节点 | 0 | 0 |
| single-shot | 3 | 0 | 3 | 0 |

single-shot的扩展是**未运行，不是跑后失败**。boltons及18道合成题未配置本扩展通道，属于not_applicable，不算扩展通过。核心通过不自动等于全部上游测试通过；766节点只是已冻结的选定文件回归集合，不宣称整个上游仓库全量测试。

## 4. 失败不是一类：重要反例保留

| 方法 | 失败类型 | 次数 | 能否判断修复逻辑 |
| --- | --- | ---: | --- |
| single-shot | 输出格式错误，无法提取候选（format_error/no_patch） | 14 | 不能，尚未功能验收 |
| single-shot | 补丁hunk不能应用（patch_rejected） | 8 | 不能，尚未功能验收 |
| single-shot | 可应用、公开通过，隐藏验收失败 | 2 | 有真实功能反例 |
| 完整Agent | 内部success，但独立隐藏验收失败 | 1 | 有真实功能反例 |

唯一Agent失败为**case_15/trial2：金额转整数分的Decimal精度边界**。候选使用`Decimal(value) * 100`后判断有限/整数；乘法已受全局Decimal context精度影响，低精度或长金额下会先舍入，因此后续整数判断不能恢复精确值。内部公开验证和Review放行，独立隐藏验收的低精度/长金额边界拒绝。另两次Agent运行通过；single-shot的trial1、trial2也被同类隐藏断言拒绝，trial3为非功能验收失败。

这是新增隐藏验收实际发现的**内部成功误报**，不是测试工具出错。未更改隐藏验收、手修候选或补跑该trial，不以“内部60/60 success”代替独立59/60。

8次不能应用的single-shot分布：case_08/t2、t3；case_14/t2；multi_time/t1、t2；more/t1、t3；boltons/t2。原错误均为patch failed/patch does not apply，不将这些失败包装成8次代码推理错误。

## 5. 逐题三次重复

| 任务 | 来源（均dev） | single-shot核心通过 | Agent核心通过 |
| --- | --- | ---: | ---: |
| case_01 | synthetic | 2/3 | 3/3 |
| case_02 | synthetic | 1/3 | 3/3 |
| case_03 | synthetic | 2/3 | 3/3 |
| case_04 | synthetic | 3/3 | 3/3 |
| case_05 | synthetic | 3/3 | 3/3 |
| case_06 | synthetic | 3/3 | 3/3 |
| case_07 | synthetic | 2/3 | 3/3 |
| case_08 | synthetic | 1/3 | 3/3 |
| case_09 | synthetic | 2/3 | 3/3 |
| case_10 | synthetic | 3/3 | 3/3 |
| case_11 | synthetic | 3/3 | 3/3 |
| case_12 | synthetic | 2/3 | 3/3 |
| case_13 | synthetic | 2/3 | 3/3 |
| case_14 | synthetic | 0/3 | 3/3 |
| case_15 | synthetic | 0/3 | 2/3 |
| multi_orders | synthetic | 3/3 | 3/3 |
| multi_inventory | synthetic | 2/3 | 3/3 |
| multi_time | synthetic | 1/3 | 3/3 |
| os_more_seekable_1269 | opensource | 0/3 | 3/3 |
| os_boltons_addlist_458 | opensource | 1/3 | 3/3 |

Agent内部attempt分布：53次只需1个attempt、5次用2个、2次用3个。按最终独立通过统计：1个attempt的53次通过、2个attempt的4次通过、3个attempt的2次通过；另1次虽在第2个attempt内部成功，仍被独立验收拒绝。**attempt是同一trial内重试，不是另一次独立trial。**

## 6. 真实资源消耗与耗时

| 正式两个阶段的角色 | 预留/返回次数 | 输入token | completion token |
| --- | ---: | ---: | ---: |
| repair | 332 | 1,403,609 | 81,845 |
| review | 61 | 40,058 | 95,949 |
| single-shot | 60 | 75,702 | 225,211 |
| 合计（不含smoke） | 453 | 1,519,369 | 403,005 |

正式合计1,922,374 token，usage_known=true。完整工作流Repair＋Review共393次调用预留、1,621,461 token；single-shot60次、300,913 token。它们不是等计算预算，也不能将token比例直接当人民币费用比例。

本次新增66槽位：272预留/272返回（Repair205、Review34、single33），输入1,178,233＋completion335,783＝1,514,016 token；无API错误、未完成调用或额外重试。加本协议的独立r2 smoke8次后，累计461次、2,031,040 token；smoke不计入修复成功率，不合并其它旧协议的smoke/54次实验。

| 方法阶段耗时（60次） | 中位数 | 均值 |
| --- | ---: | ---: |
| single-shot | 2.65秒 | 19.50秒 |
| 完整Agent | 14.23秒 | 25.21秒 |

方法阶段耗时不是含全部独立判分、准备、恢复和控制器开销的端到端耗时。各任务规模不同、模型有随机性，均值与中位数不应外推服务SLA。人民币费用、缓存计价和实际HTTP传输次数未核实，保持unknown/null，不填0或按token猜账单。

## 7. 唯一评测器修复：只影响比较，不改模型输入

原FrozenParser用FailureReport整对象相等判断当前公开基线是否仍符合冻结证据。case_10同一`assert 1 == 3`报错中的默认`<cart.Cart object at 0x...>`地址随进程变化，导致第55个slot在模型请求前被误拒。

最小修复只在summary/traceback的比较签名中消除严格默认对象repr的地址字段，业务数字、普通hex、类型、节点、异常和路径仍严格检查；比较通过后仍返回原冻结对象。不改capture_evidence、原始公开facts、TASK、生产src、工具、Review或评分。真实保存case_10重放通过，初始facts摘要仍为6d2040126bcf8b8c3af97e6f4725b2a013c3fd311a1b794c6af275575fcd2e4c。

修改源码后不能复用旧运行身份强行resume。新协议复制并验证原公开/校准资产，仅重绑新的运行身份；sidecar明确calibration_reused=true及原结果出处。旧verify_pack保持严格，旧包未原地重冻。

工程证据：比较器RED为1failed/17passed，GREEN18passed；限定回归记录109项通过（198.273秒），先前66槽位调度/恢复已单独通过、未重复跑；六文件静态/格式通过；一次限定独立只读审查无重要问题。最终只读核对覆盖新旧身份/授权、两份journal、候选与评分绑定、角色账本及汇总一致性，不是再跑测试、Docker校准或模型。

跨日准备时Docker引擎未启动导致首次新准备verify失败，保留失败目录a184，仅启动已有Docker，在a184b成功准备；不重装、不改权限/配置、不重新校准。新阶段240个确切容器ID最终实际Docker列表残留0；未删除或停止其它容器。

## 8. 冻结身份与本地原始产物

| 对象 | 身份摘要 |
| --- | --- |
| 原pack | 8a728ccde3a7fd4c37ff05ce0f4738c58fba7bdceca6d0f56d5a1d2f583c769f |
| 原runtime source | eb39d6b85185831a30b290936ddc1d8197fa4edce1c7fda505f5fec8753c35c1 |
| 新pack | 3a1877b869549c86b2bb5a7890a70d2fc813284b6e28efae303305a7a3f58a92 |
| 新runtime source | 713fe2cec737e8b0964ae9118354980263aba48bedf33b33b67ba13843bc5ba1 |
| 新执行计划 | 73ad6df80a6c7580daa60209c22ef1842a8167150bf3f8e92312c29cb94d1da2 |
| 同一环境锁 | 919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af |

- 原包：`D:/Project/PyRepair Agent/tmp/scopepack-1024-66ec3736`。
- 原中断目录：`D:/Project/PyRepair Agent/tmp/scope-formal-1024-de0c6b68`。
- 新包：`D:/Project/PyRepair Agent/tmp/repr-pack-1025-a184b`。
- 新66次：`D:/Project/PyRepair Agent/tmp/repr-formal-1025-a184`。
- 新覆盖汇总：新66次目录下`combined/summary.json`及`combined/report.md`；原grade路径仍指向原件，不重写为新目录。
- 本轮设计/授权/检查点/最终审计：`D:/Project/PyRepair Agent/tmp/repr-1024-a184`；`final-audit.json`包含逐失败、用量及来源，另有清理核对记录。

原始目录按Git规则忽略，仅在本机；不是GitHub可下载结果。最终主进程退出码因客户端会话释放未直接收取，不追认“观察到exit0”；120结果及最终文件已通过独立只读重建核对，没有重新执行来取退出码。

## 9. 独立smoke与结论边界

本协议r2 smoke仍独立保留：固定more r2/trial1，两方法各1次，2/2结束，8预留/8返回；Agent核心及766节点扩展通过，single-shot补丁不能应用。它仅为一道已读dev题的链路检查，不混入三次正式成绩。

本轮已经完成既定开发集评测闭环；仍然只有18道人造任务＋2道已读开源任务，文件级修改范围已公开，未构建冻结后的外部验收集。不宣称SWE-bench成绩、未知仓库定位、训练数据无污染、优于Claude Code或通用代码修复能力。分阶段/跨日调用与provider默认随机性也限制结论强度。

下一阶段B拟补真实外部任务，尚未开始；其设计/任务冻结及新真实调用预算另行处理。不继续调Agent刷分。2026-10-25用户另行要求同步GitHub，取代原评测阶段的暂缓发布要求，但不授权额外实验或B。发布范围不包含凭据、原始运行产物和个人简历材料。

设计与过程：[续跑设计](superpowers/specs/2026-10-24-baseline-repr-continuation-design.md)、[实施计划](superpowers/plans/2026-10-24-baseline-repr-continuation.md)、[工程日志](evaluation-v2-engineering-log.md)步骤71—75；前置[共享公开范围离线记录](public-edit-scope-offline.md)。
