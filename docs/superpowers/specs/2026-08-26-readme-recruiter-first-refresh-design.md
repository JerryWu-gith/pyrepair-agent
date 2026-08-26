# PyRepair README 求职展示版更新设计

## 状态

已批准。目标是更新本地与 GitHub README，使实习面试官能在 30 秒内理解项目价值，同时保留可复现的安装、运行与验证说明。

## 目标与受众

- 主要受众：Python / Agent 开发实习岗位的面试官和招聘者。
- 次要受众：希望本地试用 PyRepair 的开发者。
- 语言：中文为主，保留 Agent Loop、Tool Calling、Policy Gate、Review、benchmark 等英文技术名词。
- 语气：准确、克制、证据优先，不把端到端成功率描述为模型准确率。

## 非目标

- 不修改 PyRepair 的运行行为、CLI 参数或安全策略。
- 不引入 Docker、MCP、自动 Commit、自动 Push 或自动 PR。
- 不加入无法由仓库代码、测试或 benchmark 原始记录支持的宣传性结论。
- 不使用与项目无关的简历、面试手册或个人材料。

## README 信息结构

README 使用“求职证据链”结构：

1. **项目标题与一句话定位**：说明 PyRepair 是面向 Python/pytest 的安全候选补丁 Agent，而不是通用聊天机器人。
2. **30 秒看懂**：用输入、Agent 工作流和输出产物概括一次运行。
3. **项目亮点**：以表格连接技术机制与工程价值，覆盖：
   - AST 仓库索引与相对 import 邻居；
   - 确定性相关上下文排序与字符预算；
   - 8 个受限工具和稳定结构化结果；
   - 显式 Agent State、Loop Guard 与完成门禁；
   - 结构化失败反馈和多轮重试；
   - 临时工作区、Policy Gate、独立只读 Review、目标测试与全量回归。
4. **Agent Loop / 架构图**：更新 Mermaid 图，使流程与当前源码一致。
5. **快速开始**：保留 Windows PowerShell 可复制命令，包括安装、API Key、dry-run、正式修复和指定 pytest node id。
6. **安全边界**：明确不修改原仓库、不执行任意 Shell、不修改测试/CI/密钥/锁文件、不自动应用或上传补丁。
7. **最新 benchmark**：展示重新运行 15 个固定 case 后的端到端指标，并链接原始 JSONL 与报告。
8. **测试与复现**：列出离线测试、覆盖率、Ruff、live smoke 和 benchmark 命令。
9. **代码导读**：给出核心模块与职责映射，方便面试追问和源码阅读。
10. **局限与路线图**：只保留当前仍成立的限制，不再写已经修复的 pytest 9 兼容问题。

## Benchmark 更新方案

- 使用 `deepseek-v4-flash` 从头运行全部 15 个固定 case，不使用旧结果续跑。
- 运行命令：`python benchmarks/run_benchmark.py --model deepseek-v4-flash`。
- 以新生成的 JSONL 和 `docs/benchmark-results.md` 为唯一数据源。
- README 展示 case 数、成功率、首轮成功率、平均尝试次数、平均耗时、Token、回归与策略拒绝数。
- 每个失败 case 保留真实 failure reason；失败不会被删除或改写。
- 若 API Key 缺失、网络失败或 benchmark 中断，则停止更新指标，不沿用旧数据冒充新版结果。

## 内容真实性规则

- 工具数量从源码注册表核对，当前为 8 个。
- 安装和 CLI 命令从 `pyproject.toml`、`src/pyrepair/cli.py` 与命令测试核对。
- Agent Loop 从 `coordinator.py`、`repair_agent.py`、`agent_state.py`、`loop_guard.py` 和 `feedback.py` 核对。
- 安全声明从 `workspace.py`、`policy.py`、`tools.py` 与 `verifier.py` 核对。
- 测试数量和覆盖率只写本次实际验证结果。
- 不加入 CI passing badge；当前 GitHub Actions 受账户计费状态影响，不能作为代码质量证据。

## 错误处理与同步

- benchmark 任一 case 失败仍生成完整报告，README 按真实结果展示。
- benchmark 命令本身异常退出时，不提交半成品指标。
- README 中的相对链接和代码块必须通过现有 README 命令测试。
- 本地修改验证并提交后，使用普通 `git push origin main` 同步 GitHub，不强制推送。

## 验收标准

- README 不再包含“5 个工具”或“pytest 9 摘要尚未支持”等过时内容。
- README 顶部在一个屏幕内展示项目定位、核心差异和可量化证据。
- Mermaid 图与当前 8 工具、上下文、状态、循环守卫和验证链一致。
- 最新 benchmark 的 README 数字与 JSONL/报告一致。
- `tests/test_readme_commands.py`、全量离线测试、Ruff 和 wheel 构建通过。
- Git 工作区干净，本地 `main` 与 `origin/main` 指向同一提交。
