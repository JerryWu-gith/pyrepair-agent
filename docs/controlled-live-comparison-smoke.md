# 单题双方法真实冒烟记录

日期：2026-10-23。状态：本轮2个方法槽位均已结束，但均未交付可验收补丁。已记录21次ModelClient预留及21次返回，未超过37次上限；不是正式20题评测，不作总体能力或配对提升结论。费用尚未核算。

## 1. 本轮授权与固定范围

用户在“单题双方法真实冒烟，最多37次ModelClient调用预留、不是37元、需另行确认”的交付说明后回复“开始吧”。本轮仅执行more-itertools任务os_more_seekable_1269 revision2、trial1，固定原序single-shot→full-agent，各1次。smoke独立，不混入正式三次重复实验；不自动追加次数、补跑或发布Git。

| 约束 | 已固定值 |
| --- | --- |
| 模型/端点 | deepseek-flash / https://api.deepseek.com |
| 推理设置 | thinking enabled/high；temperature、seed、max_tokens未另行指定 |
| single-shot | 最多1次ModelClient预留，无后续反馈 |
| full-agent | Repair+Review合计最多36次预留；3attempt、每attempt8工具/至多11轮 |
| 全局 | 最多37次预留；不是人民币硬限额，不冒充实测HTTP次数 |
| 重试/超时 | provider与SDK额外重试0；worker1800秒，API90秒，测试阶段≤120秒 |
| 输入/评分 | 两方法共享冻结公开证据；worker不拿隐藏、gold/wrong；控制器独立核心及766节点扩展验收 |
| 凭据 | 只从DEEPSEEK_API_KEY环境变量读取；本次进程变量可用，不读.env或聊天密钥，不输出值 |

API、协议、worker、Docker基础设施或清理错误保留证据并暂停，不补发请求。普通补丁格式/策略/业务验收失败照原序继续。所有预留先落盘；费用或usage未知就保持unknown。

## 2. 实验身份与产物

- 工作区：C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent；HEAD558cf66de7fd5225c1900446a1410247fab78399，不改main。
- 冻结包：D:/Project/PyRepair Agent/tmp/lc-1023-f39590ec/，pack hash=179a568fe43142dc60c8e4caef0b209a09e18885e59ee68eb3211a7b6c9c0f07。
- 运行源码摘要：796a78060098df81a350840f69b8e804915406bcd853805541885a88dd596214；环境锁摘要919fe7da4fbd3b9a1e0544cdd477e84e61a0ef965699564814c20372604c06af。
- 新实验：D:/Project/PyRepair Agent/tmp/live-smoke-1023-b44bfb00/；与旧失败、校准包、120脚本模拟分开。
- 用户批准清单：同级live-smoke-1023-b44bfb00-authorization.json；plan hash=bcbf23b646ac21de86cb7c520747dd12261d447ec5b425c35dcfc8e1fe02c745。根据人的本次确认生成，不代表程序可以自行授权；未批准正式批次。

主要文件：execution.json绑定执行身份；q/calls.jsonl记录共享预留/响应/错误；journal.jsonl记录两槽位状态；s0000/s0001分别为两方法的公开job、worker日志、响应、candidate、supervision及独立g/判分；summary.json和report.md保存可重建摘要。

## 3. 实际结果与用量

执行前实际核对冻结包、代码、环境、输出路径及批准清单，验证先于凭据访问。真实入口退出0，含义只是2/2方法运行结束，**不代表修复成功**。

| 方法 | ModelClient预留/返回 | 方法结果 | 独立验收 | 方法内耗时 |
| --- | --- | --- | --- | --- |
| single-shot | 1/1 | format_error，未保存有效patch | core=no_patch，扩展not_run_no_candidate | 160.31秒 |
| full-agent | Repair20/20，Review0 | 3attempt后失败，未交付patch | core=no_patch，扩展not_run_no_candidate | 115.48秒 |

两方法都没有可交付候选进入独立核心/隐藏/766节点扩展执行验收；不能写成“隐藏测试失败”，更不能把内部目标测试通过当作独立验收成功。机器报告每组0/1只描述这一个已读dev任务，不能外推为真实缺陷总体成功率。

- 总预留/返回：21/21，额度错误和API错误事件0。剩余16次未使用；这不是再选题或重跑同槽位的授权。
- API usage已返回：输入289,928 tokens，completion 51,859 tokens，总计341,787；single-shot为5,220/33,614，Repair为284,708/18,245，Review无调用。按usage计账，不按正文字符数估算。
- usage_known=true；人民币费用和真实HTTP传输次数仍为unknown/null，不填0，不把ModelClient计数冒充HTTP计数。
- 两份supervision均completed/returncode0/cleanup clean。完整Agent实际3个容器阶段：基线failed；两次目标bool测试passed；容器清理错误0。未执行Review或最终Verifier，因为此前门禁已经拒绝。

## 4. 问题、证据和处理边界

### 4.1 单次补丁：模型输出的hunk不完整

