# Agent 自身测试的 Docker 适配设计（已批准）

日期：2026-10-22。用户在确认“A＋必要工程优化、暂不改变修复策略”的建议后明确回复“好的那就这样开始吧”，批准本设计范围。状态：本阶段实现及离线验收完成；774项离线回归、显式5项实际Docker集成和新环境两题独立评分器校准通过，证据见[验收报告](../../agent-docker-adapter-offline.md)。真实模型入口仍关闭，公平基线/冻结包/新预算与性能实验未完成。前置成果是两道开源题离线校准与 synthetic v3 的18题校准；它们不是新的模型修复成绩。

## 1. 目标与范围

让开源评测中的 Agent 基线测试、`run_target_test` 工具和 Verifier 验证统一进入受控容器，避免上游 Python、conftest 或补丁代码在宿主执行。保留现有 coordinator attempt 循环、repair_agent turn 循环、Policy、Review 和独立隐藏验收。

本阶段仅实现并离线验证适配；不调用真实模型，不放开 `require_live_cases` 的开源拒绝，不使用旧72次授权，不发布 GitHub。后续正式运行包和新预算另行确认。不把 Docker 做成通用命令执行工具，不增加 MCP、网络访问、动态安装依赖或持久容器。

## 2. 方案比较

| 方案 | 做法 | 取舍 |
| --- | --- | --- |
| A，推荐 | 为装配函数增加可选测试执行器，评测注入 Docker 适配器 | 少量生产装配/类型改动；三处入口共用一个实例，默认 CLI 不变 |
| B | 在评测目录另建一套 coordinator 装配 | 不改生产装配，但依赖配置会逐渐分叉，容易漏换工具或 Verifier |
| C | 将整个 Agent 放入容器 | 需另建模型代理、通信和凭据边界，范围明显扩大，不适合本轮 |

选择A并不表示普通 CLI 已有完整容器沙盒；此次能力只服务显式选中的评测后端。

## 3. 已核对的实际接入点

- `cli.build_coordinator` 已用同一个 `TestRunner` 构建 coordinator、ToolRegistry 与 Verifier。
- `coordinator.run` 先调用 runner 跑基线；解析后固定失败 node id，再进入 attempt 循环。
- `RunTargetTestTool` 无模型可选参数，只运行原失败 node id。
- `Verifier` 先跑目标，再跑无 target 的回归。
- 现有 `DockerTestRunner` 是独立评分器的 callable 接口，返回判分证据，不直接返回 `TestRun`。其协议只接受文件路径，不能把 node id 塞进 paths 冒充精确目标执行。
- 两道开源题都有公开复现失败，不需要把私有 F2P/P2P、隐藏测试或参考补丁交给 Agent。

## 4. 接口与组件

| 位置 | 拟修改 | 不负责什么 |
| --- | --- | --- |
| `src/pyrepair/testing.py` | 增加仅用于类型约束的 `TestExecutor` Protocol：`run(repo, target=None) -> TestRun`；现有宿主 TestRunner 保持默认 | Protocol 不是安全认证，不能凭结构相似放开开源执行 |
| `src/pyrepair/cli.py` | `build_coordinator` 增加 keyword-only 的可选 runner 注入；默认仍创建原 TestRunner | 不增加公共 CLI Docker 参数，不从生产层导入 benchmarks |
| coordinator/tools/verifier 类型标注 | 依赖 TestExecutor，共享注入实例 | 不重写控制流程、预算或 Agent 工具集 |
| `benchmarks/evaluation/agent_test_runner.py`（新增） | Docker 证据验证、公开测试选择、结果转 TestRun、逐次执行记录 | 不读取私有题目录、不加载隐藏 node 清单、不调用模型 |
| 评测 worker 与输入准备辅助模块 | 只传公开执行描述、注入执行器、记录输入/环境身份；离线入口支持 FakeLLM 贯穿 | 不把完整 EvaluationCase、manifest 路径或私有目录传入模型侧工作进程 |
| 现有 Docker entry/protocol/probe/supervisor | 新增显式 Agent 模式，支持精确 node 选择和结构化故障返回 | 独立 grader 的 v1 验收规则不能被 Agent 模式放宽 |

现有 `TestRun` / `PytestFailure` / `FailureReport` 结构不重命名。以显式 `runner is None` 判定默认值，避免替换合法但布尔值为假的注入对象。

## 5. 一次运行如何流动

