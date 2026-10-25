# PyRepair 真实开源缺陷试点：任务包与 Docker 离线验收设计

日期：2026-10-20
状态：用户已于 2026-10-20 确认本书面设计，开始按[实施计划](../plans/2026-10-20-opensource-pilot.md)推进。尚未本地复现、无新增模型成绩。
工作区：evaluation-v2 托管 worktree。任务 0–4 使用 Inline；2026-10-21 用户指定后续改为 GPT-6.1-sol xhigh 子代理实施，主线程整体把控，不改变设计和安全范围。
前置材料：[候选核对](../../opensource-pilot-candidates.md)、[工程日志](../../evaluation-v2-engineering-log.md)。

## 1. 本阶段交付什么

将两道已核对的真实开源缺陷制作成可追溯任务包，在 Docker 中完成 buggy / gold / wrong 三类离线验收，沿用已有独立判分协议。

本阶段成功的含义是“这两份题能真实复现、参考修复成立、漏修能被测试发现、执行与产物边界有效”，不是“Agent 已经修好真实仓库”。

明确不做：

- 不调用任何真实模型，不沿用已经结束的 72 次授权。
- 不修改 src/pyrepair/，不改双层循环、上下文预算、Review 提示词或 Policy Gate。
- 不将生产 Agent 全部容器化；真实 Agent 的凭据隔离与工具执行接入属于后续阶段。
- 不扩大到大型标准基准，不新增其他题，不把本次两题标成 holdout。
- 不自动安装 Docker/WSL，不改系统设置或 ACL，不自动提交、合并、推送、PR 或清理历史材料。

如确实发现必须改生产源码的兼容问题，先保留失败证据并说明原因，再另行确认，不在本阶段悄悄扩大范围。

## 2. 已选定的任务与来源

| ID | 任务 | buggy commit | fixed commit | 允许修改的生产文件 |
| --- | --- | --- | --- | --- |
| os_more_seekable_1269 | 零缓存时 peek/bool 不应吞元素 | 1da45ae4b61a832ed080f08a8833784aad0a9534 | b5e3886a37209bb880f17d82fbf4ba00ece0e41e | more_itertools/more.py |
| os_boltons_addlist_458 | 一次性迭代器不能破坏多值字典及 URL 参数的一致性 | d45cc414e33aa4e08a73e0993574df4397e2e9db | a1ea1030ed85137e999c0bd9b11d16368d3ab241 | boltons/dictutils.py、boltons/urlutils.py |

