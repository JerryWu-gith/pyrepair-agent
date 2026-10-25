# 五题真实开源缺陷评测工程记录

本日志保留最初五题调查历史；自步骤 2 起范围改为统一五十题建设，不改写已有二十题开发成绩。密钥不写入日志。离线检查、真实模型运行和性能结论分开记录。

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

## 2026-10-25 / 步骤 4：三十题固定源码、许可和生产参考补丁

- 目标/边界：执行 [参考资产计划](superpowers/plans/2026-10-25-catalog-reference-assets.md)，只下载和核验数据，不运行上游代码、Docker或模型。Agent、pyproject、旧任务、旧严格归档读取器和历史成绩不改。
- 来源：按30题目录去重后有55个repo/commit。固定commit/tree JSON经已连接GitHub只读接口取得，归档来自受限codeload HTTPS。元数据镜像不保存认证信息，来源可追溯但不是签名证明，也不声称抵抗恶意宿主全面重写证据。
- 新工具：`catalog_source_cache.py`核验和复用版本；`catalog_references.py`生成纯生产参考补丁并提供显式resume/离线verify；CLI `prepare_catalog_references.py`无模型或上游执行参数。
- TDD：源码缓存先缺实现失败，再12项通过；批次测试最初引用了错误的顶层测试模块，核对现有tests包后改用`tests.test_catalog_source_cache`，正常观察到两个缺实现断言失败；实现后23项通过。
- Windows问题：部分测试在目录rename报间歇WinError5，提权和缩短路径后仍出现，具体锁定进程未确认。用自有文件系统边界反例确定不能依赖目录rename，再改为验证后独占新目录、最后写完成标记；不降低Git/ZIP校验，不改ACL。没有标记的目录不能复用，不自动删除不完整数据。
- 首轮实际准备：22题完成，遇到python-dotenv `docs/changelog.md` 的归档符号链接被旧安全规则拒绝。run报告保存source_error；未伪装成功或静默重试。首轮失败ZIP只在暂存目录，未另存永久归档，不声称保存了其原始ZIP。
- 用户决定：明确批准保留六道python-dotenv候选，仅对文档链接作受限元数据处理。新增`catalog_document_links.py`，旧`opensource_archive.py`和`opensource_assets.py`未改。
- 链接边界：只允许docs/下md/rst/txt文件指向内部普通文档，原始链接目标字节参与Git blob、大小和SHA256核验；生产、测试、越界、绝对、悬空和链接链拒绝；source中没有实际链接。原ZIP/原tree保留，归一化只在内存，离线verify不写暂存文件。
- 审查修复：只读审查提出EOF缺换行可能生成无法应用的补丁。主代理构造具体反例，断言失败；新参考入口补标准EOF marker，旧helper不改。实际已准备22题没有缺EOF换行。新文档链接/EOF反例初为2 failed，修复后通过；只读验证不应创建临时目录另有RED/GREEN回归。最终受限链接审查无新增P1/P2。
- 继续准备：按原目录身份显式resume，先重验并复用22题缓存，再完成余下任务。两份run报告保留；旧失败report SHA256仍为`0c325128403482635f7eb99d8c02059a3bf4524a7405dd04ba03e49ec5f9e600`，无修改。
- 实际结果：30/30参考记录、55个来源版本；跨版本6044个普通文件、55,400,734字节；44条文档链接元数据；7份不同许可内容。普通文件集合、Git blob、归档摘要、许可和参考补丁绑定均已核验；不把这些数字当成模型性能。
- 独立验证：`--verify-only`退出0、30份reference和55份版本通过；Git只读`apply --check --no-index`全部30份补丁通过；定向工具/旧保护回归 **226 passed，0 failed，0 errors**，7.32秒；Ruff和格式检查通过。没有重跑全部历史长实验。
- 证据根：`D:/Project/PyRepair Agent/tmp/catalog30-reference-20261025-2c26859/`；初轮/继续工具摘要、元数据、缓存和两份run报告均在；JUnit为`D:/Project/PyRepair Agent/tmp/r-ff4ed8b1/focused.xml`。规范目录身份SHA256为`124ea139447523fe1b4836bde9c3a82f176a4db11ef3ada93b29e0bfb56ae3e4`。
- 当前结论：`references_prepared`，不是`calibrated`，ready_for_model_evaluation=false，model_calls=0，upstream_code_executed=false。完整源码和原始准备证据只留本地，不默认提交或发布。
- 遗留：新增题的公开复现、隐藏边界、回归范围、不完整补丁、src导入和Docker环境校准仍需实施；许可分发义务未在本步宣布通过。完成这些后再补两道自建，冻结五十题，再统一DeepSeek评测。

## 2026-10-25 至 2026-10-26 / 步骤 5：装配三十题并启动 Docker 校准