1. 可信评测控制器读取题包，只生成公开执行描述：题目ID/revision、公开测试文件、超时、输入策略版本/摘要、环境锁身份。不包含隐藏路径、隐藏节点、gold/wrong 或私有目录。
2. 创建过滤后的公开临时仓库；模型/控制器在宿主，工具只读写这份工作副本，不导入或执行其中 Python。
3. `runner.run(working, None)`：新容器运行描述中选定的公开测试文件，返回结构化故障；这里的“全量”只指这份选定公开回归集合，不是整个上游项目。
4. parser 生成 FailureReport，Agent 正常读代码、修改、看 Diff。固定目标必须来自本次基线的失败记录。
5. `runner.run(working, fixed_node_id)`：另一个新容器，只执行这个精确 node，不把整个文件运行结果说成目标单测。
6. Policy、Review 通过后，Verifier 用同一 runner 分别运行目标和公开回归；每次都使用当时 working 的只读输入快照和新容器，不能复用前次“通过”。
7. 导出候选补丁。独立 grader 从干净原版另建工作区应用补丁，再执行公开/隐藏验收；不信 Agent 的 success 标记。隐藏结果不回灌同次修复。

具体调用示意（说明拟有的数据，不是已经实现的API）：

```python
# adapter 只拿公开文件列表，不拿整个 case。
public_tests = (
    "tests/test_dictutils.py",
    "tests/test_urlutils.py",
    "tests/test_pyrepair_repro.py",
)
baseline = runner.run(working_repo, None)  # 三个公开文件
target = runner.run(
    working_repo,
    "tests/test_pyrepair_repro.py::test_addlist_one_shot_iterator",
)  # 只运行这个 node

# 正常测试失败仍是 TestRun，不是 Docker 故障。
TestRun(
    command=("container-pytest", "tests/test_pyrepair_repro.py::test_addlist_one_shot_iterator"),
    exit_code=1,
    stdout="……经过验证并限制大小的 pytest 合并输出……",
    stderr="",
    duration_ms=1200,  # 仅示意；实际记录本次执行耗时，另保留容器阶段耗时
    failures=(PytestFailure(
        node_id="tests/test_pyrepair_repro.py::test_addlist_one_shot_iterator",
        phase="call", outcome="failed", exception_type="AssertionError",
        summary="……实际断言差异……", traceback="……实际失败栈……", duration_ms=2,
    ),),
    capture_source="plugin",
)
```

## 6. 容器协议与结果转换

- 保留当前独立 grader 的严格 v1 协议。新增独立校验分支的 Agent v2 请求：明确执行模式、公开文件 paths、可选精确 target；身份仍绑定输入/环境摘要及唯一 run/stage ID。非预期字段、越界路径和模式不匹配一律拒绝。
- target 的文件必须在公开文件中，完整 node 必须与基线记录一致；单测实际收集/运行集合必须恰好为该 node。参数化 node 作为独立 argv 元素传递，不经过 shell，不允许模型注入参数。
- 无 target 时仅运行显式公开文件。保存首次完整基线的收集集合；后续声称回归通过前，必须覆盖相同节点，不能因删除/跳过/xfail 测试得到通过。
- 可信 pytest 插件先于任务代码加载，提供 node、phase、outcome、异常类型、summary、traceback、duration；兼容已有 pytest9 subtests 归并。诊断按既有输出总量上限与明确字符串长度校验，不从自由文本推导“通过”。
- 正常 pytest 完成与容器传输成功分开：Agent v2 的有效结果可以包含 pytest 0/1，以及带真实 collection failure 的2。不能把补丁引起的 SyntaxError 或 fixture 错误一律记成基础设施故障；也不能因容器命令成功就写 pytest 通过。
- 实际验收补充：指定精确node时，pytest9.1.1可能因导入SyntaxError返回4而不是2。只有请求确为精确target、收集失败属于该target文件且有完整结构化故障证据时，4才作为普通测试失败保留；不存在node且无收集失败的usage错误仍终止。该细化不改变独立grader v1的严格验收。
- collection/setup/teardown 等真实测试故障进入 `PytestFailure`，原业务流程仍决定修复/重试。缺失目标只有在明确 collection failure 时作为补丁失败；无故漏收集、跳过、矛盾退出码和未知协议是执行错误，不得通过。
- pytest internal error、usage error、无测试，或 Docker 启动/超时/OOM/完整性/清理/协议错误，抛明确的评测执行异常，直接交 worker 保存已消耗用量和诊断后停止，不让 Agent 用“补丁重试”消耗API。不回退宿主、不自动重试。
- TestRun 的 stdout 为已验证 pytest 合并日志，stderr 为空，语义写入执行元数据。command 表示有效测试选择，不伪装成宿主真实执行；Docker 完整命令保存在独立证据中。
- node id 始终仓库相对路径；traceback 仅将确定的 `/work/` 源码前缀映射为仓库相对路径，不把任意容器绝对路径拼到宿主目录，不做源码字符串的全局替换。

