# 三十道开源题：资产装配与离线校准

截至 2026-10-26，三十道真实开源题全部通过离线校准，覆盖五个仓库、87 个 F2P 故障节点与 68 个 P2P 回归节点。这是题目质量验收，不是 DeepSeek 性能结果。承接[来源与参考补丁准备](opensource-reference-preparation.md)和[实施计划](superpowers/plans/2026-10-25-catalog-task-calibration.md)。生产 Agent 保持冻结；只有全部五十题就绪后才开始新的统一模型实验。

## 当前交付

三十题均已生成公开说明、公开复现、隐藏边界、参考生产补丁、不完整生产补丁及 manifest。新增覆盖层按仓库分为 packaging、Click、dotenv/迭代器三个数据模块；旧两题沿用原行为合同，装配时使用新的测试路径、全包编辑范围和导入配置，所以新任务 revision 为 3，不覆盖旧 revision 2。

公开测试统一为 `pyrepair_public_tests/test_repro.py`，隐藏测试为私有侧的 `hidden_tests/test_contract.py`。公开材料不含隐藏测试或参考补丁。允许修改整个生产包现有的受策略允许 Python 文件，不按参考补丁涉及的文件缩窄。回归范围是所登记的合同测试，不声称执行了上游全仓测试。

原始生成记录保留 `assets_prepared` 和运行前的 `declared_not_collected`，不就地改写。另有三十题 `calibrations_verified` 索引绑定实际节点结果与最终资产。`ready_for_model_evaluation=false`：统一五十题与正式实验尚未冻结。人工不完整补丁只用于校准测试，不当作模型生成结果。

## 导入与环境

`pyrepair_imports.json` 是公开运行树内的只读数据配置，绑定 `src/` 或仓库根和预期包文件。可信 pytest 与评分插件先加载，然后清除候选包的旧模块缓存，导入真实候选源码并检查文件来源；否则环境安装的同名 `packaging` 可能被误测。该检查防止误导入，不是抵抗恶意源码伪造 `__file__` 的证明；实际执行仍依靠 Docker 边界。

