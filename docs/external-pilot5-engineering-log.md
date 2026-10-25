# 五题真实开源缺陷评测工程记录

本日志只记录新增五题阶段，不改写已有二十题开发成绩。密钥不写入日志。离线检查、真实模型运行和性能结论分开记录。

## 2026-10-25 / 步骤 1：确认边界并核对候选来源

- 目标：新增五道缺陷、至少三个此前未纳入本项目评测的仓库；固定 Agent 后比较两方法，每题各三次独立运行。当前只做设计及来源调查。
- 版本：复用已附加的 evaluation-v2 managed worktree，起点为 `7c9508e63ff3a133e7599b3a2ca439e935f10295`。提权只读 Git 检查确认工作区原本无变更；未改主 checkout 或个人材料。
- 现象 1：普通受限命令中的 `git status` 报 `this operation must be run in a work tree`，即使指定 git-dir/work-tree 仍相同。
- 处理 1：在权限流程允许后，用原路径执行只读 `git -C ... status --short` 和 `git log -1`，得到干净状态及预期提交。未改 ACL、仓库所有者或 Git 配置。这只解决本次读取，不宣称已修复受限环境的 Git 行为。
- 现象 2：部分上游更新日志引用的 PR 不是直接合并记录，不能只凭日志拿它的 base SHA 当缺陷版本。
- 证据 2：GitHub API 显示 python-dotenv #663 与 Click #2907 均为 merged=false；Click #2897 的 pulls 路由为 404，而 #2930 的正文将其作为被修复问题引用。
- 处理 2：排除含糊来源；核对五个候选的 merged、merge_commit_sha、合并日期及固定提交第一父 SHA。完整清单见 [候选核对](external-pilot5-candidates.md)。
- 现象 3：正式比较入口硬编码二十题；来源登记固定两题；新候选均为 src 布局，当前容器入口只显式加入仓库根。仅增加 manifest 不足以完成接入。
- 处理 3：在 [书面设计](superpowers/specs/2026-10-25-external-pilot5-design.md) 中要求独立外部入口、明确导入根、来源路径核验及新环境身份；不放宽旧入口，不改 Agent 本体。
- 验证：已读取现有相关代码并通过 GitHub PR/commit API 核对五个候选；未下载或执行候选源码，未运行新 Docker 测试，未进行 DeepSeek 请求。本步骤不需要将整套历史测试再跑一遍。
- 当前结论：五题来源候选明确，运行可行性尚未验证。设计文件待用户审阅，尚未开始实现或产生新性能结果。
- 下一步：审阅书面设计后制定定向实施计划，再准备固定任务资产、Docker 预检和正式运行。三次独立重复不共享之前对话、补丁或私有评分。

## 2026-10-25 / 步骤 2：改为先完成全部题集，再统一评测

- 用户决定：先完成三十道开源题的建立和合并，再补自建任务；全部题集建立、合并和冻结后，才统一执行 DeepSeek。取消先跑五题的顺序。
- 数量核对：遍历现有所有 `manifest*.json` 的 `source_kind=opensource` 任务，按唯一 ID 去重后只有 `os_more_seekable_1269`、`os_boltons_addlist_458` 两题。不同 manifest/revision 不能重复计数；三道多文件任务属于十八道自建题。
- 新口径：开源累计三十题等于已有二题加五道来源候选加二十三道尚待筛选题；自建十八加二等于二十。最终统一五十题，两方法各重复三次，共三百个正式方法运行。
- 处理：新增 [统一题集设计](superpowers/specs/2026-10-25-unified-goldset50-design.md)，给旧五题方案和候选表加范围变更说明；未删除历史来源证据。统一管理仍保留 dev/holdout 与自建/开源标签，不把已有任务改称未见任务。
- 验证边界：本步骤只核对 manifest 与更新设计；没有准备新的任务资产、没有改 Agent、没有 Docker 新验收或 DeepSeek 请求。新成绩仍不存在。
- 后续：审阅新方案后先实施三十道开源题的建设与离线校准，再完成自建题并冻结整体实验；不得把旧成绩和新增任务结果拼成同一新批次。

## 2026-10-25 / 步骤 3：三十题来源目录与只读校验

