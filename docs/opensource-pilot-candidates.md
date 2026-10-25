# 真实开源缺陷试点：候选核对与接入建议

日期：2026-10-19；状态更新：2026-10-20。**[正式设计](superpowers/specs/2026-10-20-opensource-pilot-design.md)已获批准，按[实施计划](superpowers/plans/2026-10-20-opensource-pilot.md)推进。归档读取、宿主/付费入口保护及两题任务包已实现；当前为 assets_prepared，见[准备记录](opensource-pilot-assets.md)。尚未运行上游测试、Docker 或 Agent。**

本轮沿用 evaluation-v2 独立工作区。固定 GitHub 来源已下载并逐文件核验；上游 Python 尚未执行。自有测试已检查真实文件字节与补丁应用，但没有导入这些源码。没有模型请求，没有提交、合并、推送或 PR。这份文件不是性能报告；下文拟定验收仍需 Docker 实测。

## 1. 为什么选这两题

建议先用两道依赖较少、来源可追溯的真实缺陷验证接入链路，再扩展任务量。不是为了用两题证明通用修复能力。

| 试点 | 真实缺陷 | 覆盖的能力 | 难度边界 |
| --- | --- | --- | --- |
| more-itertools / seekable | 关闭历史缓存时，peek 和 bool 会消耗本应保留的元素 | 迭代器状态、方法间影响、重复调用与边界输入 | 单源文件、小补丁；真实不等于大型复杂任务 |
| boltons / addlist | 一次性迭代器被遍历两次，导致容器内部记录不一致；两个模块都含有此实现 | 定位重复实现、跨两个模块修复、公开接口一致性 | 两文件同源缺陷，不包装成复杂架构重构 |

两题已被本次开发过程阅读过，应标为 opensource / capability / dev，不标成未见 holdout。公开历史缺陷也不能证明模型训练时未见过。

## 2. 候选 A：more-itertools 的零缓存窥视