已保存响应stop_reason=stop、正文1,253字符、无tool_calls，并非解析器因正文大小或截断状态拒绝。对原响应做一次仅本地extract_patch诊断，得到PatchRejected: incomplete hunk。第3个hunk声明旧6/新16行，实际旧6/新15行；前两个hunk计数吻合。

处理：保持format_error原结果，不自动补一行、不修hunk计数、不追问模型，也不修改验收解析器来放过它。当前仅证明格式无效，未替模型补完后验证修复逻辑。

### 4.2 完整Agent：Windows编辑工具造成整文件换行变化

已定位到src/pyrepair/tools.py的ReplaceTextTool：read_text后write_text未显式保留原换行；Windows写回与WorkspaceSession保留字节换行的Diff组合，造成LF→CRLF整文件差异。证据来自**本次真实运行保存的副本**，不是推测模型改了上万行逻辑：

| 已存副本 | 文件行数/换行 | 原始Diff变更行数 | 仅诊断用LF规范化后的逻辑变更 |
| --- | --- | --- | --- |
| 冻结原版/基线 | 5,630行，全LF | 0 | 0 |
| 第2个容器快照 | 5,651行，全CRLF | +5,651/-5,630=11,281 | +26/-5=31 |
| 第3个容器快照 | 5,644行，全CRLF | +5,644/-5,630=11,274 | +14/-0=14 |

第1attempt本身工具额度8次耗尽，同时其反馈显示超大Diff11,275行。第2、3attempt直接policy_rejected，原因too_many_changed_lines超过80行。两次内部目标测试虽然通过，但之后仍被门禁拦截，未进Review和独立验收。

处理：只在内存做换行规范化对照，写diagnostics.json；**没有**重写原补丁、快照、分数或门禁，没有增大80行阈值，也没有改生产源码。下一步建议先离线修复编辑工具保留换行，加入大于40行LF文件的一处替换回归（单元小文件不足以暴露该规模问题），再重新冻结代码。修复属于新版本，不回填本次成绩。

### 4.3 报告模板和时限说明

机器summary.json确实记录execution_mode=smoke，但kind/limitations沿用通用对照措辞，其中three repeats不适用于本轮。原机器报告不覆盖，本页明确仅1题×1trial×2方法；下一次入口修订应补smoke专用标题/限制文案测试。

观测到single-shot完整complete耗时160.31秒，虽然客户端timeout配置为90；不能把这个配置写成已验证的每次完整调用90秒硬壁钟上限。本轮未提高配置，worker总限仍1800秒。没有额外传输时间戳，具体网络/服务端行为未核实，不猜测原因。

一个只读诊断命令曾因PowerShell的foreach语句直接接管道而ParserError；改为数组收集后输出。该错误没有模型调用、任务修改或成绩影响，属于排查命令问题。

## 5. 恢复、安全与后续

已在清除进程key、禁止credential_getter的条件下实际resume，仅本地重放：预留数仍21，journal/calls/summary/report四份文件SHA256逐字节不变，新增模型调用0。证据resume-verification.json。真实运行后再次verify原20题包通过，源码和任务身份仍一致，HEAD仍558cf66de7fd5225c1900446a1410247fab78399。

原始结果不删除、不覆盖，不把本地换行诊断当作修复成功，不补跑或换目录刷新同槽位。未做Git提交/合并/推送/PR；正式120槽位/2,220预留未获批准、未执行。

建议顺序：先另行确认离线修复换行工具和smoke报告文案 → 完整回归并冻结新版本 → 另批新的单题真实冒烟 → 通过接线检查后再另批正式实验。当前两个方法未交付补丁且存在已证明的工程干扰，不宜直接启动正式付费批次。过程见[工程日志](evaluation-v2-engineering-log.md)步骤57–58。

## 6. 后续离线修复检查点（不回填本次成绩）

用户随后批准先离线修复换行问题并补回归，已完成：新增20项边界测试，完整离线950项通过，显式Docker/FakeLLM集成3项通过；小补丁不再因整文件换行变化被门禁误拦。未放宽Diff/Policy、未修正本次模型hunk、未补跑真实模型。旧四份核心结果摘要不变，21次预留不变。

当前源码已不同于本次smoke所用冻结包，实际verify会拒绝旧包；需要新冻结及新的真实运行授权。本次两方法失败保持原样，smoke模板文案尚未修改。完整边界和证据见[换行修复验收](replace-text-newlines-offline.md)与工程日志步骤59。

随后用户另行批准的报告修复和新冻结也已完成，见[最新离线检查点](report-scope-refreeze-offline.md)：新报告按实际计划说明任务/轮数，旧机器报告仍不覆盖。新包20题校准及120槽位脚本恢复通过；没有据此重跑本次两槽位或产生新模型成绩，未来真实smoke仍需新授权。

2026-10-24另获人的新授权后，[新包smoke](controlled-live-comparison-smoke-after-fixes.md)独立运行：8/37次预留，完整Agent核心/扩展通过，单次候选路径拒绝；并发现需公开评分路径约束的协议缺口。本页旧smoke两方法失败不覆盖，不混合统计，不使用旧剩余额度。
