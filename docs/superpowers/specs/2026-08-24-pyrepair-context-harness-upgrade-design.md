# PyRepair Agent 上下文与 Harness 升级设计

日期：2026-08-24

状态：设计已批准，等待用户复核正式文档

目标周期：14 天，每天 4–6 小时

## 1. 背景与当前基线

PyRepair Agent 已实现面向单个 pytest 故障的候选补丁闭环：临时工作区、失败解析、DeepSeek Tool Calling、受限工具、确定性补丁门禁、独立 Review、目标测试、全量回归和运行产物记录。

当前工程基线：

- 134 个离线测试通过，1 个 live 测试默认跳过。
- 总覆盖率 91%。
- Ruff 检查通过。
- 15 个单 Bug Benchmark 中，DeepSeek V4 Flash 端到端成功 13 个，成功率 86.7%。
- `case_05` 和 `case_08` 在调用 LLM 前失败，原因是 pytest 9 输出格式未被文本解析器识别。

当前主要限制：

- 初始上下文主要依赖 traceback，缺少结构化仓库概览和相关代码选择。
- Agent 需要从消息轨迹中自行统计已读文件、工具预算和验证进度。
- 重试只接收粗粒度字符串，缺少上一轮 Diff、新测试失败和审查证据。
- 工具把主要结果放在自由文本中，不利于状态计算、分页和错误恢复。
- 仅有最大工具调用次数，没有重复调用和无进展检测。
- Benchmark 以简单、单文件任务为主，无法充分验证上下文增强的价值。

## 2. 目标

本次升级围绕一个核心问题展开：在模型固定的情况下，能否通过改进观察空间、工具反馈和 Harness 状态管理，提高 PyRepair 在跨文件故障上的修复表现，并用可复现实验量化效果。

必须达到以下目标：

1. 使用结构化 pytest 采集解决 pytest 8/9 输出变化，并保留文本解析降级路径。
2. 使用 traceback、AST 符号、文件结构、import 关系和关键词构建确定性 `ContextBundle`。
3. 在每次模型调用前注入由 Python 维护的 `AgentStatus`。
4. 使用 `LoopGuard` 检测完全重复调用、相同错误和连续无进展。
5. 将工具结果改为稳定 JSON，明确区分工具执行失败与测试正常执行但未通过。
6. 将每轮候选 Diff、Policy、Review、目标测试和回归证据压缩为 `AttemptFeedback`，供下一轮使用。
7. 将 Benchmark 扩展到 30 个任务，通过四组累积式消融实验比较各模块贡献。

## 3. 非目标

本次不实现：

- Docker、microVM 或远程代码执行沙盒。
- MCP、A2A 或动态工具发现。
- 自动 Commit、Push、创建 PR 或合并代码。
- 长期记忆、用户画像或向量数据库。
- 多故障联合规划和并行修复。
- Agent Teams、异步 Agent 或并行工具调用。
- 任意 Shell 命令和自动依赖安装。
- DeepSeek 以外的模型供应商适配。
- 精确模型 Tokenizer；第一版使用字符预算，API 返回的真实 Token 只用于事后评测。

当前 pytest 仍使用宿主机 Python 执行，只适用于开发者信任的本地项目。临时工作区隔离文件修改，但不提供进程、网络和宿主文件系统隔离。README 必须明确这一边界。

## 4. 总体架构

```text
pytest baseline
      │
      ▼
TestRunner + 内置 pytest capture plugin
      │
      ▼
PytestParser ──► FailureReport
      │
      ▼
ContextBuilder
  ├─ RepositoryIndex
  ├─ traceback / node id signals
  ├─ AST symbols and imports
  └─ lexical matches
      │
      ▼
ContextBundle
      │
      ▼
RepairAgent Loop
  ├─ AgentStatusBuilder
  ├─ Structured ToolRegistry
  ├─ LoopGuard
  └─ CompletionPolicy
      │
      ▼
PatchPolicyGate ──► ReviewAgent ──► Verifier
      │                    │              │
      └────────────────────┴──────────────┘
                           │
                           ▼
                    FeedbackBuilder
                           │
                           ▼
                    AttemptFeedback
                           │
              restore baseline and retry
```

保持现有信任边界：LLM 负责探索与提出修改；Python 负责工作流、权限、预算、门禁、验证和最终成功判断。

## 5. 数据模型

内部模型继续使用 `dataclass`，不在本次引入 Pydantic。

### 5.1 pytest 结构化结果

```python
@dataclass(frozen=True)
class PytestFailure:
    node_id: str
    phase: Literal["setup", "call", "teardown", "collection"]
    outcome: str
    exception_type: str | None
    summary: str
    traceback: str
    duration_ms: int
```