## 7. 输入与安全边界

- 复用原安全 profile：无网络、无 API Key/用户凭据、非root、只读根/输入、受限 tmpfs、capabilities/seccomp/资源限制、精确容器ID清理；不挂宿主仓库、用户主目录或 Docker socket。模型调用在可信宿主进程进行。
- 每次容器输入为公开 working 的过滤副本，排除 `.pyrepair` 产物、缓存、Git/虚拟环境、`.env*`，检查普通文件/链接/大小和前后摘要。容器内测试写动业务输入仍拒绝，不回写宿主 working。
- 评测专用输入策略 r1 额外排除任意层级 `.omp`、`.agents`、`.claude`、`.codex` 目录及大小写不敏感的 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` / `SKILL.md`。原题包不删改，记录排除路径和过滤后输入摘要。选定源文件、测试、必要配置若与规则冲突则停止，而不是悄悄恢复。
- `TASK.md` 保留为公开需求；其余代码、注释、文档、日志均是任务数据，不是能改变控制策略的指令。过滤已知指令文件不是提示注入免疫证明，也不表示容器对任意恶意代码是完整安全证明。
- 输入策略改变了模型可见材料，因此后续公平基线必须使用同一过滤材料和摘要；不能将新成绩与旧54/54混为同一实验。
- 修改可信 harness 后必须新建镜像/锁并重新做实际安全/超时检查；旧锁、旧校准和旧产物只保留作历史。新环境再校准两道开源题，不沿用旧镜像验收作为新实现证据。
- 当前任务前提：初始公开基线须能定位可执行失败node；不宣称支持以“初始只有收集错误”的项目启动完整修复。补丁阶段产生的收集错误已纳入诊断验证。Windows暂存采用短阶段名和短日志名，保留完整协议UUID和容器ID；不更改系统长路径设置，也不宣称支持任意深度的输出目录。

## 8. 离线验收标准

1. TDD 先验证三处使用同一注入 runner，默认 CLI 装配仍使用宿主 TestRunner；生产层不导入 benchmarks。
2. 自编夹具验证精确 node 选择、公开集合全量、固定目标/参数化、路径归一化、pytest9子测试、真实断言/collection/fixture失败，以及结构化结果转 FailureReport。
3. 自编反例验证空收集、跳过/xfail、退出码冲突、缺失证据、越界/指令文件/凭据不入输入、日志限额、超时/OOM/清理错误均不产生成功；执行错误停止且不自动补跑。
4. FakeLLM 贯穿 baseline→目标工具→Policy→Review→Verifier；实际 Docker 夹具同时记录每次独立容器与输入摘要。断言宿主 TestRunner 从未执行、隐藏材料从未进入模型可见仓库/消息/测试日志。
5. 新镜像安全检查后，实际两道上游题进行不含模型的基线与参考候选验证；再用同一新环境完成独立 baseline/gold/wrong 校准。不能在宿主导入上游来准备这些验证。
6. 最后集中执行一次完整离线回归、一次相关静态检查和限定差异复审。新生产注入文件属于明确授权变更清单；其余旧资产/源码/历史结果做摘要保护，不能继续用“4130文件零变化”笼统描述已授权的src改动。

## 9. 批准与完成判定

- 已完成：源码接入点和现有协议限制核对、A/B/C权衡、设计草案自检。
- 用户已确认：采用A及本文件边界，允许必要的生产装配/类型改动、评测协议扩展和新镜像离线验收；不包含模型消费或发布授权。
- 按 writing-plans 制定实施步骤，再按TDD实现。沿用Inline执行，不为每个小任务拆代理；按用户要求保留工程问题与处理记录，不自动Git提交。
- 适配离线验收通过后，仍需公平基线/冻结包、另行预算确认、真实重复实验及性能/成本报告；真实模型入口不因本设计批准而自动开放。