来源：[more-itertools Issue #1268](https://github.com/more-itertools/more-itertools/issues/1268)、[PR #1269](https://github.com/more-itertools/more-itertools/pull/1269)、[boltons PR #458](https://github.com/mahmoud/boltons/pull/458)。

两题均标 source_kind=opensource、suite=capability、split=dev、revision=1。第一题是单文件状态缺陷，第二题是两份重复实现中的同源缺陷；不将它们宣传为复杂大型仓库任务。

保留固定版本 LICENSE 与版权声明。more-itertools 为 MIT；boltons 按固定 LICENSE 原文保存三条件 BSD 风格许可，不能只复制 API 的 NOASSERTION 标签。boltons 上游披露 AI 辅助修复，来源记录如实保留。

## 3. 方案选择与目录

采用“固定仓库快照 + 独立覆盖层 + 容器测试适配”，不采用抽取函数改写为小样例，也不立即接入大量仓库。理由及取舍见候选记录第 4 节。

新增目录与文件职责：

| 位置 | 用途 |
| --- | --- |
| benchmarks/manifest_opensource_v1.json | 两题的 v2 manifest；不改原 manifest_v2.json |
| benchmarks/eval_cases/opensource_v1/<id>/buggy/ | 保留原仓库源码、测试、配置、文档及许可的文件树，加公开复现测试 |
| benchmarks/eval_cases/opensource_v1/<id>/TASK.md | 公开合同，准备时复制到输入仓库 |
| benchmarks/eval_private/opensource_v1/<id>/ | gold.patch、wrong.patch、hidden_tests、来源与覆盖层记录 |
| benchmarks/evaluation/opensource_assets.py | 验证来源、组装任务包、计算快照和覆盖层摘要 |
| benchmarks/evaluation/docker_runner.py | 宿主侧容器生命周期与结果适配 |
| benchmarks/evaluation/container_entry.py | 固定的容器内测试入口、完整性检查及结果输出 |
| benchmarks/docker/ | 独立 Dockerfile、依赖锁与环境说明，不使用第三方仓库的构建文件 |
| benchmarks/prepare_opensource_cases.py | 显式获取/核验/组装任务；不执行上游 Python |
| benchmarks/results/opensource/ | 忽略入 Git 的下载缓存、环境锁、检查及验收原始产物 |

测试放在项目自身 tests/ 下。两份外部仓库放在现有 pytest 已排除的 eval_cases / eval_private 中，防止项目普通测试自动收集外部测试。新增 results/opensource 忽略规则先于任何下载落盘。

完整快照指文件树，不包含 Git 历史；源树与测试文件不得按模型答题表现裁剪。运行副本按既有规则排除 .git、环境文件、虚拟环境、缓存等，每项排除都记入文件清单。原快照与运行副本的差异可追溯；不得静默改写上游源码或配置。

## 4. 来源获取与内容完整性

获取步骤只读取明确的两个公共仓库及固定提交，不接受任务文本提供的下载 URL 或可执行命令。

- 使用 GitHub 固定提交归档/文件树，记录仓库、提交、tree/blob 标识、下载摘要和逐文件 SHA-256；不使用浮动分支。
- more-itertools 的 buggy 使用修复提交第一父提交，不从 PR 的可变化 base 字段推断。
- 解包前检查路径、数量和体积。拒绝绝对路径、..、盘符、Windows 设备名、大小写冲突、重复成员、符号/硬链接、子模块、设备文件及越界解包。
- 每仓库下载与解包上限各 20 MiB、单文件 8 MiB、文件数 2000；超限中止，不默默放宽。初步文件树远低于该范围。
- 原始字节保留；生成 patch 时仅在临时工作副本沿用项目已有换行处理规则。若摘要不匹配，直接停止，不覆盖旧缓存。
- 来源资产更新必须增加 revision 并建立新结果目录。
- 参考补丁只提取上游生产变更。采用当前 patching 支持的 plain unified diff，不把含测试、文件模式或 Git 额外头的整个 PR Diff直接送入 grader。
- 每个 overlay 文件标明来源：改编上游复现、改编上游回归或本项目新增；人工错误补丁不得标成模型产物。
- 固定 SHA、参考解释、标签和私有验收只在评测侧保存，不进入 TASK.md 或未来模型输入。上游已有文档照常保留，不声称消除了训练数据污染。

## 5. 两题的测试合同

### 5.1 more-itertools

公开复现使用零缓存和普通非空整数序列，暴露 peek 后原序列丢元素的断言失败。合同描述 peek、bool、next 的关系及 elements 为空的要求，不告诉模型具体修补方法。

隐藏验收覆盖：

- 重复 peek、bool/next 交错，源序列不重排、不丢失、不重复。
- 0、False、None 和空字符串也是合法元素，不能按真假值当作“没有元素”。
- 空迭代器、默认值与 StopIteration 的既有行为。
- 零缓存仍为空；默认和有限非零缓存的既有行为保持。

公开回归选择原 tests/test_more.py、tests/test_recipes.py 以及新增公开复现文件。实际收集数量、跳过和错误必须记录；不把 pytest 结果称为包含 unittest load_tests 自动加入的 doctest。本阶段不自动执行该 doctest 路径，报告明确标注“未覆盖 unittest load_tests 注入的 doctest”。

gold 使用上游生产修复。wrong 人工保留对假值元素处理不完整的版本；必须实际证明它公开通过、隐藏断言失败，才能入集。若校准不成立，记录原因并调整反例及 revision，不能临时删掉抓错的公开回归。

### 5.2 boltons

公开复现覆盖 dictutils.addlist 对非空一次性迭代器的处理，任务说明同时明确多值字典和 URL 查询参数接口的正常一致性要求。

隐藏验收覆盖：

- QueryParamDict 的同类调用和序列化/查询一致性。
- 空迭代器不能创建无值键。
- 重复键追加、不同一次性迭代器和既有列表输入。
- keys、getlist、get、多值 items 与长度之间的行为一致性。

公开回归选择原 tests/test_dictutils.py、tests/test_urlutils.py 以及新增公开复现文件。其他上游测试仍保留但不在本次指定回归范围，因此不称为全仓测试。

gold 修改两个源文件。wrong 只修 dictutils、保留 urlutils 的缺陷；它是人工构造的漏修反例。上游新测试只覆盖前者，新增隐藏验收用于验证跨文件缺口。

### 5.3 F2P/P2P 与失败证据

每题都显式列出 F2P（修复前失败、修复后通过）与 P2P（修复前后均通过）node id。节点使用真实容器收集结果冻结，不凭猜测填写成功数量。

原版必须出现指定业务断言失败；ImportError、收集失败、超时、skip/xfail 不算缺陷复现。pytest 退出码 1 本身不能证明是正确的业务失败，需核对具体节点和异常类别。评测 probe 新增异常类别字段：对旧结果可选，对本轮两题的 F2P call 失败必须存在并符合 AssertionError，且人工核对日志中的断言确实针对任务合同。缺失字段的旧结果仍可读取；不修改生产 pytest 捕获链路。

有限隐藏测试只是验收依据，不是数学意义上的完全正确性证明。

## 6. 一次离线验收的数据流

本阶段没有 Repair/Review 模型循环，只有评测器调度：

1. 校验任务摘要、固定环境锁与 Docker 可用性。
2. 从相同 buggy 生成三个独立宿主临时副本；宿主只处理文件和受限 patch，不导入外部 Python。
3. 基线副本加入公开与隐藏测试，在新容器中跑出 F2P/P2P 证据。
4. gold 副本应用参考生产补丁；先新容器执行公开测试，再另一个新容器执行隐藏测试。
5. wrong 副本应用人工漏修补丁，执行相同的公开/隐藏流程。
6. 宿主解析输出、核对运行完整性和环境身份，生成 validation.json 与汇总。
7. 保留所有失败日志；只清理本次生成且身份明确的容器/运行副本，绝不清理旧实验或其他容器。

公开执行阶段不能挂载私有测试、标签、参考补丁或完整 private 目录；隐藏阶段只加入本题明确列出的测试。可见/隐藏阶段分开容器，不能共享上一阶段的可写工作目录。

## 7. Docker 执行边界

### 7.1 环境锁与启动检查

首个环境目标：Linux/amd64、Python 3.13.5、pytest 9.1.1。依赖及传递依赖按版本和发行文件哈希锁定；不安装两个上游项目，直接从工作副本导入，避免不必要的构建钩子。

构建之前确认目标版本可获得，解析并保存基础镜像 digest；构建后记录最终镜像完整 image ID、架构、Python/pytest/依赖版本、Dockerfile/锁文件/入口摘要。只有锁文件绑定的本地 image ID 可执行。不能用 latest 或仅用可移动 tag 作为运行身份；版本不可用则记环境问题，不偷偷换版本。

镜像准备与验收分开：准备可从官方镜像源和 PyPI 获取固定依赖；validate/grade 不联网安装、不隐式 build/pull，使用 --pull=never。不将用户目录、项目密钥或整个 PyRepair 工作区作为构建上下文。

首轮只支持经确认的本地 Linux Docker 引擎。发现远程 daemon、Windows container 模式、镜像缺失或安全参数不受支持时中止，不自动切换 context/引擎或放宽限制。

### 7.2 挂载与权限

- 当前阶段唯一输入 staging 目录只读挂载 /input。
- 镜像内置固定入口与探针，不能被仓库中的同名模块替代。
- /input 复制到容器内 /work 的临时文件系统后运行测试。
- 根文件系统只读；/work、/tmp 是有容量上限的临时空间。
- 仅本次新建的空输出目录可写挂载 /output；它不含项目源码、旧成绩或其他材料。
- 非 root 用户，移除 capabilities，启用 no-new-privileges，保留 seccomp 约束。
- 禁止 privileged、host network、host PID、宿主设备、Docker socket、整个用户目录/磁盘/项目根挂载。
- 不传 API Key、不传宿主环境整包、不加载 .env；容器环境只允许固定测试配置。
- 容器测试阶段使用 network=none。其 loopback 仍可用，不将“禁外网”说成不存在任何网络接口。

只读挂载与禁网行为依据 Docker [挂载说明](https://docs.docker.com/engine/storage/bind-mounts/)及 [none 网络说明](https://docs.docker.com/engine/network/drivers/none/)；权限/根文件系统限制依据 [CLI 运行参数](https://docs.docker.com/reference/cli/docker/container/run/)。这些是设计要求，需真实环境自检，不能仅凭命令字符串认定有效。

### 7.3 资源、输出与终止

固定试点 profile：2 CPU、2 GiB 内存、内存加 swap 总限 2 GiB、128 个进程、/work 256 MiB、/tmp 64 MiB。每个测试阶段 120 秒，启动与回收各另有 30 秒上限。限制依据 [Docker 资源文档](https://docs.docker.com/engine/containers/resource_constraints/)；具体 profile 是本项目选择，不是行业标准。

stdout/stderr 合计保留上限 16 MiB，probe/integrity 各 16 MiB。输出目录上限为 8 个文件、单文件 16 MiB、总量 64 MiB；固定文件名白名单以入口协议为准，不从上游任务文本读取。每秒监测，超限终止并拒绝验收；监控有延迟，不称为硬磁盘配额。截断、文件过大、输出洪泛不能静默记通过。

启动记录唯一 run/stage ID 和容器 ID，默认不自动重启。超时、中断或输出超限时只停止该 ID；不能仅终止 docker 客户端就假设容器也结束。回收失败记入产物，不盲目重跑。禁止全局 prune、按宽泛名字清理、递归删除未经确认的目录。

## 8. 完整性与可信边界

目前 grader 检查的是宿主运行副本。采用容器内 /work 后，它无法发现容器里修改测试文件的行为；所以 Docker 后端必须另有实际执行副本证据：

- 宿主给出输入逐文件摘要，容器入口先确认复制后的文件与预期一致。
- 测试前后对所有输入文件、显式测试、配置计算摘要；新增、缺失、链接替换和修改均记录。
- 只允许声明的运行缓存/内部输出变化；即使测试放在被通用排除规则忽略的路径，显式测试仍必须单独核验。
- 所有业务输入文件在测试时保持不变；参考 patch 是运行前已应用的合法变化，不应被误判为运行期间篡改。
- 宿主要求 integrity 证据完整且 unchanged=true；pytest 全绿但证据缺失也不得通过。
- 容器停止后才读取输出。只接受固定文件名、普通文件、尺寸合规、解析结构合规、位于该新输出目录内的结果；拒绝符号链接、junction、路径逃逸、缺失或过期 ID，不执行输出文件。
- 输出携带本次随机 run/stage ID、输入/环境摘要、测试退出码、probe 与完整性结果。错误 PID、OOM 等以 Docker inspect 的运行状态辅助判断。

这能限制宿主暴露并发现预期范围内的篡改，不是恶意补丁的不可伪造证明。同一容器里的恶意 Python 仍可能干预自身测试和输出，摘要也抓不到“改后恢复”；不宣称抗对抗性攻击或绝对安全。本试点仅执行经审查的上游基线、参考补丁和人工校准反例，不执行模型补丁。

## 9. 与现有代码的接入及防绕过

1. grade_patch 继续使用可替换 test_runner；为 validate_case 增加同类入口，并将同一个执行后端传到 baseline、reference、mutant 的全部测试阶段。
2. Docker 后端提供与现有 run_tests 相同的 passed/status/returncode/outcomes/required 语义，另附执行身份和完整性信息。判分规则不因搬入容器而放宽。
3. opensource 任务必须使用受信任的 Docker 后端描述及已核验环境锁；CLI 默认 host 不可执行此类任务，Docker 失败也不能回退 host。不能仅靠用户任意填写的 is_sandbox=true 绕过。
4. run_evaluation.py 的 validate/grade 增加显式 --backend docker 与 --environment-lock；synthetic 的原命令保留。
5. run/create/resume 的真实模型路径遇到 opensource 时，在启动预检或读取模型凭据之前明确拒绝，本阶段不开通其付费执行。experiment 和 agent_worker 的程序化入口同样设边界。
6. Review 固定候选评测继续仅支持已有 synthetic 集合，不顺手扩充该流程。
7. 项目普通测试不收集/导入外部仓库；Docker 集成测试须显式选择，没 Docker 时记“未执行”，不能算集成验证通过。
8. 同一轮不混合 synthetic/host 与 opensource/docker 成绩。旧报告可读取，旧记录/资产不覆盖；运行源码变化使旧 ready 包失效是预期行为，不改写旧摘要绕过。

主干源码、源码学习注释和原 CLI 均保持不变。改动限于 benchmarks、相应自有 tests、文档及必要的忽略/测试标记配置。

## 10. 输出与错误口径

新结果目录不覆盖已有目录。主要文件：

| 产物 | 内容 |
| --- | --- |
| source-verification.json | 固定提交、许可位置、文件与覆盖层摘要、异常或排除清单 |
| environment-lock.json | 实际镜像身份、依赖、平台、入口与安全 profile 摘要 |
| environment-check.json | 本地引擎、安全参数、禁外网、无凭据、只读输入等实际自检结果 |
| <id>/baseline、reference、mutant/ | 每阶段日志、probe、integrity、容器状态及受限输出 |
| <id>/validation.json | 原版复现、参考通过、漏修被拒及其证据 |
| validation-summary.json / report.md | 两题是否有效、未执行与环境问题、测试范围及限制 |

错误分层：断言失败属于测试结果；依赖/引擎/镜像/启动/OOM 属于环境或资源错误；probe 不完整、ID 不符、收集错误属于验收错误；测试/配置被改属于候选拒绝。保留实际细分原因，不只依赖 pytest 返回码。

CLI：validate 的 0 表示所选任务全部完成且符合校准条件；grade 的 0 表示该补丁通过全部指定验收。1 表示正常完成但校准不成立/补丁未通过；2 表示配置、环境或验收系统错误。混合情况优先 2。任何未执行任务均不能贡献有效题数量。

使用阶段状态名：source_verified → assets_prepared → environment_verified → offline_validated。环境未就绪时最多交付 assets_prepared；不得将整个阶段写为已完成。

## 11. 验证与验收清单

实施遵循先失败测试再最小修正。自有单元测试可用假 Docker，不执行外部 Python；真实隔离效果必须有容器实测证据。

- 来源获取：固定版本、摘要不符、恶意路径、链接、重复文件和超限拒绝；源树/overlay 差异可追溯。
- 后端传递：baseline/gold/wrong 全部使用指定后端，opensource 的宿主/付费路径均在执行前拒绝。
- 命令与生命周期：安全参数、环境白名单、中文空格路径、超时后停止正确容器、回收失败留痕。
- 判分：缺 probe、退出码不一致、无测试、必需节点缺失、skip/xfail、setup/收集异常不能通过。
- 完整性：容器内测试/配置被改、显式隐藏文件在排除目录、结果符号链接及 stale ID 均拒绝。
- 凭据边界：使用无价值哨兵环境变量测试“不传入”，不使用真实密钥做泄漏试验。
- 实际环境：先运行项目自有小型探针，验证非 root、只读根和输入、禁外网、资源配置及容器终止，再允许外部测试。
- 真实任务：两题都完成 buggy 业务失败、gold 全部指定验收通过、wrong 公开通过/隐藏失败，F2P/P2P 实际收集冻结。
- 回归：项目全量 non-live、相关静态检查；旧报告仅在新副本重建比较。原有资产和历史结果摘要保持不变。

如果公开上游测试在该环境存在无关失败，保留错误并标该题未通过预检；不得随意删除测试取得绿灯。变更执行范围需新 revision 和清晰原因，再重新完整校准。

## 12. 实施顺序与当前停点

1. 用户已审核本书面设计（2026-10-20）。
2. 已制定详细实施计划；任务 0–4 为 Inline，后续按 2026-10-21 用户最新指定使用子代理，不重复询问执行模式。
3. 已实现安全归档读取、case-aware 宿主/付费默认拒绝及两题固定来源任务包，当前为 assets_prepared；详见[准备记录](../../opensource-pilot-assets.md)。容器协议与内部入口已通过自编夹具检查，见[协议说明](../../opensource-container-protocol.md)；后续做 Docker 后端与 grader 接线，过程中不在宿主导入外部仓库。
4. Docker 安装由用户另行确认或完成；不以此阻塞前述安全工作。
5. 核验可用环境后，准备固定镜像、做安全自检，再执行真实离线校准。
6. 更新工程日志和离线报告；是否进入真实 Agent 试跑及费用预算另确认。

本设计没有已经测得的镜像 digest、容器测试数量或通过率；这些只能在实际准备/运行后写入不可覆盖的锁与证据。当前无任何新的性能结论。