`TestRun` 新增：

```python
failures: tuple[PytestFailure, ...] = ()
capture_source: Literal["plugin", "text", "none"] = "none"
```

### 5.2 仓库与上下文模型

```python
@dataclass(frozen=True)
class SymbolInfo:
    path: str
    name: str
    kind: Literal["function", "class", "method"]
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ContextSnippet:
    path: str
    start_line: int
    end_line: int
    symbol: str | None
    reason: str
    score: int
    content: str


@dataclass(frozen=True)
class ContextBundle:
    repo_overview: str
    snippets: tuple[ContextSnippet, ...]
    related_files: tuple[str, ...]
    total_chars: int
    truncated: bool
```

### 5.3 Tool 结果

```python
JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class ToolErrorInfo:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, JSONValue]
    error: ToolErrorInfo | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
```

`ok=True` 只表示工具完成调用。`run_target_test` 的测试结论由 `data["passed"]` 表示；pytest 正常启动但测试失败必须返回 `ok=True, passed=False`。

### 5.4 Agent 状态

```python
@dataclass(frozen=True)
class AgentStatus:
    attempt: int
    max_attempts: int
    tool_calls_used: int
    max_tool_calls: int
    files_read: tuple[str, ...]
    changed_files: tuple[str, ...]
    last_tool: str | None
    last_error: str | None
    repeated_call_count: int
    no_progress_steps: int
    diff_inspected: bool
    target_test_run: bool
```

运行时使用可变的 `AgentRuntimeState` 维护工具历史、文件集合和验证状态，对外只生成不可变 `AgentStatus`。

### 5.5 重试反馈

```python
@dataclass(frozen=True)
class TestFailureEvidence:
    node_id: str | None
    exit_code: int | None
    summary: str
    output_tail: str
    timed_out: bool


@dataclass(frozen=True)
class AttemptFeedback:
    attempt: int
    outcome: str
    changed_files: tuple[str, ...]
    candidate_diff: str
    policy_violations: tuple[str, ...]
    review_findings: tuple[str, ...]
    target_failure: TestFailureEvidence | None
    regression_failures: tuple[str, ...]
    next_focus: str
    truncated: bool = False
```

## 6. pytest 结构化采集与解析

### 6.1 主路径：内置轻量插件

新增内部 pytest 插件，通过 pytest hook 采集 node id、阶段、outcome、`longreprtext`、耗时和 session 退出码。结果写入 working 副本的：

```text
.pyrepair/internal/pytest-report.json
```

`.pyrepair` 已被工作区快照排除，不会进入候选 Diff。插件不得修改测试结果、fixture 或标准输出；报告写入失败时 pytest 仍正常结束。

### 6.2 降级路径：文本解析

当插件无法加载、报告不存在或 JSON 无法安全解析时，文本解析器依次支持：

```text
FAILED tests/test_a.py::test_x - AssertionError: ...
FAILED tests/test_a.py::test_x
ERROR tests/test_a.py::test_x
tests/test_a.py::test_x FAILED
```

同时处理参数化 node id、Windows/Linux 路径、setup/teardown/collection 错误、多行异常、ANSI 控制符及 pytest 8/9 摘要差异。

### 6.3 主要失败选择

第一版仍只修复一个主要失败。稳定选择顺序：

1. 用户显式指定的测试。
2. `call` 阶段失败。
3. `setup` 阶段失败。
4. `teardown` 阶段失败。
5. `collection` 错误。
6. pytest 报告中的稳定顺序。

`TestRun.failures` 保留全部失败，为后续多故障支持预留数据，不在本次实现联合规划。

## 7. ContextBuilder

### 7.1 职责

`ContextBuilder` 回答：本次失败最相关的文件、符号和代码片段是什么，以及如何在固定字符预算内提供这些信息。

它不调用 LLM，不建立向量数据库，不生成修改建议。

### 7.2 索引范围

扫描 Python 文件并提取：

- 文件路径和模块名。
- 类、函数、方法及起止行。
- import 与 from-import 关系。
- 失败测试、traceback、异常类型和摘要中的标识符。

复用 `WorkspaceManager` 的排除集合，跳过 `.git`、虚拟环境、缓存、构建目录、`.pyrepair` 和工作树目录。

AST 解析失败时保留文件路径并回退到词法匹配；非 UTF-8 文件跳过并记录原因。ContextBuilder 自身失败时返回最小空 Bundle，Agent 退化为当前工具探索流程，不能令整个修复任务崩溃。

### 7.3 确定性评分