- 目标：完成来源登记的最小可用交付，不将候选登记包装成 gold set 通过验收。用户已批准统一方案并要求开始；本步按 [来源登记计划](superpowers/plans/2026-10-25-unified-goldset-sources.md) 在原独立 worktree 内执行。
- 来源结果：通过 GitHub PR/commit API 核对三十个来源的已合并状态、修复 SHA、全部父提交及第一父基线；两个旧 dev ID/revision 与原 manifest 对照，二十八个新增来源暂列 holdout 候选。
- 分布：packaging 十二、Click 八、python-dotenv 六、more-itertools 三、boltons 一；五个仓库。每条保留参考源码修改文件及上游修改的测试文件，但不把参考文件当作公开编辑白名单。
- 选题排除：Click #3201 未直接合并且与选中的 #3225 对应同一问题，不能再算一题；Click #2991 虽合并但原作者明确说明复现不稳定，本批不纳入。此前 #663/#2907/#2897 的排除记录继续保留。排除均发生在任何新增模型运行之前。
- 交付：`benchmarks/opensource_catalog30.json`、`benchmarks/evaluation/source_catalog.py`、`benchmarks/inspect_source_catalog.py`、`tests/test_source_catalog.py` 与 [人类可读目录](opensource-catalog30.md)。未改旧来源白名单，不提供新的执行权限。
- TDD：校验器测试先因缺实现失败；实现后先通过五十三项。新增真实目录及split类型反例出现三项预期失败，补清单及严格类型校验后五十六项通过。CLI先缺实现失败，再通过六十五项；审查修复后新功能六十七项通过。
- 环境问题 1：受限运行时 pytest 原临时目录不能创建，初次基线七十六项setup错误。单项复现定位到 `C:/Users/Jerry/.pytest-temp/pytest-of-Jerry` 的编号目录创建。改用项目 `tmp/` 下新建的独立 `PYTEST_DEBUG_TEMPROOT` 后，同一基线七十六项通过；未改源码、ACL或验收条件。
- 环境问题 2：Ruff 默认缓存目录拒绝创建临时文件，改用 `--no-cache` 进行检查和格式化，不改目录权限。
- 代码审查问题：只读子代理指出五千位整数和二万层嵌套JSON在512KiB限制内仍可能触发普通ValueError/RecursionError，使CLI未受控退出。主代理独立复现为两项失败，再在解析边界保留已有CatalogError，并将其他解析资源异常转换成CatalogError。两项回归已通过，审查者复核关闭P2。
- 测试记录问题：最初大输入参数自动成为超长pytest ID，产生噪声并影响fixture准备；给参数设置 `long_integer`、`deep_nesting` 短ID后正常复现目标错误。没有为此修改生产行为或降低输入边界测试。
- 代码规范：时间戳先由正则限定显式UTC，再用Python>=3.11支持的 `datetime.fromisoformat` 校验日期；按Ruff检查去掉多余时区字符串替换。只格式化新增文件。
- 最终验证：来源目录、新旧归档/来源保护、入口策略和任务模型五组定向测试共 **192 passed，0 failed，0 errors**，4.59秒；新功能其中67项。三份新增Python文件Ruff检查和格式检查通过。没有为本次来源目录改动重跑全部历史长实验。
- 证据：`D:/Project/PyRepair Agent/tmp/goldset30-verified-c822fb79035349e6954391e04e016061/focused.xml`；只读CLI输出source_count=30、repository_count=5、dev=2、holdout=28、ready_for_model_evaluation=false。
- 冻结检查：相对 `7c9508e63ff3a133e7599b3a2ca439e935f10295`，`src/pyrepair/` 和 `pyproject.toml` 无差异；未修改旧manifest、旧资产或旧结果。来源校验属于新增评测基础设施，不把新运行时伪装成旧冻结包。
- 提交粒度：来源校验、清单和只读入口共享同一测试文件，作为一个自洽来源登记交付提交，避免中间提交引用尚未入库的清单或CLI。没有扩大到资产/模型执行。
- 当前结论：来源目录单元完成；新增二十八题的源码字节、许可、容器环境和行为验收尚未完成。没有新的DeepSeek请求、Docker执行、推送或PR。
- 下一步：准备固定源码归档、许可及参考生产补丁，再建立公开复现、隐藏边界与不完整补丁；三十题完成后再补两道自建题，五十题全部冻结后才做统一模型评测。
