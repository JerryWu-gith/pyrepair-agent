# PyRepair Agent 保守清理设计

## 目标

清除本地运行测试、代码检查和生成 PDF 时产生的缓存及临时文件，使仓库目录更清晰，同时不改变项目结构、源码、测试、文档、评估数据或正式输出。

## 删除范围

- `.pytest_cache/`
- `.ruff_cache/`
- `.superpowers/`
- `.worktrees/`（当前为空）
- `tmp/`
- `.coverage`
- 仓库内所有 `__pycache__/` 目录

这些路径均为本地生成物，已被 `.gitignore` 忽略，不属于正式项目内容。

## 保留范围

- `.git/`、`.github/`
- `benchmarks/`，包括已提交的 JSONL 评估结果
- `docs/`
- `examples/`
- `output/pdf/`
- `scripts/`
- `src/pyrepair/`
- `tests/`
- `.env.example`、`.gitignore`、`pyproject.toml`、`README.md`
- 将来创建的 `.venv/`；它是本地开发环境，不纳入本次清理

## 执行与验证

1. 删除前逐项按仓库绝对路径确认目标存在。
2. 仅删除“删除范围”中列出的路径，不使用针对仓库根目录的递归删除。
3. 清理后检查正式顶层目录仍然存在。
4. 运行 `git status --short`，确认清理没有删除或修改受 Git 跟踪的文件。

本次清理不需要运行测试，因为不修改任何代码或配置。后续运行 pytest、ruff 或覆盖率工具时，相应缓存可能再次生成，属于正常行为。