| 信号 | 分值 |
| --- | ---: |
| 文件直接出现在 traceback | +100 |
| 当前失败测试文件 | +90 |
| 包含异常涉及的函数或方法 | +70 |
| 被失败测试直接 import | +60 |
| 与 traceback 文件存在一层 import 关系 | +40 |
| 包含失败摘要中的标识符 | +30 |
| 文件名与测试模块名称相似 | +20 |
| 普通关键词匹配 | +10 |

同分时按规范化路径、起始行和符号名排序，保证结果可复现。分数只用于上下文选择，不直接决定修改目标。

### 7.4 字符预算

第一版使用：

```python
MAX_CONTEXT_CHARS = 16_000
MAX_SNIPPETS = 8
MAX_SNIPPET_CHARS = 2_500
MAX_OVERVIEW_CHARS = 2_000
```

优先顺序：失败测试片段、traceback 源码、相关符号、一层 import 关联、关键词结果。超过预算后停止追加并设置 `truncated=True`。模型可通过工具继续读取未进入初始上下文的内容。

不引入 Tokenizer 的原因：保持模型与供应商无关、避免新增运行依赖。每次 API 返回的实际 Prompt/Completion Token 仍写入轨迹和 Benchmark，用于事后比较。

### 7.5 上下文格式与信任边界

每段代码附带路径、行号、符号、选择原因和分数，并放入明确的数据标签。仓库注释、文档和字符串均属于不受信任数据，不能获得系统指令权限。

轨迹默认只记录选中文件、符号、分数、字符数、截断和构建耗时，不重复记录完整代码正文。

## 8. 结构化代码工具

第一版工具集升级为：

- `read_file(path, start_line=1, end_line=None)`：返回带行号文本、总行数、截断与下一起始行。
- `search_code(query, path=None, offset=0, limit=50)`：返回匹配路径、行号、文本、总数和下一偏移。
- `find_symbol(name)`：使用 AST 返回定义位置。
- `find_references(name)`：AST 与文本结合返回可能引用，工具描述明确其不是完整 LSP 语义保证。
- `inspect_module(path)`：返回模块中的类、函数和 import 概览。
- `replace_text(path, old_text, new_text)`：继续要求 old string 唯一匹配，只允许修改 Python 源码。
- `show_diff()`：返回 Diff、修改文件、增删行和截断信息。
- `run_target_test()`：返回执行状态、测试通过状态、耗时和输出末尾。

工具结果必须是稳定 JSON。错误返回公开错误码、可行动消息和 `retryable`，不暴露原始异常、API Key、绝对临时路径或环境变量。

## 9. AgentStatus 与 LoopGuard

### 9.1 状态栏

每次模型调用前，Harness 在消息末尾追加一条由 Python 生成的 `<agent_status>`，包含尝试次数、工具预算、已读文件、修改文件、最后工具与错误、重复次数、无进展次数、Diff 检查和目标测试状态。

状态栏只含元数据，不含代码正文；字段顺序稳定。修改源码后自动把 `diff_inspected` 和 `target_test_run` 重置为 false。

### 9.2 进展定义

以下事件算取得进展：

- 首次读取新的文件或范围。
- 搜索获得此前未见结果。
- 成功修改源码或 Diff 变化。
- 测试结果变化。
- 获得新的错误证据。

完全相同的读取、搜索结果、替换错误、测试结果和工具错误不算进展。

### 9.3 循环规则

- 完全相同的工具名与规范化参数第二次调用时允许，但状态栏警告。
- 第三次连续完全重复时阻止本轮，原因 `repeated_tool_call`。
- 连续 3 次无进展时注入调整策略提示。
- 连续 4 次无进展时停止本轮，原因 `no_progress`。
- 同一工具与参数连续得到相同错误两次后，禁止再次原样调用。
- 工具预算剩余 2 次时提示优先完成 Diff 和目标测试验证。

### 9.4 完成策略

只要产生了源码修改，模型主动结束前必须满足：

```text
存在源码修改
AND 修改后查看过 Diff
AND 修改后运行过目标测试
```

缺少步骤且还有预算时，Harness 追加缺失步骤状态并继续；预算耗尽时返回 `required_verification_missing`。最终成功仍只由 Policy、Review 和 Verifier 判定。

## 10. StructuredAttemptFeedback

每轮从以下真实结果构建反馈：

- Snapshot 与候选 Diff。
- Policy violations。
- Review findings。
- 目标测试的新失败证据。
- 全量测试与新增回归。
- 本轮结果和确定性下一步关注点。

长度限制：

```python
MAX_FEEDBACK_DIFF_CHARS = 6_000
MAX_TEST_OUTPUT_CHARS = 4_000
MAX_REVIEW_FINDINGS = 5
```

