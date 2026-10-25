# Review 公开任务说明：离线实现与验收

日期：2026-10-16。范围：evaluation-v2 独立 worktree；未提交、合并、推送或 PR。

后续更新（2026-10-17）：用户已另行批准并完成 36 次真实对照，见[真实结果](review-contract-live-results.md)。本文的“0 次调用/待授权”均指下述离线实施阶段；保留阶段记录，不将真实运行混作离线验收。

## 已完成什么，尚未证明什么

已补齐 `PublicContractContext → ContextBundle.task_contract → Coordinator → Review`。Repair 原消息不重复加说明，16,000 字符上下文预算不变。普通无说明调用保持兼容；说明非字符串、空白或超过 4,000 字符时拒绝，v2 缺失任务文件也不静默变成“无说明”。Review 没有工具、使用原严格 JSON 解析。

已实现固定候选准备、显式 live 对照入口和离线统计。**本离线实施阶段真实模型调用为 0；不能仅据离线测试声称 Review 误拒减少或修复成功率提高。** A 组是新共同提示词的无说明控制组，不是旧版提示词逐字复现。

## 三题六候选的实际独立验收

最终离线包：`benchmarks/results/review/prepared-20261016-02/`（本地忽略目录）。`prepared-20261016-01/` 保留为审查修正前的记录；新源码会拒绝使用其旧运行时指纹。

| 候选 | 来源 | 可见测试 | 隐藏测试 | Review 专用金额精度检查 |
| --- | --- | --- | --- | --- |
| case_03 正例 | 历史 trial 1 最终模型候选 | 2 通过 | 2 通过 | 不适用 |
| case_03 反例 | 原 wrong.patch | 2 通过 | 1 失败、1 通过 | 不适用 |
| case_15 正例 | **人工校准** | 2 通过 | 2 通过 | 18 通过 |
| case_15 反例 | 原 wrong.patch | 2 通过 | 1 失败、1 通过 | 12 失败、6 通过 |
| multi_time 正例 | 历史 trial 1 最终模型候选，2 文件 | 1 通过 | 2 通过 | 不适用 |
| multi_time 反例 | 原 wrong.patch | 1 通过 | 1 失败、1 通过 | 不适用 |

被排除的历史金额 Decimal 乘法候选，在新精度检查中 **6 失败、12 通过**。这只是说明旧验收有覆盖缺口，不改写旧 54/54 结果。人工候选使用 `Decimal.as_integer_ratio()` 后做整数运算；测试涵盖 6 个金额及精度 2/28/64。它不是第七个模型评测候选，不增加未来 36 次的预算。

prepare 从未安装隐藏测试的公共 buggy 副本捕获原始故障，再在其他副本上应用候选、独立验收。准备失败不生成 ready 包。标签/来源/评分与公开模型输入分离；发送边界只选择 failure、patch、task_contract。冻结包有源码、CLI、提示词、fixture、候选及说明摘要。摘要用于可复现和误改检测，不是防恶意篡改的密码学签名。

## 入口与产物

```powershell
# 完全离线；请换一个尚不存在的目录
python benchmarks/run_review_evaluation.py prepare --output benchmarks/results/review/prepared-02

# 完全离线；对已有对照实验重建报告
python benchmarks/run_review_evaluation.py report --experiment benchmarks/results/review/run-01
```

真实运行需另行授权费用。批准后，形式为：

```powershell
# 会产生费用，当前尚未执行/批准
python benchmarks/run_review_evaluation.py run --live --prepared benchmarks/results/review/prepared-02 --output benchmarks/results/review/run-01 --model deepseek-flash --repeats 3 --request-cap 36
```

36 是请求数量上限，不是货币上限。DeepSeekClient 在这个入口的 max_retries=0（SDK 也为 0），不改变生产修复客户端的默认重试。每次都是新的两条消息，A/B 相邻，18 对中 AB/BA 各 9 对。

| 文件 | 用途 |
| --- | --- |
| prepared.json | 离线验收通过的固定输入、标签、来源及指纹 |
| manifest.json | 模型、调度、上限、输入指纹和每个请求的摘要 |
| requests/0001/request.json | 实际两条消息及空工具列表，不含评分标签 |
| requests/0001/started.json | 请求前落盘的调用意图与请求摘要 |
| requests/0001/result.json | 返回 content、解析结果、用量、耗时或脱敏错误；不保存 reasoning_content |
| summary.json / report.md | 可重建统计与解释边界 |

不覆盖已有输出目录，不自动续跑付费运行。started 不能写入则不调用；响应保存失败则终止后续调用。started 无 result 只能说明调用结果和费用未知，不能推断一定没花钱；未完成请求保留在总分母。源码或固定资产改变后必须新建准备包，不能续用旧指纹。

## 统计与已验证的工程行为

- 正例误拒 / 有效正例判断；反例误放 / 有效反例判断。
- 判断正确 / 全部计划请求；API 错误、解析失败、未完成都不算正确。
- 同候选同组全部重复有效时才计波动；不完整组单列。
- A/B 双有效配对分别统计 B 纠正 A、B 破坏 A、两者皆对/皆错；缺失配对单列。
- 用量 0/0 按未知处理；只汇总已知 Token 下界，不把遗漏当零成本。
- 第一轮全量验收 **340 passed, 1 deselected in 141.40s**；审查补强后最终回归 **343 passed, 1 deselected in 149.60s**，相关文件 ruff 和 git diff --check 通过。未执行的 1 项为 live 测试。
- 独立审查发现的 P2 已修复并复核：Review 专用 pytest 插件从真实异常捕获 AssertionError，运行异常和缺失 required 节点不能冒充有效负例；缺失配对会明确提示“证据不足”。共享 grader 仅增加可选注入点，旧默认行为不变。
- 历史三批 18/18/54 运行及原任务资产的 **1,853 个文件**，本次修改前后逐文件 SHA-256 一致，无新增或丢失（排除可再生 pycache）。

所有测试仍是可信自建小任务；不等于 OS 沙盒、真实开源缺陷、未见任务或通用正确性证明。独立审查已无剩余阻塞问题。下一步是单独确认真实 36 次 Review 对照预算，再看数据决定是否推广或重跑端到端评测。

最终源码摘要：`d4ec543f6c11f82042e2fc125d282959599b2cccea9bbd00dfdeb7833cad240f`；准备包摘要：`9cb83cdba20990588c1ec12160de74b0a86185be42296f5c982550d5b48d11cd`。运行入口另校验 CLI、提示词、fixture 和依赖环境。文档不包含真实 Key。

设计与问题记录：[设计](superpowers/specs/2026-10-16-review-contract-ablation-design.md)、[工程日志](evaluation-v2-engineering-log.md)、[候选来源](../benchmarks/review_cases/README.md)。
