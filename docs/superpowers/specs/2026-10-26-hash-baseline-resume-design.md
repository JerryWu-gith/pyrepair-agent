# 动态hash基线修复与受控续跑

用户已明确批准：仅修评测层，严格识别hash比较动态值；保留原模型输入、普通数字断言及前两阶段，预检剩余公开基线后续跑167个未调用模型的槽。Agent、任务和评分合同不变，累计调用仍受原5550上限约束。

唯一可变的冻结运行时文件为 `benchmarks/evaluation/comparison_evidence.py`。仅在明确的hash对hash断言失败、两侧pytest展开值与不等整数一致、summary/traceback相符时比较动态数值的语义签名；hash表达式、节点、异常、源位置和其它数值保留。普通数字、hash对固定数字、缺失/不一致展开、变更表达式、相等结果仍拒绝。原对象地址规则保留。签名只用于内部比较，返回的FailureReport、FrozenContext、initial_facts和公开evidence不变。

修复前 `D:/Project/PyRepair Agent/tmp/g50-hash-prechange-1026-a01.json` 已验证旧runtime和80文件源码SHA。新冻结包只复制旧p/control并更新获批adapter runtime，禁止其它冻结源码、配置、证据、任务、环境或校准改变；旧包不覆盖，不重跑隐藏/参考校准。

已有133普通槽由旧129加恢复阶段前4组成；两次原技术事件保留。最新WorkerError槽没有模型调用且无候选，可以作为新阶段首槽合法生成。原slots[133:]共167槽：84 Agent、83 single-shot，新上限3107，旧506加新最大3613低于5550。旧配额不重置、不重放已调用模型的槽。

同一Docker环境只预检剩余28题公开基线。receipt绑定新包/runtime及原始公开TestRun，全部通过才允许真实执行。新外层控制器的源码、旧来源、预检、167槽和3107上限独立授权，复用现有live controller/journal/supervisor/配额；技术异常停止，不自动重试或清锁，CLI以非零表示技术停止。

报告标记STAGED/adapter-only fix，组合旧133普通记录与新167槽，保留两次技术事件、来源和累计usage；缺时长保持unknown，部分分组无完整成功率。仅本地保存，不推送或改简历。用户已批准实施和续跑，无需重复询问同一设计。
