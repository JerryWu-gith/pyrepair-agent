# 修复后单题双方法真实冒烟（2026-10-24）

本轮根据用户在明确37次ModelClient预留上限、非人民币上限、无自动重试/补跑的询问后回复“请继续”执行。只覆盖新冻结包的more r2/trial1、single-shot→full-agent各1次；不含正式120槽位或Git发布。

## 1. 结果先看

| 方法 | 实际模型预留/返回 | 候选与独立验收 | 方法内耗时 |
| --- | --- | --- | --- |
| 单次生成 | 1/1 | 生成450字符候选；修改不在允许范围内的文件，被拒绝，未执行功能测试 | 160.87秒 |
| 完整Agent | Repair6＋Review1，均返回 | 1 attempt、7次工具调用；独立公开22节点＋隐藏4节点通过，766节点扩展通过，fully_verified=true | 75.81秒 |

真实入口exit0仅表示2/2方法运行结束，**不是两方法都修复成功**。这是一道已读dev任务、一次trial，不是20题正式结果，不能外推整体成功率，更不能将结果差异归因于某一个组件。

**还发现一个正式对比前必须处理的协议问题：** 评分器限制只修改`more_itertools/more.py`，但两方法共享的初始输入没有明确公布该路径白名单。完整Agent确实交付了通过独立验收的补丁；然而不能据单次候选的路径拒绝来公平宣称完整Agent优于单次生成。原分数保留，不给单次补丁改路径或补跑。

## 2. 身份、授权和产物

- 新包：`D:/Project/PyRepair Agent/tmp/lf-1023-9cae6ba2/`；包身份`2027d10c8ecdf58048eb84cd78d52c3e501ab528dab4b29d40a14c4ee97838c1`。
- 源码摘要：`af78066e0e2ec5d5a10659894e7160807ad32e343f6026f96f00d81b6ba87b82`；环境锁`919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af`。
- 计划摘要：`c5bd9392f3bdf02deb5118a6ac5bf2f23ea957cd7aa25aee30dac0e92b96c9b0`；模型deepseek-flash、thinking enabled/high，SDK/provider额外重试0，worker上限1800秒。
- 本轮输出：`D:/Project/PyRepair Agent/tmp/future-smoke-1023-9cae6ba2/`。名称沿用原只读计划，不代表执行日期为10月23日；本轮实际授权/执行为10月24日。
- 同级`future-smoke-1023-9cae6ba2-authorization.json`根据本次人的明确回复创建；之前proposed-smoke-plan.json保留当时NOT AUTHORIZED，不覆盖。

目录中的execution.json绑定计划与授权；q/calls.jsonl保存先预留后响应/错误；s0000/s0001分别为两方法公开job、响应、candidate、supervision与独立g/判分。summary.json/report.md保持机器原始输出；diagnostics.json和resume-verification.json是事后只读核对元数据，不改写原分数。

身份与授权先于凭据访问，环境凭据可用才执行；未读取.env或聊天旧key，不输出真实值，不放入命令、job或日志。旧smoke、旧包和旧失败不覆盖，未提交/合并/推送/PR。

## 3. 真实用量与失败分布

总预留8、返回8：single1、Repair6、Review1，API错误事件0，两槽位技术错误0。37次是本轮调用预留上限，不是人民币费用或HTTP传输次数上限。剩余29次未使用，**不自动授权另一题或补跑**；旧实验剩余16次也不沿用。

| 角色 | 模型调用 | 输入tokens | completion tokens |
| --- | --- | --- | --- |
| single-shot | 1 | 5,220 | 36,386 |
| Repair | 6 | 60,375 | 4,137 |
| Review | 1 | 800 | 7,945 |
| 合计 | 8 | 66,395 | 48,468 |

provider usage_known=true，总计114,863 tokens；人民币费用和真实HTTP请求数为unknown/null，不填0。耗时是各方法内部计时，不是所有预检查/独立评分合计的端到端时间；API90秒配置仍不声称为已验证的完整调用硬壁钟。

单次方法是`patch_rejected`，不是本次format_error，也不是隐藏断言失败；其功能测试根本未执行。完整Agent的core与扩展均passed，不能把这个一次通过写成真实缺陷总体100%。不同版本/随机生成之间也不能仅凭用量差异作组件效果的因果结论。

## 4. 换行修复已在真实任务生效

完整Agent新增`_pending`以保留零长度缓存放不下的peek值，仅修改more.py，原始Diff为+12/-0；原80行Policy无违规，没有放宽规则。成功仅用了第1个attempt，随后Review和最终Verifier通过。

4份实际Agent容器快照：原版174,856字节、5,630个LF；后3份175,342字节、5,642个LF；全部CRLF计数0。不存在旧smoke的整文件LF→CRLF及上万行Diff。原始补丁和快照保留，不做事后规范化改分。

独立评分器另外执行公开22节点、隐藏4节点和766节点扩展。Agent内部目标/公开验证不冒充隐藏或扩展验收。共7个独立容器CID，清理/完整性错误0，实际Docker列表中本轮剩余容器0。两份worker supervision均completed、returncode0、cleanup clean。

新机器报告标题为SMOKE，说明实际1任务、每题计划1轮，无three repeats错误，仍显式禁止外推整体性能。

## 5. 新发现：评分允许路径没有明确公开

单次候选把`_seekable.__bool__`的猴子补丁加到`more_itertools/__init__.py`。评分器按原规则拒绝：`patch touches a path outside allowed_source_paths`。manifest中只允许more.py；没有修改该规则，也没有把其候选改为通过。

按系统排错追溯边界，实际两个job的spec/evidence及重建初始事实相同，初始事实摘要均为`b527b99028623bd1f3f75343b61c0eb51fe7e23e553c42bf85476f6e0ffd008d`。但PublicTaskSpec只有case_id/revision/source_kind/visible_tests/timeout/input_policy/public_input_hash/version；任务说明只讲零长度缓存的行为要求，初始事实及系统提示没有明确的按题可修改路径列表。`prepare_agent_input`仅把allowed_source_paths用于确保文件被纳入公开树，不等于把可修改范围公开给模型。

**结论边界：** 同一份初始材料不自动等于评分合同完整。该发现影响工作流优劣对比的解释，不否定完整Agent补丁已通过当前功能验收。未执行单次候选的可见/隐藏测试，不能声称若放开路径它会通过或失败。

推荐下一步先离线把同一份允许修改路径作为明确公开约束提供给两种方法（必要时也供Review使用），保留评分器、隐藏测试与路径限制，不为本次候选放宽规则。涉及公开输入协议版本和新冻结，应先确认设计；本轮不实施、不使用剩余29次重试。正式实验在此问题解决前不启动。

## 6. 本地恢复核对

清除进程key，并将credential_getter设为禁止访问后，实际resume完成，exit0；新增模型调用0，预留/返回仍8/8。journal/calls/summary/report四份SHA256逐字节不变，完整摘要见原产物resume-verification.json。该验证不是模型重试或补跑。

过程与未解决项见[工程日志](evaluation-v2-engineering-log.md)步骤62–63。此前换行和报告范围修复、新20题离线校准的历史记录见[新冻结报告](report-scope-refreeze-offline.md)。

收尾再次verify新包通过，源码摘要及HEAD未变；旧21次与新8次账本、两轮四份核心产物摘要均保持原样。六份更新文档86条本地链接有效、0断链。汇总检查保存在`D:/Project/PyRepair Agent/tmp/livecheck-1024-f4c0fffc/verification.json`，本轮结束后没有新增真实请求、实现公开约束修复或启动正式实验。