新环境增加固定 Click 8.3.0 universal wheel，供 dotenv CLI 使用，摘要按[官方 PyPI 元数据](https://pypi.org/pypi/click/8.3.0/json)核对。旧环境锁不就地改写；新的 harness 摘要和依赖要求使用新锁，旧成绩仍绑定原环境。

新镜像：`sha256:eb08da21b62bf636ca21adebc9ae298d355d440166522042444c7fe1116f790f`。Python 3.13.5，pytest 9.1.1，Linux/amd64；已通过九项自有安全/超时检查：非 root、根只读、输入只读、无凭据、禁外网、回环可用、seccomp 生效、实际容器配置检查、超时停止。测试阶段不联网、不安装依赖、不传入 API Key。

## 三种校准结果

每题各用干净副本执行：

1. 缺陷基线：所有声明 F2P 节点以断言失败，P2P 节点通过；导入或收集错误不算复现成功。
2. 参考生产补丁：公开与隐藏均通过。
3. 人工不完整补丁：公开通过，隐藏至少一个 F2P 节点以断言失败；仅破坏原有回归不足以通过当前校准。

技术错误、漏收集、跳过和运行期间改写源码均不算合格。修正评测资产时使用新的装配/校准目录，保存旧资产及失败；不修改 Agent 来适应新题。

## 本地证据与复现

| 路径 | 含义 |
| --- | --- |
| `D:/Project/PyRepair Agent/tmp/catalog30-environment-20261025-a07cf42/` | 新锁、依赖元数据、构建输入、安全与超时证据 |
| `D:/Project/PyRepair Agent/tmp/catalog30-tasks-20261025-a01/` | 首版草稿，保留，不覆盖 |
| `D:/Project/PyRepair Agent/tmp/catalog30-tasks-20261026-a02/` | 修正三个不完整补丁后的三十题装配 |
| `D:/Project/PyRepair Agent/tmp/catalog30-tasks-20261026-a03/` | 当前三十题资产；仅 boltons 不完整补丁及来源说明相对 a02 改变 |
| `D:/Project/PyRepair Agent/tmp/catalog30-calibration-20261025-a01/` | 首题 hash 合同校准 valid，缺陷失败/参考通过/不完整修复隐藏失败 |
| `D:/Project/PyRepair Agent/tmp/catalog30-calibration-20261026-a02/` | 首次整批：29 valid、1 invalid（boltons mutant 过弱），不覆盖 |
| `D:/Project/PyRepair Agent/tmp/catalog30-calibration-20261026-a03/` | 修正后仅重验 boltons：1 valid；calibration-index.json 汇总最终三十题的匹配证据 |

在 managed worktree 用已有 `benchmarks/run_evaluation.py validate`，显式传 `--manifest`、`--backend docker`、`--environment-lock` 和全新 `--output`。它不会请求模型。私有测试、完整源码缓存和原始容器产物保持本地，不自动上传。

`catalog_calibration.collect_calibrations()` 读取最终清单、候选结果目录及环境锁 SHA-256，重算每题资产指纹，复查三种行为和每阶段的环境/完整性/收集/清理状态。只复用完全匹配的记录；旧指纹失败保留但不用于新资产，同一指纹出现 invalid 冲突则拒绝汇总，不能静默取最好一次。

最终环境锁 SHA-256：`788e6a18f3d4f3683444b4bd4407723ff6531b1bb31ed60e056089f6a517b86e`。索引明确指向 29 份 a02 证据和 1 份 a03 证据及各自 JSON 摘要，不声称所有题都来自一次未改资产的校准批次。汇总器只是复核保存的证据，不代替正式实验冻结时的新环境检查。

最终 `calibration-index.json` SHA-256：`c2804ba805fe8d8a53b6f2ead33db97abdfdfa03c18f9f257e43ee8153c95903`。

工具侧最终定向回归：232 passed，0 failed/errors/skipped；JUnit：`D:/Project/PyRepair Agent/tmp/r-33625427/focused.xml`。Ruff 与所选新文件格式检查通过。只读审查发现的路径 P2 已复现、修复并复审；汇总器无新增 P1/P2。这 232 项是本项目工具测试，和三十题的 155 个行为节点不是同一统计口径。

## 已发现的问题

- `src/` 未显式绑定时会误用环境包。自有小仓库先复现失败，新增导入配置与实际来源检查后通过；不改上游生产文件。
- dotenv CLI 需要 Click。固定 wheel/摘要并准备新环境，不在测试期间临时联网安装。
- BOM、empty-get、Click EOF 的首版不完整补丁只破坏 P2P 回归，而隐藏 F2P 仍全过。已改为遗漏 quoted/export BOM、遗漏空值插值、丢失无末尾换行的输入，保持评分规则不变；实际效果由 Docker 校准决定。
- Windows 受限测试不能创建硬链接。仅对自有 Docker-supervisor 测试按权限流程执行；未跳过硬链接保护或修改 ACL，88 项通过。
- 2026-10-25 审批服务额度中断使首次校准未执行。2026-10-26 显式继续后首题 valid；不把未执行记成失败，也不伪造运行记录。
- 只读审查发现输出路径含 `..` 时，`.absolute()` 加字面重叠检查可绕过来源缓存隔离。自有反例先失败；拒绝链接后规范化双方路径再比较，8 项装配测试通过，审查确认关闭该 P2。
- boltons 首版 mutant 仅修 dictutils，实际上 urlutils 会复用该实现，导致隐藏测试也全过。当前改用旧 revision 2 已登记的“只在新键上物化迭代器”边界；本批失败结果保留，新资产后另行校准。
- boltons 修正后已通过完整三类校准。其余二十九题的最终指纹与 a02 证据一致，故未再全部重跑。

## 结果解读边界

来源覆盖五个仓库：packaging 十二题、Click 八题、python-dotenv 六题、more-itertools 三题、boltons 一题。仓库集中度较高，以纯 Python 库的行为缺陷为主，不能把三十题称为广泛代表真实软件工程任务的业界基准。参考补丁大小也不等于任务难度。

新增测试依据公开合同独立编写，隐藏值和源码不提供给模型；通过这些测试只证明满足已覆盖的行为，不证明完全正确。旧两题采用新的资产布局和局部回归选择，因此本批不能与旧二十题成绩拼接；待正式五十题实验重新统一运行。

后续先解决校准暴露的题目或环境问题，再补两道自建题、统一五十题复核与冻结。本阶段不更新 README/简历为新模型成绩。
