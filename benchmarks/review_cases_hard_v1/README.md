# Review hard v1：固定候选开发挑战集

六个既有公开任务，每题正反各一份，共十二候选。synthetic/dev，非 holdout，非真实开源缺陷。

公开源码、可见测试、任务说明引用原资产，不复制或修改。Review 只收到当前候选补丁转换的 Diff、公开故障和任务说明；其他候选的参考答案、标签、来源、分类与隐藏验收不进入模型输入。

| 任务 | 负例机制 |
| --- | --- |
| case_04 | lower_bound：Zero and negative pages must be rejected; last page must be accepted. |
| case_13 | whitespace_normalization：Case-insensitive true/false must allow surrounding whitespace. |
| case_15 | decimal_context_precision：Exact integer cents, including long amounts, must not depend on Decimal arithmetic precision. |
| multi_orders | rounding_order：Apply discount to the overall subtotal then floor, not floor each line. |
| multi_inventory | failure_state_mutation：A failed reservation raises ValueError without changing stock; cancellation releases once. |
| multi_time | public_helper_contract：The exposed parser returns UTC offset zero as well as preserving the instant; a correct main flow alone is insufficient. |

候选来源和原始 SHA-256 见 manifest.json。金额正例是已有人工校准参考，金额负例是旧集合排除的历史精度反例（旧记录保留）；时间正例复用历史模型候选。其余正例为人工参考、负例为人工变异。不把参考校准当作模型修复成绩。

新验收保留旧验收含义，加入边界、精度、跨文件取整和状态副作用检查。时间必须同时断言 UTC 偏移与时刻；datetime 相等本身不足以证明 UTC 偏移。金额有六个金额 × 三种 context 精度共十八项检查。

实现与验收依据：[设计](../../docs/superpowers/specs/2026-10-17-review-hard-candidates-design.md)。只执行 prepare 不会调用模型；真实 A/B 另需预算。本轮没有新模型表现结论。