- 目标：执行[测试资产与校准计划](superpowers/plans/2026-10-25-catalog-task-calibration.md)，保持生产 Agent 冻结，无新模型调用。
- 覆盖层：三组子代理各自只写数据模块，静态比较真实 buggy/fixed 源码和测试。缓存 commit JSON 实际只有 sha/parents/tree，没有 files/diff；因此依据固定快照中的测试文件差异，不声称读过不存在的元数据。
- 新装配器：先独立复核来源与参考补丁，再检查覆盖层 AST、节点和 mutant 锚点；只创建全新输出，私有补丁/隐藏测试不进入公开树，编辑范围为生产包现有受允许 Python 文件。已有两题因布局/导入/范围变化进入新 revision 3，旧 revision 2 保留。
- TDD：装配器先观察到缺实现断言失败，再由真实自有 ZIP/Git 字节夹具验证隐藏隔离、全包 ACL、错节点/错锚点/越界拒绝、引用篡改拒绝及不覆写；7 项通过。未宿主执行任何上游 Python。
- 导入问题：自有 src/packaging 小仓库实际误用环境同名包，owned_answer 不存在；新增只读导入配置、候选模块缓存清除和来源检查后，9 项导入测试及 18 项原入口测试通过。可信 pytest/probe 保持先加载，未把来源检查当作恶意源码防护证明。
- 依赖：dotenv CLI 缺 Click；核对官方 PyPI Click 8.3.0 wheel 摘要，新增固定依赖并构建新镜像/新锁。受限 PowerShell HTTPS 请求被拒，官方元数据通过可用只读网页接口核对，实际构建准备依权限流程再次按官方元数据校验。旧锁不覆写。
- 工具回归：新增依赖后测试夹具仍固定旧依赖集合而拒绝新锁，更新完整协议夹具；受限环境的硬链接创建 WinError 5 通过 scoped 权限运行解决，未跳过安全测试，88 passed。Ruff 仅整理本次新文件。
- 新环境：镜像 `sha256:eb08da21b62bf636ca21adebc9ae298d355d440166522042444c7fe1116f790f`；九项真实自有安全/超时检查全部通过，来源与路径详见[校准记录](opensource-task-calibration.md)。
- 资产问题：静态审查发现 BOM、empty-get、Click EOF 首版 mutant 只破坏 P2P，未暴露隐藏 F2P；改为明确的 grammar/插值/未终止行遗漏，不放宽评分器。首版 a01 不覆盖，修正后新装配 a02。
- 中断：审批服务曾报告额度限制，首次真实校准命令未执行；子代理后续修正也未完成。2026-10-26 用户继续后主代理完成三个 mutant 修改并重新发起，未自动冒充已运行。
- 当前证据：两版均装配 30 题；首个 packaging hash 任务真实校准 valid；a02 三十题校准已启动，未宣布全部验收。首题和批次目录分别保留。现有源/引用/装配/导入定向测试 117 passed；最终回归与审查尚待完成。
- 审查发现并修复 P2：输出含 `..` 别名可绕过 lexical 重叠检查。用自有缓存夹具观察 DID NOT RAISE，再在拒绝链接后 resolve 两路径，8 个装配测试通过；只读复审确认关闭。此次只改装配工具，不改变已启动校准的容器 harness/锁。
- a02 暴露 boltons mutant 过弱：baseline 和参考均符合预期，但 mutant 也 passed。检查真实 urlutils 对 dictutils 的复用及旧 private/opensource_v2 资产，确认应采用已登记的只物化新键边界，而非旧 v1 的单文件修复。修正注册配方，不修改生产源码或评分器，旧失败保留；待新资产单独校准。
- a02 整批结果：30 candidate，29 valid、1 invalid，无环境/导入/收集技术错误；无效为上述 boltons 样本。a03 新资产只改该人工补丁和说明，仅重验该题，结果 valid。
- 新增只读 `catalog_calibration.py`：先观察缺实现失败，再 8 项自有数据测试通过；复核资产指纹、环境、基线断言、参考双通过、mutant 公开过/隐藏 F2P 拒绝及完整性/清理/收集。不同旧指纹不能 qualify 新题，同指纹 invalid 冲突拒绝，不能选择最好记录。只读审查无 P1/P2。
- 最终索引：a03 `calibration-index.json` 对 30 个最终指纹全部验证通过，复用 a02 未变 29 题与 a03 修正 1 题；87 F2P + 68 P2P = 155 个登记节点。五仓库分布为 more-itertools 3、boltons 1、packaging 12、Click 8、python-dotenv 6。不把节点数当题数或模型成功率。
- 环境锁 SHA-256 为 `788e6a18f3d4f3683444b4bd4407723ff6531b1bb31ed60e056089f6a517b86e`。生产 `src/pyrepair/` 和 `pyproject.toml` 与冻结基线无差异。旧记录及旧结果未覆盖，无新 DeepSeek 请求；ready_for_model_evaluation 仍 false，统一五十题尚未冻结。
- 最终工具回归：232 passed、0 failures/errors/skips，18.02 秒；JUnit `D:/Project/PyRepair Agent/tmp/r-33625427/focused.xml`。Ruff 和 8 个选定新文件格式检查通过。没有重复整套历史模型实验，三十题的校准重跑仅限修改后的 boltons 一题。
- 后续：记录本轮所有无效题及原因，只修评测合同/环境/人工补丁；三十题通过后再补自建两题并冻结五十题。没有 DeepSeek 请求、推送、PR 或简历新成绩。
