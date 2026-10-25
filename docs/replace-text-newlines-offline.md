# 编辑工具换行修复：离线验证

## 批准范围与实现约束

2026-10-23，用户在真实冒烟诊断后回复“继续”，批准先离线修复换行问题并补回归测试；不含真实模型补跑、正式实验或 Git 发布。复用 evaluation-v2 工作区，保留原始冒烟、冻结包和失败记录。

修复仅落在 `ReplaceTextTool` 的文本替换边界：匹配模型读取到的逻辑文本，接受 LF/CRLF/CR 的等价换行；除换行外仍是字面匹配且必须唯一。未替换部分原样保留；新文本的换行优先沿用命中区间的首个换行，否则用原文件首个换行，没有换行时默认 LF。混合换行不全文件规范化，也不承诺替换区间内逐行保留不同换行。是否保留末尾换行取决于原后缀和明确传入的新文本，不主动追加。

不改变 `WorkspaceSession.snapshot()` 的字节敏感 Diff、不放宽 Policy 的 80 行阈值、不修模型输出的 hunk、不改变任务或评分标准。源码变化后原冻结包仅作历史证据，不能重用它的授权来执行新版本。

## 验证计划

1. 先添加行为测试，确认原实现在 Windows 上对 LF 文件产生非预期字节和整文件 Diff。
2. 最小修改编辑工具，再验证 LF/CRLF/CR/混合换行、UTF-8 BOM、无末尾换行、唯一匹配和大文件小修改。
3. 运行现有完整离线回归和显式 Docker/FakeLLM 接线测试；测试进程清除 API key，不执行模型请求。
4. 记录实际结果、遗留问题与冻结边界。旧冒烟结果不回填；新冻结、真实冒烟和正式评测分别报告。

## 实测结果

产物目录：`D:/Project/PyRepair Agent/tmp/eol-1023-097ce4d1/`。本轮没有新增模型请求；测试中的 FakeLLM 返回预设响应，不是 DeepSeek 性能成绩。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 修改实现前 RED | 最终20项反例中12失败、8通过；201行LF文件一处修改产生+201/-201 | `red-boundaries.xml`；更早17项测试的RED另存 `red-newlines.xml` |
| 修复后聚焦回归 | 72项通过，含新增20项和原编辑/工作区/门禁测试 | `green-focused.xml` |
| 完整离线回归 | 950项通过，0失败/错误/跳过，455.111秒；9项live/docker排除，不算通过 | `full-regression.xml`；另以collect-only确认950/959、9 deselected |
| 显式Docker离线集成 | 3项通过，148.17秒，exit0 | `docker-integration.xml` |
| 限定独立审查 | 无P1/P2发现；仅只读一次，不重复执行测试 | 审查范围为本轮工具函数、换行测试及大LF集成夹具 |
| 静态规范 | 3个改动Python文件Ruff check通过；2个测试文件format通过 | `tools.py`原有4处无关格式差异保留，不宣称整个生产文件format已通过 |

完整回归进程完成时，继续消息使旧终端会话句柄失效；未因此补跑整套测试。读取本轮新生成的JUnit确认950/0/0/0及455.111秒，测试进程已结束；不能据此补记未取得的终端退出码。Docker集成的退出码0已实际取得。

### 关键行为验证

- LF、CRLF、CR、多行与混合换行按约定处理；未替换前后缀字节不变，UTF-8 BOM和中文保留，没有额外末尾换行或CRCRLF。
- 除换行等价外仍按字面匹配，正则字符与反斜杠不被解释；零命中或重复命中不写文件。CRLF不可回溯拆成两个逻辑换行，不把单个CRLF误认成空行。
- 201行LF/CRLF夹具只改一行：`snapshot`及`show_diff`均为+1/-1，未经修改的Policy允许；原仓库和baseline不变，恢复后工作副本字节与原版一致、snapshot为空。
- 大LF文件的实际Docker/FakeLLM完整修复：产出仅一行删除/增加的补丁，经过Policy、Review和最终目标/全量验证；Repair4次、Review1次为假模型调用，不计真实API。另复验新子进程两方法共享额度/独立核心及扩展判分、仅清理自身CID的超时路径。

## 改动与完整性

生产改动仅为[src/pyrepair/tools.py](../src/pyrepair/tools.py)的`ReplaceTextTool`及`re`导入；新增[20项换行回归](../tests/test_replace_text_newlines.py)，加强[已有Docker完整修复夹具](../tests/test_agent_docker_integration.py)。Diff、Policy、Review、任务资产、评分器和Docker可信执行器未修改。

只读核对64份运行身份文件：在内存逆转本轮`tools.py`改动后，聚合摘要精确恢复到旧包的`796a78060098df81a350840f69b8e804915406bcd853805541885a88dd596214`，排除了其余运行文件变化；没有写回还原源码。当前运行源码摘要为`8150c4183440bc61c59286e24c25513a6a30bfaf9b8eafd4efbfdbdac626643a`，不是新冻结包身份。Python、包列表、平台和两个CLI摘要不变。

旧包身份仍为`179a568fe43142dc60c8e4caef0b209a09e18885e59ee68eb3211a7b6c9c0f07`；实际调用`verify_pack`得到预期拒绝：`comparison runtime changed; prepare a new pack`，没有覆盖旧冻结包。旧smoke的journal/calls/summary/report四份SHA256与原`resume-verification.json`逐字节相同，预留仍21次。未读取`.env`、输出key或进行Git提交/合并/推送/PR。

## 遗留与下一步

本轮完成的是换行故障的离线修复与回归，不证明真实模型现在可以修好more任务。

1. 尚未修改smoke通用报告的`three repeats`文案；旧原始报告仍保留，解释见[原冒烟记录](controlled-live-comparison-smoke.md)。该模板修订应单独补行为测试。
2. single-shot的不完整hunk仍按原规则拒绝，不替模型补齐、不放松解析器。API90秒配置也未被证明为完整调用硬壁钟时限，本轮未调整。
3. 正式运行前需以最终稳定源码重新校准/冻结，不能沿用旧包。随后另行批准新的单题真实冒烟；旧37次额度的剩余16次不授权补跑。
4. 正式20题、每方法3次的120槽位及理论2,220次预留仍未授权或执行；不发布或外推总体成功率。

过程中的排查命令失误及处理也记录在[工程日志](evaluation-v2-engineering-log.md)步骤59。

收尾复核：格式化后聚焦72项再次通过；六份更新文档90条本地链接有效、0断链；HEAD和环境锁摘要未变。机器核对摘要存于本轮产物目录`verification.json`，完整套件原终端退出码保留null，不补填未知项。

后续检查点：用户另行批准报告修复与新冻结后，smoke文案已修正、新20题包及120槽位脚本恢复已完成，见[最新离线冻结记录](report-scope-refreeze-offline.md)。本页仍保留换行阶段的原始测试和边界，不回改旧smoke成绩，也不把后续离线验证算作真实模型成功。