上游来源：[Issue #1268](https://github.com/more-itertools/more-itertools/issues/1268)、[已合并 PR #1269](https://github.com/more-itertools/more-itertools/pull/1269)。

- 缺陷基线：`1da45ae4b61a832ed080f08a8833784aad0a9534`。
- 修复提交：`b5e3886a37209bb880f17d82fbf4ba00ece0e41e`。
- 基线取该合并提交的**第一父提交**，不是 PR 页面可能变化的 base 字段。
- 上游生产修改：`more_itertools/more.py` 中的 `seekable.peek`。
- 上游新增两项测试：`SeekableTest.test_maxlen_zero_peek_does_not_drop_items` 与 `test_maxlen_zero_bool_does_not_drop_items`。
- 固定基线的项目配置声明 Python >= 3.10，没有声明运行时第三方依赖；测试文件使用 unittest。实际 pytest 收集及 Python 3.13.5 兼容性仍需本地验证。
- [固定版本 LICENSE](https://github.com/more-itertools/more-itertools/blob/1da45ae4b61a832ed080f08a8833784aad0a9534/LICENSE) 为 MIT 文本；导入资产时保留原文件与版权信息。

具体行为：`seekable([10, 20, 30], maxlen=0)` 在调用 peek 后，后续迭代仍应包含 10；连续 peek、bool 不能吞元素，历史缓存仍应为空。这是上游问题描述和代码表明的合同，不是我们追加的业务需求。

拟定验收：

1. 公开最小复现让 Agent 能看到失败；原有源码和测试仍保留。
2. 私有验收覆盖连续 peek、bool 与 next 交错、空迭代器、0/False/None 等有效元素、缓存为空和默认缓存行为。
3. 使用上游生产修复作为参考补丁，测试变更单独管理，不把整份 PR Diff 当作待应用的生产补丁。
4. 人工构造“只对真值元素恢复”的不完整补丁，尝试校准为公开测试通过而隐藏测试失败；是否合格以真实运行结果为准。
5. 不把 pytest 收集到的测试数量等同于上游 unittest 加载的全部测试：test_more.py 的 load_tests 会加入 doctest，pytest 路线需要明确记录是否另行执行这些 doctest。

参考：[修复 Diff](https://github.com/more-itertools/more-itertools/commit/b5e3886a37209bb880f17d82fbf4ba00ece0e41e)、[基线项目配置](https://github.com/more-itertools/more-itertools/blob/1da45ae4b61a832ed080f08a8833784aad0a9534/pyproject.toml)。

## 3. 候选 B：boltons 的一次性迭代器

上游来源：[已合并 PR #458](https://github.com/mahmoud/boltons/pull/458)。

- 缺陷基线：`d45cc414e33aa4e08a73e0993574df4397e2e9db`。
- 修复提交：`a1ea1030ed85137e999c0bd9b11d16368d3ab241`，父提交正是上述基线。
- 上游生产修改：`boltons/dictutils.py` 与 `boltons/urlutils.py` 的 addlist。
- 新增上游测试：`tests/test_dictutils.py::test_addlist_iterator`。
- 固定配置声明 Python >= 3.7；相关测试依赖 pytest，未声明运行时第三方依赖。实际运行兼容性待验证。
- [固定版本 LICENSE](https://github.com/mahmoud/boltons/blob/d45cc414e33aa4e08a73e0993574df4397e2e9db/LICENSE) 是带三项条件的 BSD 风格许可文本。GitHub API 的机器标签为 NOASSERTION，所以保存原许可全文，不只相信 API 标签。
- 上游 PR 明确披露使用 AI 辅助准备补丁。保留这一来源信息，不将上游修复描述为本项目独立发现或编写。

具体行为：将生成器交给 addlist 后，keys、getlist、get、元素数量应该相互一致；空生成器不应创建一个“存在但没有值”的键。URL 查询参数使用的实现也受影响。

**发现的覆盖缺口：** 上游生产修改涉及两个模块，但新增回归测试只在 test_dictutils.py。不能仅复制该测试就宣称已验证多文件修复。

拟定验收：

1. 公开复现 dictutils 的失败，公开任务说明同时描述容器及 URL 查询参数接口的正常行为。
2. 私有验收检查 QueryParamDict、空迭代器、重复键追加及不同一次性迭代器。
3. gold.patch 保留上游两个生产模块的修改。
4. wrong.patch 只修 dictutils，留下 urlutils 未修；该补丁明确标为人工构造的校准反例。只有实际公开测试通过、隐藏断言失败后才能认定校准有效。
5. 原有 dictutils/urlutils 测试作为回归依据；完整上游测试树保留，实际执行范围单独列出，不能把局部回归叫作全仓回归。

参考：[修复 Diff](https://github.com/mahmoud/boltons/commit/a1ea1030ed85137e999c0bd9b11d16368d3ab241)、[基线项目配置](https://github.com/mahmoud/boltons/blob/d45cc414e33aa4e08a73e0993574df4397e2e9db/pyproject.toml)。

## 4. 三种接入方式

| 方式 | 收益 | 代价与限制 | 建议 |
| --- | --- | --- | --- |
| 保留固定提交的仓库快照，新增独立测试覆盖层，容器中离线验收 | 能保留真实代码环境、明确来源与执行边界；可复用现有评分协议 | 需要隔离执行环境及评测适配 | 推荐 |
| 抽取几个函数改成独立小样例 | 制作最快 | 只能叫“源于开源缺陷的简化题”，不能证明真实仓库修复 | 不作为本阶段主方案 |
| 立即接入大型标准基准与大量仓库 | 范围更广 | 环境、Issue 输入、预算和排障范围明显扩大 | 两题链路跑通后再评估 |

“完整仓库快照”指保留固定提交的文件树与布局，不是保留 Git 历史。运行副本不提供 .git、参考提交、PR 的修复解释、标签、gold.patch 或私有测试。许可与必要版权信息保留。任务 overlay 的新增/排除文件逐项登记并绑定摘要，不悄悄改写上游源码。

## 5. 预计改动在哪里

首轮不改 `src/pyrepair/coordinator.py` 或 `repair_agent.py`，不放宽 Policy Gate，不改 Review 提示词。

- 新增独立真实任务 manifest 与资产目录，不改旧 18 题、旧 Review 集及其成绩。
- 新增来源记录：仓库、完整提交 SHA、上游问题/PR、许可、文件摘要、overlay、参考及错误补丁来源。
- 在 `benchmarks/evaluation/` 增加可替换的隔离测试执行适配。沿用 grade.json、pytest probe、F2P/P2P 和错误分类；运行路径由容器映射，不把主机绝对路径硬编码进去。
- 首轮只做基线、参考补丁、错误补丁的离线预检；暂不将这两题交给付费 Agent。
- 当前 `grading.py` 接收 test_runner，但 `validate_case` 的基线与后续验收仍默认走宿主执行，需补齐一致的适配入口，不能只在一个阶段套容器。
- 当前 manifest 已接受 source_kind=opensource，不需要为这个标签重写任务模型。
- 是否需要其他兼容修正，由真实 RED/GREEN 检查决定；不预先承诺“主体代码绝对零修改”。

后续真实 Agent 执行另行设计：模型通信留在可信侧，源码/测试执行放到无密钥的隔离侧。当前 TestRunner 复制进程环境，agent_worker 又需持有 API Key；不能直接将现有 live 流程用于不可信代码后声称已实现凭据隔离。

## 6. 执行边界与当前环境

只移除环境变量、创建临时目录或禁用 pytest 自动插件，都不是操作系统沙盒。

本轮只检查到：Docker 不在命令路径，两个常见 Docker Desktop 路径不存在。这不证明机器上绝对没有其他 Docker/远程运行环境；也未运行服务探测或安装命令。

建议执行边界：

- 单独、无主机凭据的容器；测试阶段禁网。
- 不挂载用户目录、.git、Docker socket 或其他项目；只提供当前任务所需副本。
- 镜像/依赖固定版本并记录摘要，优先直接从源码导入，避免执行不必要的打包安装钩子。
- 非特权运行，限制资源、运行时长和输出量；记录退出码、超时、收集错误和全部测试证据。
- 旧 Windows 结果与未来容器结果分开记录，不能忽略 Python/pytest/操作系统变化。
- 容器也不是绝对安全保证，执行前仍需审查仓库配置、conftest、导入行为和依赖。当前仅完成部分静态核查，不能标注“全仓安全审计通过”。

**在用户确认环境方案、可用隔离环境完成核验前，不在宿主机执行这些外部仓库测试，不自行安装 Docker/WSL，也不启动新付费实验。** 可以先实现不执行外部代码的来源下载、摘要核验、任务包组装及自有离线测试。

## 7. 进入真实模型评测前的门槛

每题都必须实际证明：

1. buggy 失败来自业务断言，而非缺依赖、收集失败或配置问题。
2. 指定 F2P 修复前失败、参考修复后通过；P2P 修复前后均通过。
3. 参考修复通过全部指定公开与隐藏验收。
4. 不完整修复公开通过、隐藏失败，证明隐藏测试确实能抓住漏修。
5. 原始快照/运行输入/私有资产边界和哈希校验有效，运行日志可重放。
6. 环境与适配故障单列，不偷偷删题、不记为模型修复错误。
7. 新结果使用独立报告；没有模型请求就不产生模型性能结论。

截至 2026-10-20：上游来源与修复关系已核对，本地上述七项验收均未执行。方向已确认；下一步审核正式设计，再制定实施计划。本文保留选题依据，不代替后续真实验收记录。
