# 新增五题外部真实缺陷：候选核对

日期：2026-10-25。状态：来源已核对；五题均未执行离线预检或模型评测。本文件不是成绩报告。

## 选题口径

三个仓库均未出现在已有二十题开发评测中。选择基于纯 Python 环境适配、公开行为是否清楚、上游修复是否可追溯和缺陷类型多样性，不基于被测模型能否修复。五题为偏小型工程试点，不代表完整标准基准。

## 候选清单

| 固定候选 ID | 仓库及上游来源 | 缺陷行为 | 上游生产修改 | 当前状态 |
| --- | --- | --- | --- | --- |
| `os_click_flags_2930` | [pallets/click PR #2930](https://github.com/pallets/click/pull/2930)，关联 Issue #2894、#2897 | `is_flag=True` 且指定类型时，未显式指定的 flag 值处理错误 | `src/click/core.py` | 已合并；待离线核验 |
| `os_dotenv_bom_640` | [theskumar/python-dotenv PR #640](https://github.com/theskumar/python-dotenv/pull/640)，关联 Issue #637 | UTF-8 BOM 污染第一个变量名，按预期名称读不到值 | `src/dotenv/parser.py` | 已合并；待离线核验 |
| `os_dotenv_backslash_680` | [theskumar/python-dotenv PR #680](https://github.com/theskumar/python-dotenv/pull/680)，关联 Issue #661 | 含反斜杠的值写入再读出不一致；尾部反斜杠还可能吞掉后续变量 | `src/dotenv/main.py`、`src/dotenv/parser.py` | 已合并；待离线核验 |
| `os_packaging_hash_1232` | [pypa/packaging PR #1232](https://github.com/pypa/packaging/pull/1232) | 等价版本约束的 Requirement 相等但哈希不同，集合或字典去重错误 | `src/packaging/requirements.py` | 已合并；待离线核验 |
| `os_packaging_quotes_1213` | [pypa/packaging PR #1213](https://github.com/pypa/packaging/pull/1213) | marker 字符串序列化未保留引号语义，重新解析后的条件可能不同 | `src/packaging/_parser.py` | 已合并；待离线核验 |

此处生产修改文件用于来源审计和参考补丁生成，不用来缩窄 Agent 的可编辑文件范围；公开编辑范围按整个生产包的现有 Python 文件列举。

## 固定提交

以下信息来自 GitHub PR API 的 merged/merge_commit_sha 与提交 API 的 parents。缺陷版本始终选修复提交的第一父提交，不选 PR 当前 base 字段。

### Click #2930

- 缺陷版本：`011b9f9d190c71310264e6c54bae6259f5e38a9f`。
- 修复提交：`884af5c20fdc95c9c7352df35c37273391464fb9`。
- 合并日期：2025-05-20。
- 该提交有两个父提交；上述缺陷版本为第一父提交。
- 上游 AI 辅助情况：本次已读的 PR/提交信息未建立结论，不写成人工独立修复。

### python-dotenv #640

- 缺陷版本：`68ea2d10dd8e97e6dea67c32742085f27729e3fe`。
- 修复提交：`bca6644d9aedbe287b792b756b3ae3d650cd0d3a`。
- 合并日期：2026-04-19。
- PR 明确披露由 Claude Code 辅助生成；保留来源披露，不称本项目独立发现或上游人工独立编写。

### python-dotenv #680

- 缺陷版本：`751f8c148222e58aa173c83c4e5e6cfccb2cc124`。
- 修复提交：`f7b18d9c72d1abcc2ad4023424b84f5bee30d266`。
- 合并日期：2026-08-16。
- PR 明确披露由 Claude Code 辅助生成。
- 实际生产修复跨两个文件；写侧转义和读侧解析都需要纳入任务行为与独立验收。

### packaging #1232

- 缺陷版本：`664f049980f1873c458de72a449003b83173f445`。
- 修复提交：`d8e08df11bfa50e987375546eda1f0ee3f27bd41`。
- 合并日期：2026-06-15。
- 上游 AI 辅助情况：本次已读的 PR/提交信息未建立结论。

### packaging #1213

- 缺陷版本：`2497782b2bb03812d2a12ae882a4390c61ec5061`。
- 修复提交：`5b583e309996a085ad3b5b045f3bf50a09c11b58`。
- 合并日期：2026-07-20。
- 上游 AI 辅助情况：本次已读的 PR/提交信息未建立结论。
- PR 作者曾说明可能存在其他正确实现；评分须检查公开行为合同，不要求 Diff 与上游相同，也不能凭 PR 声称参考修复覆盖了所有情况。

## 调查后未纳入的来源

| 来源 | 发现 | 处理 |
| --- | --- | --- |
| python-dotenv PR #663 | 更新日志引用，但 API 显示 closed 且 merged=false、merge_commit_sha=null | 不用作已合并修复来源；未制作任务、未请求模型 |
| Click #2897 | 被修复 PR 引用，但 `/pulls/2897` 返回 404；实际属于被关联的问题编号 | 以已合并 PR #2930 及其第一父提交为准，不将 Issue 当 PR |
| Click PR #2907 | 更新日志引用，但 API 显示未直接合并 | 不作为本批独立任务来源；未制作任务、未请求模型 |

## 正式纳入前还需取得的证据

每个候选均须取得固定版本许可证、归档摘要、逐文件 Git blob 核验、上游测试收集范围、公开复现、隐藏边界、参考修复及不完整补丁的 Docker 结果。当前没有这些运行证据，不称候选已通过验收。

如候选预检失败，须在任何正式模型运行前记录排除原因及替换来源。不得因 Agent 的正式失败而替换题目。