Diff 保留开头与结尾，测试输出优先保留末尾，所有截断都加入显式标记。最多 3 轮，因此下一轮接收之前所有轮次的压缩反馈。

固定输入分层：

```text
FailureReport      原始故障，始终不变
ContextBundle      baseline 仓库上下文，始终不变
AttemptFeedback    前序尝试产生的新外部证据
AgentStatus        当前尝试和工具循环的实时状态
```

Review findings 来自 LLM，只作为审查证据，不提升为系统指令。

## 11. Coordinator 数据流

1. 创建 baseline 与 working。
2. 执行 baseline pytest，优先读取结构化插件报告。
3. 选择主要失败并生成 `FailureReport`。
4. 从 baseline 构建一次 `ContextBundle`。
5. 每轮恢复干净 working，创建全新 ToolRegistry、RepairAgent 运行时状态和 LoopGuard。
6. RepairAgent 接收固定故障、固定上下文和前序反馈，在每次模型调用前接收最新状态栏。
7. 候选修改依次经过 Policy、Review 和 Verifier。
8. 失败时由 FeedbackBuilder 生成结构化反馈；成功时写入 Patch。
9. 所有路径均写入报告、轨迹和 pytest 日志，最后清理临时工作区。

每轮仍从 baseline 恢复，失败补丁不能叠加。ContextBundle 基于 baseline 构建，不在每轮重复索引。

## 12. Benchmark 与消融实验

### 12.1 数据集

保留现有 15 个 Level 1 单 Bug 项目，新增 15 个：

| 难度 | 数量 | 内容 |
| --- | ---: | --- |
| Level 2 | 5 | 测试与源码跨文件 |
| Level 2 | 3 | import 调用链与辅助函数 |
| Level 2 | 2 | fixture、参数化测试和输出格式 |
| Level 3 | 3 | 同名符号与干扰文件 |
| Level 3 | 2 | 结合两个代码片段定位根因 |

每个任务只有一个人工注入 Bug，测试是客观成功标准，并配人工确认的参考补丁。`case.json` 和参考补丁不复制进 Agent 工作区。

`case.json` 保存 id、标题、难度、标签、期望源码文件、参考补丁、主要测试和是否需要跨文件上下文。期望文件只用于评测，不参与 ContextBuilder 评分。

### 12.2 四组累积式消融

所有实验固定模型、数据集、最大尝试、工具预算、Policy、Review、Verifier 和 pytest 采集器。

| Arm | 功能 |
| --- | --- |
| `control` | 新 pytest 采集器，其他保持兼容基线 |
| `context` | control + ContextBuilder + 结构化代码工具 |
| `state` | context + AgentStatus + LoopGuard |
| `full` | state + StructuredAttemptFeedback |

命令：

```powershell
python benchmarks/run_benchmark.py --model deepseek-v4-flash --arm full --repeat 3
```

新增 `--arm control|context|state|full`、`--repeat N`，保留 `--case` 与 `--resume`。

### 12.3 指标

最终结果：成功率、首轮成功率、平均尝试、回归、Policy/Review 拒绝。

上下文：字符数、片段数、选中文件、截断、构建耗时、API 实际 Token。

循环：工具次数、重复调用、无进展步骤、LoopGuard 阻止、目标测试次数、修改后未验证次数。

补丁：修改文件、增删行、是否命中参考文件、是否修改相同符号。不同正确实现不要求与参考补丁文本完全一致。

### 12.4 公开结果

```text
benchmarks/results/raw/       本地原始结果，不提交
benchmarks/results/public/    脱敏稳定结果，提交 GitHub
```

公开结果包含模型、Git commit、Python/pytest 版本、实验组、重复次数、逐 case 结果、Token、耗时、工具次数、失败归因和候选补丁或补丁哈希。

不得包含 API Key、绝对本机路径、环境变量、用户项目代码或隐藏推理内容。报告必须明确样本量和单次/重复实验范围，不从小样本外推普遍结论。

## 13. 错误处理与降级

- pytest 插件失败：回退文本解析。
- ContextBuilder 失败：返回最小 Bundle，回退 Agent 工具探索。
- AST 失败：回退词法检索。
- 工具参数无效：返回结构化非重试错误。
- 文件缺失等可修正问题：返回结构化可重试错误。
- FeedbackBuilder 部分失败：至少保留 outcome、失败原因和 changed files。
- 状态栏构建失败：作为内部 Harness 错误停止，不向模型提供可能错误的状态。
- LoopGuard 阻止：结束当前尝试，由 Coordinator 记录并决定是否进入下一轮。
- API、工作区、记录器等基础设施错误：沿用现有异常路径和脱敏要求。

