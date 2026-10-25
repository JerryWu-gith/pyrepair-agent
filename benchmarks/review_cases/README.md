# 固定 Review 对照候选（开发集）

这里只存待审查的固定补丁及离线验收资产，不是新模型修复成绩、随机样本或 holdout。

| 题目 | 正例来源 | 反例来源 |
| --- | --- | --- |
| case_03 | 历史 54-trial 实验 trial 1 的最终模型补丁 | 原 wrong.patch，只适配重量 2 |
| case_15 | **人工校准**：Decimal.as_integer_ratio + 整数运算 | 原 wrong.patch，只适配金额 12.50 |
| multi_time | 同一历史实验 trial 1 的最终模型补丁（2 个源码文件） | 原 wrong.patch，固定一个时间字符串 |

历史实验：live-repeat3-flash-20261016-df19fe71。manifest.json 保存来源、原始字节哈希、人工契约核对依据。复制的 patch 仅统一为 LF；没有改写原始产物。准备时再记录当前 fixture 的字节摘要。

## 金额候选为何人工校准

旧补丁 `int(Decimal(value.strip()) * 100)` 通过了当时有限测试，但乘法受 Decimal context 的有效位数限制；长金额仍会舍入。该旧补丁保存在 diagnostics 下作为排除证据，不属于这次 6 个模型评测输入。

人工候选先精确转换为整数分子/分母，再用整数乘法和整除。对非负、最多两位小数的十进制金额，分母约分后只含 2、5 且整除 100，因此不会舍入；不承诺非法格式、非有限值或违反小数位约定的输入行为。

precision_tests/test_money_precision.py 覆盖 6 个金额 × 3 个 Decimal context 精度（2、28、64），包含 28 位以上金额。它只安装到独立的 Review 标签验收副本，不进入公开故障捕获、Repair 或 Review 提示词。旧 v2 hidden/gold/wrong 及成绩保持原样。

## 如何使用

在项目根目录离线执行：

```powershell
python benchmarks/run_review_evaluation.py prepare --output benchmarks/results/review/prepared-01
```

只有公共 buggy 故障、六候选标签和精度检查全部成立，才生成可运行的 prepared.json。重复目录拒绝覆盖。源码、CLI 或本目录资产改变后，必须重新准备；不续跑旧包。

真实 run 需要显式 --live、模型、重复次数和请求上限，且需单独同意费用。当前只完成离线能力，不据此声称 Review 更准确。报告可离线重建，固定候选的六个 ID/标签/来源均不发送给模型。

输入中只有 FailureReport、候选 Diff、改动行数，以及 B 组的公开任务说明。标签、精度测试、隐藏测试、额外 gold 答案不发送。目录分离不是 OS 安全沙盒，仅用于本仓库可信自建任务。
