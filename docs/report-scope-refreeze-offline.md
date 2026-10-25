# 冒烟报告范围修正与新版本冻结

2026-10-23：用户对“修正冒烟报告文案、重新冻结版本，再单独确认真实预算”回复“请继续吧”。本轮只修正报告范围并进行离线校准/冻结，不调用真实模型，不读取.env或真实凭据，不提交/合并/推送/PR。

根因是`summarize_comparison`将限制说明写死为three repeats，而真实控制器虽然写入execution_mode=smoke，却没有让报告标题和说明区分smoke与formal。修复保留所有统计/评分/额度规则：标题明确冒烟；任务数和计划trial数从实际选中的slots及paired_cases计算，不误用父冻结包的三轮配置，不把计划次数描述为已经完成。模拟和离线假执行继续不产生真实成功率，历史结果不覆盖。

执行顺序：先补报告及控制器行为测试观察RED，再最小修复、聚焦及完整回归；源码稳定后使用现有可信Docker环境在全新目录校准20题，成功才生成新包。随后120槽位只做脚本模拟及恢复验证，真实模型结果仍为未测量。遇校准失败保留证据并调查，不挑选补跑成绩或更改任务标准。

本轮开始时运行摘要为8150c4183440bc61c59286e24c25513a6a30bfaf9b8eafd4efbfdbdac626643a；起始文件摘要保存在本轮测试产物目录的start-integrity.json。后续各阶段以实际测试、校准和[工程日志](evaluation-v2-engineering-log.md)记录为准。

## 报告修复验证

产物目录：`D:/Project/PyRepair Agent/tmp/report-1023-8a18cf7b/`。

| 项目 | 已取得的证据 |
| --- | --- |
| RED | 新7项最初均失败，`red-report-scope.xml`保留；控制器夹具修正后单独RED证明两槽位已完成但仍错误写three repeats |
| 聚焦回归 | 42项通过，84.93秒、exit0，`green-report-scope.xml` |
| 完整离线回归 | 957项通过、9项live/docker排除，440.72秒、exit0，`full-regression.xml` |
| 静态与格式 | 本轮4份Python文件Ruff check及format均通过 |
| 代码范围 | 起始66份运行身份文件仅comparison_reporting.py/live_comparison.py变化，src/pyrepair未改，模型/评分/额度规则未改 |
| 历史结果 | 原smoke四份核心产物SHA256与resume-verification相同，预留仍21；不覆盖旧报告，未补跑 |

控制器反例起初因测试专用假Docker锁被真实环境检查拒绝，出现1槽位technical终态。确认原因后只替换测试中的外部环境探针，真实无补丁grader继续运行，不执行容器，也没有放宽生产环境校验。之后反例在报告说明处按预期失败，再实施修复。

当前运行源码摘要为`af78066e0e2ec5d5a10659894e7160807ad32e343f6026f96f00d81b6ba87b82`；环境锁仍`919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af`。

## 新冻结包已完成实际校准

新包目录：`D:/Project/PyRepair Agent/tmp/lf-1023-9cae6ba2/`，prepare与verify均exit0。`pack.json`为641,756字节，identity_hash为`2027d10c8ecdf58048eb84cd78d52c3e501ab528dab4b29d40a14c4ee97838c1`，authorization仍为offline-only。这是独立新版本，不原地重写旧179a568f包。

- 18个合成任务＋2个开源任务，20/20核心校准valid。任务指纹、revision、隐藏/回归协议和完整collection摘要逐题与旧包相同，没有换题或放宽评分。
- more r2的3次核心校准均valid；独立扩展缺陷基线为failed，参考补丁passed，固定766节点。参考补丁校准不是模型修复成绩。
- 132份supervisor证据、132个独立64位CID，清理/完整性错误0；只读核对Docker实际列表，属于本轮的容器剩余0。阶段状态67 passed、65 failed中的失败是预期缺陷/错误补丁校准，不是65个Agent答题失败。
- 校准在完整离线回归结束后顺序运行，没有与整套宿主测试并行；没有API或上游任务选择性补跑。

## 脚本模拟、恢复与默认只读入口

`D:/Project/PyRepair Agent/tmp/lfs-1023-9cae6ba2/`：120/120计划槽位脚本模拟完成，real_model_trials=0，4组核心比例均null，扩展适用6/不适用114、fully_verified=null。模拟报告根据实际计划写20任务、每题计划3轮，不是假造模型100%成功。

再次执行相同simulate恢复，exit0；journal SHA256前后均为`8b504c3483631a632038d0f097d0b46ac77d742c323a658f76eb6a377d9a89cb`，不重执行或追加模型调用。

对新包实际运行真实入口默认inspect，exit0，输出NOT AUTHORIZED；计划仅more r2/trial1两方法、最多37次ModelClient预留，未来输出目录实际不存在。检查发生在凭据访问前，未新建执行批准、付费额度或结果目录；本轮产物中的proposed-smoke-plan.json明确未授权，不是可执行批准。

## 遗留、问题与授权边界

一次只读汇总脚本用“含core字段”挑选任务，误选到单轮合成校准，三轮断言失败；改为more的确切ID后通过。没有重跑校准、修改候选或改变成绩。一次读取单行JSON把766节点清单整行展开，改为解析字段计数；之后不输出冗长清单。这些均是排查命令问题，不记作Agent失败。

原smoke的journal/calls/summary/report四份SHA256保持原样，仍只有原21次预留。single-shot的不完整hunk按旧规则拒绝；API90秒配置不冒充已验证的完整调用硬壁钟。本轮未放宽80行门禁、修模型hunk、改模型策略、调用真实API或Git提交/合并/推送/PR。

下一步才是**另行批准新的单题真实冒烟**：固定新包、deepseek-flash、more r2/trial1、两方法各1次，最多37次ModelClient预留，无自动重试/补跑。37不是人民币上限或HTTP请求实测上限；旧剩余16次不沿用。正式120次方法运行、理论最多2,220预留仍需再另批，不能将本轮离线校准与模拟混成真实修复成功率。

收尾再次verify新包通过；七份更新文档94条本地链接有效、0断链，4文件Ruff及format通过，HEAD仍558cf66de7fd5225c1900446a1410247fab78399。机器检查摘要见本轮产物目录`verification.json`；未授权的建议smoke计划摘要为c5bd9392f3bdf02deb5118a6ac5bf2f23ea957cd7aa25aee30dac0e92b96c9b0，仅用于后续核对，不代替人的批准。

后续实际检查点（2026-10-24）：用户另行批准该计划的新smoke，实际8/37次预留，完整Agent核心及扩展通过；单次候选被路径范围规则拒绝。另发现该按题规则没有在共享初始输入中明确公开，正式实验前需补齐。见[新smoke记录](controlled-live-comparison-smoke-after-fixes.md)；本页离线阶段的未授权状态和历史数据不回写，也不把新结果当整体成功率。