状态栏准确率属于安全边界；不允许用 LLM 批量总结轨迹来生成状态。

## 14. 测试策略

### 14.1 pytest 采集

- pytest 8/9 摘要。
- 无错误后缀的 FAILED。
- setup、teardown、collection 和参数化失败。
- Windows/Linux 路径与 ANSI 输出。
- 插件报告损坏后的文本降级。
- 多失败稳定排序。
- 插件写入失败不改变原始 pytest 退出码。

### 14.2 ContextBuilder

- traceback 文件优先。
- 失败测试 import 的源码被选中。
- AST 类、函数、方法与 import 正确。
- 语法错误降级。
- 排除目录正确。
- 字符预算和片段上限不突破。
- 同输入排序一致。
- 不可信代码注释被标记为数据。
- 构建失败可降级。

### 14.3 工具、状态与循环

- ToolResult 稳定 JSON 与 Unicode。
- 工具错误和测试失败区分。
- read/search 分页与截断。
- 成功编辑后验证状态重置。
- 不同参数不被误判为重复。
- 第三次完全重复被阻止。
- 新证据重置无进展计数。
- 修改后缺 Diff 或目标测试不能正常结束。
- 脱敏覆盖工具、状态、反馈和日志。

### 14.4 反馈与 Benchmark

- 下一轮收到新 pytest 失败、Policy 和 Review 证据。
- 长度限制与截断标记正确。
- 四种 Arm 装配准确。
- `--resume` 和重复运行不覆盖、不重复。
- 不汇总混合模型、数据集版本或功能配置。
- 公开结果不含密钥和绝对路径。

## 15. 两周实施顺序

1. Day 1–2：pytest 内置采集插件、结构化模型与文本降级。
2. Day 3–5：RepositoryIndex、ContextBuilder、评分和字符预算。
3. Day 6–7：结构化 ToolResult、分页、符号和引用工具。
4. Day 8–9：AgentRuntimeState、AgentStatus、CompletionPolicy 和 LoopGuard。
5. Day 10–11：FeedbackBuilder、Coordinator 接入与轨迹扩展。
6. Day 12：新增 15 个跨文件、干扰和 pytest 形态任务。
7. Day 13：运行四组消融实验；先单次全量，再对关键组重复 3 次。
8. Day 14：失败归因、公开结果、README、架构说明、演示与简历数据更新。

如进度落后，按顺序缩减：重复 3 次的范围、`inspect_module`、Level 3 用例数量。不得删除 pytest 结构化采集、ContextBuilder、状态栏、结构化反馈、离线测试和至少一轮可复现消融。

## 16. 完成标准

- pytest 8/9 主要失败可通过插件或回退解析，现有 `case_05`、`case_08` 不再因摘要格式提前失败。
- ContextBuilder 在预算内稳定选择失败测试、相关源码和跨文件依赖。
- Agent 每轮看到准确状态，重复和无进展路径有确定性终止原因。
- 修改后未查看 Diff 或未运行目标测试不能被 RepairAgent 视为完成。
- 下一轮获得上一轮候选修改和最新测试、Policy、Review、回归证据。
- 默认离线测试全部通过，覆盖率不低于当前 91%，Ruff 通过。
- Benchmark 共 30 个任务，四种 Arm 可运行、恢复和比较。
- 至少发布一组脱敏可复现结果，并明确模型、版本、样本量和限制。
- README 准确描述临时工作区与宿主 pytest 的安全边界。
- Docker、MCP、自动 PR 和多故障修复未进入本次实现。

## 17. 教程知识映射

本设计参考《深入理解 AI Agent：设计原理与工程实践》前五章：

- 1.1.1、1.1.4、1.1.5：观察空间、上下文与 ReAct。
- 1.2、1.2.6：Harness、护栏、验证、纠正和人工移交。
- 2.2、2.6、2.7：消息结构、Agent 状态栏和上下文控制。
- 3.3.1、3.3.2、3.3.4、3.3.5：结构化索引、文件系统范式、智能体化检索和上下文感知检索。
- 4.2、4.4、4.5：工具粒度、参数保真、感知与执行工具。
- 5.1.4、5.1.5、5.1.7、5.1.8、5.1.9：Coding Agent Harness、错误恢复、搜索、编辑与安全。
- 5.2.2、5.2.4：代码化规则与系统适配器。

本设计不因教程包含某项技术就默认引入。长期记忆、向量 RAG、MCP、异步、多 Agent 和执行沙盒均根据当前任务边界延后。
