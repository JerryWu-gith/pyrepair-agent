# PyRepair Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用两周时间实现一个面向 Python/pytest 项目的安全候选补丁 Agent，支持本地 `pyrepair fix`、DeepSeek V4 Tool Calling、确定性安全检查、独立 Review、全量测试回归验证和可复现评测。

**Architecture:** CLI 只负责输入输出，`RepairCoordinator` 掌握固定流程；LLM 只能通过受限工具读取和修改临时副本，不能控制安全规则与最终成功判定。所有模型调用都经过可替换的 `ModelClient` 接口，使绝大多数测试使用 `FakeLLM` 离线运行，真实 DeepSeek 只用于手动 live smoke 和 benchmark。

**Tech Stack:** Python 3.11+、Typer、OpenAI Python SDK（连接 DeepSeek OpenAI-compatible API）、pytest、pytest-cov、Ruff、标准库 `dataclasses/pathlib/subprocess/tempfile/difflib/json`、GitHub Actions。

## Global Constraints

- 默认模型必须是 `deepseek-v4-flash`，只允许配置切换到 `deepseek-v4-pro`。
- 默认入口必须是 `pyrepair fix`；pytest 必须用参数列表调用 `python -m pytest -q --tb=short`，禁止 `shell=True`。
- API Key 只从 `DEEPSEEK_API_KEY` 读取；日志、报告和轨迹不得保存密钥。
- Agent 只能修改临时工作区；成功时只输出候选 Patch，不自动修改原项目，不 Commit、Push 或创建 PR。
- 禁止修改 `tests/`、`.env`、密钥、CI 配置和依赖锁文件；禁止新增 skip/xfail 或削弱断言。
- 每轮候选修改最多涉及 3 个源文件，新增与删除合计最多 80 行；总修复尝试最多 3 轮。
- 目标测试、全量测试、最终 PatchPolicyGate 必须全部通过；出现新的失败测试即为回归。
- 普通测试必须完全离线；真实 API 测试必须标记 `live` 并由开发者手动启用。
- MVP 内部数据对象使用 `dataclass`，不引入 Pydantic；外部边界需要强校验时再局部评估。
- 生产代码和测试均不得依赖用户已经掌握 Git 分支或 Pull Request。

---

## 0. 开工前学习门槛（Day 1 前 2–3 小时）

- [ ] 学完 Hello Agents 7.5.1，能口头解释工具基类、统一接口、工具注册和 JSON Schema。
- [ ] 学完 Hello Agents 7.5.2，独立写一个接收参数并返回统一结果的自定义工具。
- [ ] 阅读 7.5.4 的 ToolChain 思想，画出 `读取 → 修改 → 测试 → 验证` 的确定性顺序。
- [ ] 在练习目录执行并理解以下 Git 命令；只需理解“查看、暂存、提交”三个动作，不需要先学分支和 PR。

```powershell
git status
git add <文件路径>
git commit -m "说明这一步完成了什么"
git log --oneline -5
```

验收：不用看笔记，能解释“LLM 选择工具，但 Python 代码真正执行工具并判断结果”。

## 1. 文件结构与职责

```text
pyrepair-agent/
├── pyproject.toml                  # 构建、依赖、CLI、pytest 与 Ruff 配置
├── README.md                       # 安装、演示、限制、评测结果和简历表述
├── src/pyrepair/
│   ├── __init__.py                 # 包版本
│   ├── cli.py                      # Typer 命令和退出码
│   ├── config.py                   # 环境变量与固定默认值
│   ├── models.py                   # 跨模块 dataclass 与枚举
│   ├── testing.py                  # 安全运行 pytest
│   ├── pytest_parser.py            # pytest 文本转 FailureReport
│   ├── workspace.py                # 基线/工作副本、差异和清理
│   ├── tools.py                    # 五个受限工具与 ToolRegistry
│   ├── policy.py                   # 确定性 Patch 安全规则
│   ├── deepseek.py                 # ModelClient、DeepSeekClient 与消息转换
│   ├── repair_agent.py             # Tool Calling 循环
│   ├── review_agent.py             # 独立只读审查
│   ├── verifier.py                 # 目标/全量/回归/策略验证
│   ├── recorder.py                 # patch、JSON、JSONL、pytest 日志
│   └── coordinator.py              # 固定工作流和三轮状态机
├── tests/
│   ├── fixtures/                   # pytest 输出样本和小型仓库模板
│   ├── fakes.py                    # FakeLLM 与测试构造器
│   └── test_*.py                   # 对应模块测试
├── examples/buggy_bank/            # 可演示的有缺陷 Python 项目
├── benchmarks/
│   ├── cases/                      # 至少 15 个隔离 Bug 任务
│   ├── manifest.json               # 任务元数据，不含答案
│   └── run_benchmark.py            # 真实调用、汇总指标
└── .github/workflows/
    ├── ci.yml                      # 离线 CI
    └── pyrepair-demo.yml           # workflow_dispatch 手动演示
```

数据接口在 Task 1 一次定义，后续任务不得擅自改名；确需改变时，必须同步修改本计划中所有消费者。

### Task 1: 可安装包、核心数据模型与 CLI 外壳（Day 1）

**Files:**
- Create: `pyproject.toml`
- Create: `src/pyrepair/__init__.py`
- Create: `src/pyrepair/models.py`
- Create: `src/pyrepair/config.py`
- Create: `src/pyrepair/cli.py`
- Create: `tests/test_config.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: 环境变量 `DEEPSEEK_API_KEY`。
- Produces: `RepairRequest`、`TestRun`、`FailureReport`、`FileChange`、`PatchSnapshot`、`ToolCallRequest`、`ModelTurn`、`AgentRun`、`PatchCheck`、`ReviewResult`、`VerificationResult`、`RunResult`；`load_config()`；Typer `app`。

- [ ] **Step 1: 写配置和 CLI 的失败测试**

```python
# tests/test_config.py
import pytest
from pyrepair.config import ConfigError, load_config


def test_load_config_uses_flash_by_default(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    config = load_config()
    assert config.model == "deepseek-v4-flash"
    assert config.api_key == "test-key"


def test_load_config_rejects_unknown_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("PYREPAIR_MODEL", "unknown")
    with pytest.raises(ConfigError, match="PYREPAIR_MODEL"):
        load_config()
```

```python
# tests/test_cli.py
from typer.testing import CliRunner
from pyrepair.cli import app


runner = CliRunner()


def test_fix_help_shows_safe_defaults():
    result = runner.invoke(app, ["fix", "--help"])
    assert result.exit_code == 0
    assert "--model" in result.stdout
    assert "--max-attempts" in result.stdout
    assert "--dry-run" in result.stdout
```

- [ ] **Step 2: 运行测试并确认因包尚不存在而失败**

Run: `python -m pytest tests/test_config.py tests/test_cli.py -v`

Expected: collection 阶段出现 `ModuleNotFoundError: No module named 'pyrepair'`。

- [ ] **Step 3: 创建构建配置和固定数据接口**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "pyrepair-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["openai>=1.99,<3", "typer>=0.16,<1"]

[project.optional-dependencies]
dev = ["build>=1.2,<2", "pytest>=8,<10", "pytest-cov>=5,<8", "ruff>=0.12,<1"]

[project.scripts]
pyrepair = "pyrepair.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/pyrepair"]

[tool.pytest.ini_options]
addopts = "-m 'not live'"
markers = ["live: requires DEEPSEEK_API_KEY and makes a paid network request"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

```python
# src/pyrepair/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class RepairRequest:
    repo: Path
    test_target: str | None = None
    model: str = "deepseek-v4-flash"
    max_attempts: int = 3
    dry_run: bool = False
    verbose: bool = False


@dataclass(frozen=True)
class TestRun:
    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    launch_error: str | None = None


@dataclass(frozen=True)
class FailureReport:
    node_id: str | None
    exception_type: str | None
    traceback: str
    summary: str
    related_files: tuple[str, ...] = ()
    parseable: bool = True


@dataclass(frozen=True)
class FileChange:
    path: str
    old_text: str
    new_text: str
    diff: str
    added_lines: int
    deleted_lines: int


@dataclass(frozen=True)
class PatchSnapshot:
    changes: tuple[FileChange, ...]

    @property
    def text(self) -> str:
        return "".join(change.diff for change in self.changes)


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    content: str
    reasoning_content: str | None
    tool_calls: tuple[ToolCallRequest, ...]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stop_reason: str | None = None


@dataclass(frozen=True)
class AgentRun:
    completed: bool
    turns: tuple[ModelTurn, ...]
    failure_reason: str | None = None


@dataclass(frozen=True)
class PatchCheck:
    allowed: bool
    violations: tuple[str, ...]
    changed_files: tuple[str, ...]
    added_lines: int
    deleted_lines: int


@dataclass(frozen=True)
class ReviewResult:
    approved: bool
    risk: Literal["low", "medium", "high"]
    findings: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class VerificationResult:
    target_passed: bool
    full_suite_passed: bool
    regression_failures: tuple[str, ...]
    patch_check: PatchCheck

    @property
    def passed(self) -> bool:
        return (
            self.target_passed
            and self.full_suite_passed
            and not self.regression_failures
            and self.patch_check.allowed
        )


@dataclass(frozen=True)
class RunResult:
    status: Literal["success", "failed", "dry_run"]
    attempts: int
    artifact_dir: Path
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
# src/pyrepair/config.py
import os
from dataclasses import dataclass


ALLOWED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    model: str
    base_url: str = "https://api.deepseek.com"
    api_timeout_seconds: float = 90.0
    pytest_timeout_seconds: float = 120.0


def load_config(require_api_key: bool = True) -> AppConfig:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    model = os.getenv("PYREPAIR_MODEL", "deepseek-v4-flash")
    if require_api_key and not api_key:
        raise ConfigError("缺少 DEEPSEEK_API_KEY")
    if model not in ALLOWED_MODELS:
        raise ConfigError(f"PYREPAIR_MODEL 必须是 {sorted(ALLOWED_MODELS)} 之一")
    return AppConfig(api_key=api_key, model=model)
```

```python
# src/pyrepair/cli.py
from pathlib import Path
from typing import Annotated

import typer


app = typer.Typer(no_args_is_help=True)


@app.command()
def fix(
    target: Annotated[str | None, typer.Argument()] = None,
    repo: Annotated[Path, typer.Option()] = Path("."),
    model: Annotated[str, typer.Option()] = "deepseek-v4-flash",
    max_attempts: Annotated[int, typer.Option(min=1, max=3)] = 3,
    dry_run: Annotated[bool, typer.Option()] = False,
    verbose: Annotated[bool, typer.Option()] = False,
) -> None:
    """诊断 pytest 失败并生成安全的候选补丁。"""
    typer.echo(
        f"repo={repo.resolve()} target={target or 'full-suite'} "
        f"model={model} attempts={max_attempts} dry_run={dry_run} verbose={verbose}"
    )
```

- [ ] **Step 4: 安装开发包并运行测试、静态检查**

Run: `python -m pip install -e ".[dev]"`

Run: `python -m pytest tests/test_config.py tests/test_cli.py -v`

Run: `python -m ruff check src tests`

Expected: 3 个测试通过；Ruff 输出 `All checks passed!`。

- [ ] **Step 5: 验证命令入口并提交**

Run: `pyrepair fix --help`

Expected: 显示 `target`、`--repo`、`--model`、`--max-attempts`、`--dry-run`、`--verbose`。

```powershell
git add pyproject.toml src tests/test_config.py tests/test_cli.py
git commit -m "feat: scaffold pyrepair CLI and core models"
```

### Task 2: 安全 pytest 执行器（Day 2）

**Files:**
- Create: `src/pyrepair/testing.py`
- Create: `tests/test_testing.py`
- Create: `tests/fixtures/passing_project/test_ok.py`
- Create: `tests/fixtures/failing_project/test_fail.py`

**Interfaces:**
- Consumes: `models.TestRun`。
- Produces: `TestRunner(timeout_seconds: float).run(repo: Path, target: str | None = None) -> TestRun`。

- [ ] **Step 1: 写通过、失败和超时测试**

```python
from pathlib import Path
from pyrepair.testing import TestRunner


FIXTURES = Path(__file__).parent / "fixtures"


def test_runner_returns_pass_result():
    result = TestRunner(5).run(FIXTURES / "passing_project")
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.command[-3:] == ("-q", "--tb=short", "--disable-warnings")


def test_runner_returns_failed_result_without_throwing():
    result = TestRunner(5).run(FIXTURES / "failing_project")
    assert result.exit_code == 1
    assert "FAILED" in result.stdout


def test_runner_marks_timeout(monkeypatch, tmp_path):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(("python", "-m", "pytest"), 0.01)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    result = TestRunner(0.01).run(tmp_path)
    assert result.exit_code is None
    assert result.timed_out is True
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_testing.py -v`

Expected: `ModuleNotFoundError: No module named 'pyrepair.testing'`。

- [ ] **Step 3: 实现无 Shell 的执行器**

```python
# src/pyrepair/testing.py
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from .models import TestRun


class TestRunner:
    def __init__(self, timeout_seconds: float = 120.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, repo: Path, target: str | None = None) -> TestRun:
        command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "--disable-warnings"]
        if target:
            command.append(target)
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                encoding="utf-8",
                errors="replace",
            )
            return TestRun(
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            return TestRun(
                command=tuple(command),
                exit_code=None,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )
        except OSError as exc:
            return TestRun(
                command=tuple(command),
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=int((time.perf_counter() - started) * 1000),
                launch_error=str(exc),
            )
```

- [ ] **Step 4: 增加启动异常测试并验证**

```python
def test_runner_returns_launch_error(monkeypatch, tmp_path):
    def raise_os_error(*args, **kwargs):
        raise OSError("python unavailable")

    monkeypatch.setattr(subprocess, "run", raise_os_error)
    result = TestRunner(5).run(tmp_path)
    assert result.exit_code is None
    assert result.launch_error == "python unavailable"
```

Run: `python -m pytest tests/test_testing.py -v`

Expected: 4 个测试通过。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/testing.py tests/test_testing.py tests/fixtures
git commit -m "feat: run pytest with bounded subprocess execution"
```

### Task 3: pytest 失败解析器（Day 3）

**Files:**
- Create: `src/pyrepair/pytest_parser.py`
- Create: `tests/test_pytest_parser.py`
- Create: `tests/fixtures/pytest_outputs/assertion.txt`
- Create: `tests/fixtures/pytest_outputs/exception.txt`
- Create: `tests/fixtures/pytest_outputs/unparseable.txt`

**Interfaces:**
- Consumes: `TestRun`。
- Produces: `PytestParser.parse(run: TestRun) -> FailureReport`；`extract_failed_node_ids(text: str) -> set[str]`；只选择首个失败 node id。

- [ ] **Step 1: 写三个解析测试**

```python
from pyrepair.models import TestRun
from pyrepair.pytest_parser import PytestParser


def make_run(text: str) -> TestRun:
    return TestRun(("python", "-m", "pytest"), 1, text, "", 12)


def test_parse_first_failed_node_and_exception():
    report = PytestParser().parse(make_run(
        "FAILED tests/test_account.py::test_withdraw - ValueError: insufficient funds\n"
    ))
    assert report.node_id == "tests/test_account.py::test_withdraw"
    assert report.exception_type == "ValueError"
    assert report.summary == "insufficient funds"


def test_parse_keeps_related_python_paths():
    report = PytestParser().parse(make_run(
        "account/service.py:18: in withdraw\nFAILED tests/test_account.py::test_withdraw - AssertionError\n"
    ))
    assert "account/service.py" in report.related_files


def test_unparseable_output_is_explicit():
    report = PytestParser().parse(make_run("pytest stopped unexpectedly"))
    assert report.parseable is False
    assert report.node_id is None
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_pytest_parser.py -v`

Expected: 缺少 `pyrepair.pytest_parser` 导致失败。

- [ ] **Step 3: 实现保守解析**

```python
# src/pyrepair/pytest_parser.py
import re

from .models import FailureReport, TestRun


FAILED_RE = re.compile(r"^FAILED\s+(?P<node>\S+)\s+-\s+(?:(?P<exc>[\w.]+):\s*)?(?P<summary>.*)$", re.M)
PATH_RE = re.compile(r"(?m)^([\w./\\-]+\.py):\d+")


class PytestParser:
    def parse(self, run: TestRun) -> FailureReport:
        raw = "\n".join(part for part in (run.stdout, run.stderr) if part)
        match = FAILED_RE.search(raw)
        related = tuple(dict.fromkeys(path.replace("\\", "/") for path in PATH_RE.findall(raw)))
        if not match:
            return FailureReport(None, None, raw[-6000:], raw[-500:], related, False)
        return FailureReport(
            node_id=match.group("node"),
            exception_type=match.group("exc"),
            traceback=raw[-6000:],
            summary=match.group("summary").strip(),
            related_files=related,
            parseable=True,
        )


def extract_failed_node_ids(text: str) -> set[str]:
    return {match.group("node") for match in FAILED_RE.finditer(text)}
```

- [ ] **Step 4: 运行解析测试和全量离线测试**

Run: `python -m pytest tests/test_pytest_parser.py -v`

Run: `python -m pytest -q`

Expected: 所有测试通过，live 测试数量为 0。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/pytest_parser.py tests/test_pytest_parser.py tests/fixtures/pytest_outputs
git commit -m "feat: parse pytest failures into structured reports"
```

### Task 4: 临时安全工作区与候选 Diff（Day 4）

**Files:**
- Create: `src/pyrepair/workspace.py`
- Create: `tests/test_workspace.py`

**Interfaces:**
- Consumes: `FileChange`、`PatchSnapshot`。
- Produces: `WorkspaceManager.create(repo: Path) -> WorkspaceSession`、`WorkspaceSession.snapshot() -> PatchSnapshot`、`WorkspaceSession.restore_working_from_baseline()`、`WorkspaceSession.cleanup()`。

- [ ] **Step 1: 写隔离、排除和 Diff 测试**

```python
def test_workspace_changes_do_not_touch_source(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    session = WorkspaceManager().create(repo)
    (session.working / "app.py").write_text("value = 2\n", encoding="utf-8")
    snapshot = session.snapshot()
    assert (repo / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    assert snapshot.changes[0].path == "app.py"
    assert "+value = 2" in snapshot.text


def test_workspace_excludes_git_env_and_cache(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in (".git", ".venv", "__pycache__", ".pyrepair"):
        (repo / name).mkdir()
    session = WorkspaceManager().create(repo)
    assert all(not (session.working / name).exists() for name in (".git", ".venv", "__pycache__", ".pyrepair"))
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/test_workspace.py -v`

Expected: 缺少 `pyrepair.workspace`。

- [ ] **Step 3: 实现 baseline/working 双副本和 unified diff**

```python
# src/pyrepair/workspace.py 核心接口
EXCLUDED_NAMES = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".pyrepair"}


@dataclass
class WorkspaceSession:
    root: Path
    baseline: Path
    working: Path

    def snapshot(self) -> PatchSnapshot:
        paths = sorted(
            {p.relative_to(self.baseline) for p in self.baseline.rglob("*") if p.is_file()}
            | {p.relative_to(self.working) for p in self.working.rglob("*") if p.is_file()}
        )
        changes: list[FileChange] = []
        for relative in paths:
            old = _read_text_or_empty(self.baseline / relative)
            new = _read_text_or_empty(self.working / relative)
            if old == new:
                continue
            diff_lines = list(difflib.unified_diff(
                old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile=f"a/{relative.as_posix()}", tofile=f"b/{relative.as_posix()}",
            ))
            changes.append(FileChange(
                relative.as_posix(), old, new, "".join(diff_lines),
                sum(line.startswith("+") and not line.startswith("+++") for line in diff_lines),
                sum(line.startswith("-") and not line.startswith("---") for line in diff_lines),
            ))
        return PatchSnapshot(tuple(changes))

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)

    def restore_working_from_baseline(self) -> None:
        shutil.rmtree(self.working)
        shutil.copytree(self.baseline, self.working)
```

`WorkspaceManager.create()` 使用 `tempfile.mkdtemp(prefix="pyrepair-")`，验证 `repo.resolve()` 是目录且包含 `.py` 文件，再用 `shutil.copytree(..., ignore=...)` 分别创建 baseline 和 working；任何失败都清理已创建目录并抛出带阶段信息的 `WorkspaceError`。

- [ ] **Step 4: 补齐异常清理测试并验证**

```python
def test_workspace_rejects_repo_without_python(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    with pytest.raises(WorkspaceError, match="Python"):
        WorkspaceManager().create(repo)


def test_restore_discards_previous_attempt_and_cleanup_removes_root(tmp_path):
    repo = make_python_repo(tmp_path)
    session = WorkspaceManager().create(repo)
    (session.working / "app.py").write_text("changed = True\n", encoding="utf-8")
    session.restore_working_from_baseline()
    assert (session.working / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    root = session.root
    session.cleanup()
    assert root.exists() is False
```

Run: `python -m pytest tests/test_workspace.py -v`

Expected: 隔离、排除、Diff、无效仓库和清理测试全部通过。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/workspace.py tests/test_workspace.py
git commit -m "feat: isolate repairs in temporary workspaces"
```

### Task 5: 受限工具与 ToolRegistry（Day 5）

**Files:**
- Create: `src/pyrepair/tools.py`
- Create: `tests/test_tools.py`

**Interfaces:**
- Consumes: `WorkspaceSession`、`TestRunner`、`FailureReport.node_id`。
- Produces: `ToolResult`、`BaseTool`、`ToolRegistry.schemas()`、`ToolRegistry.execute(name, arguments)`；工具名固定为 `read_file`、`search_code`、`replace_text`、`show_diff`、`run_target_test`。

- [ ] **Step 1: 写路径越界、精确替换和 Schema 测试**

```python
def test_read_file_rejects_parent_escape(tool_registry):
    result = tool_registry.execute("read_file", {"path": "../secret.txt"})
    assert result.ok is False
    assert result.error == "path_outside_workspace"


def test_replace_text_requires_exactly_one_match(tool_registry):
    path = tool_registry.workspace / "app.py"
    path.write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = tool_registry.execute("replace_text", {
        "path": "app.py", "old_text": "x = 1", "new_text": "x = 2"
    })
    assert result.ok is False
    assert result.error == "expected_one_match_found_2"


def test_registry_exports_openai_function_schema(tool_registry):
    schemas = tool_registry.schemas()
    assert {item["function"]["name"] for item in schemas} == {
        "read_file", "search_code", "replace_text", "show_diff", "run_target_test"
    }
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_tools.py -v`

Expected: 缺少 `pyrepair.tools`。

- [ ] **Step 3: 实现统一工具结果和路径约束**

```python
@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str = ""
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def resolve_inside(root: Path, user_path: str) -> Path:
    candidate = (root / user_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ToolError("path_outside_workspace") from exc
    return candidate
```

每个工具实现 `name`、`description`、`parameters` 和 `execute(**arguments) -> ToolResult`。`read_file` 最多返回 20,000 字符；`search_code` 只遍历 `.py` 文件并最多返回 50 条；`replace_text` 要求旧文本恰好出现一次且路径不在 `tests/`；`show_diff` 调用 `session.snapshot()`；`run_target_test` 的 node id 只能使用 Parser 已识别的值，不能接受模型传入的新命令。

- [ ] **Step 4: 补齐所有工具的正反例并验证**

至少增加：不存在文件、二进制文件、搜索上限、禁止改 tests、成功替换、Diff 输出、固定 node id 七个测试。

Run: `python -m pytest tests/test_tools.py -v`

Expected: 工具正反例全部通过，任何越界路径都返回结构化错误而不是读取文件。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/tools.py tests/test_tools.py
git commit -m "feat: add restricted repair tool registry"
```

### Task 6: 确定性 PatchPolicyGate（Day 6）

**Files:**
- Create: `src/pyrepair/policy.py`
- Create: `tests/test_policy.py`

**Interfaces:**
- Consumes: `PatchSnapshot`。
- Produces: `PatchPolicyGate.check(snapshot: PatchSnapshot) -> PatchCheck`。

- [ ] **Step 1: 写安全边界测试矩阵**

```python
@pytest.mark.parametrize("path", [
    "tests/test_app.py", ".env", ".github/workflows/ci.yml",
    "poetry.lock", "uv.lock", "requirements.lock",
])
def test_policy_rejects_protected_paths(path):
    check = PatchPolicyGate().check(snapshot(path, "x = 1\n", "x = 2\n"))
    assert check.allowed is False
    assert any("protected_path" in item for item in check.violations)


def test_policy_rejects_skip_xfail_and_weakened_assertion():
    changed = snapshot("app.py", "assert value == 3\n", "pytest.skip('later')\nassert value\n")
    check = PatchPolicyGate().check(changed)
    assert {v.split(":", 1)[0] for v in check.violations} >= {"test_bypass", "assertion_weakened"}


def test_policy_rejects_more_than_three_files_or_eighty_lines():
    check = PatchPolicyGate().check(large_snapshot(file_count=4, added_lines=81))
    assert check.allowed is False
    assert "too_many_files:4>3" in check.violations
    assert "too_many_changed_lines:81>80" in check.violations
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_policy.py -v`

Expected: 缺少 `pyrepair.policy`。

- [ ] **Step 3: 实现纯函数规则门**

```python
class PatchPolicyGate:
    def check(self, snapshot: PatchSnapshot) -> PatchCheck:
        violations: list[str] = []
        paths = tuple(change.path for change in snapshot.changes)
        added = sum(change.added_lines for change in snapshot.changes)
        deleted = sum(change.deleted_lines for change in snapshot.changes)
        for change in snapshot.changes:
            path = PurePosixPath(change.path)
            if _is_protected(path):
                violations.append(f"protected_path:{change.path}")
            if path.suffix not in {".py", ".pyi"}:
                violations.append(f"non_source_file:{change.path}")
            if re.search(r"pytest\.(skip|xfail)|@pytest\.mark\.(skip|xfail)", change.new_text):
                violations.append(f"test_bypass:{change.path}")
            if _weakens_assertions(change.old_text, change.new_text):
                violations.append(f"assertion_weakened:{change.path}")
        if len(paths) > 3:
            violations.append(f"too_many_files:{len(paths)}>3")
        if added + deleted > 80:
            violations.append(f"too_many_changed_lines:{added + deleted}>80")
        return PatchCheck(not violations, tuple(violations), paths, added, deleted)
```

`_weakens_assertions()` 比较旧、新文本中 `assert` 行数量，并拒绝把带比较运算符的断言替换为仅真值判断；这是保守启发式，规则触发时宁可要求下一轮缩小修改。

- [ ] **Step 4: 验证允许的最小源码修复**

新增测试：只修改 `src/account.py` 一行条件判断时 `allowed is True`，统计为 added=1、deleted=1。

Run: `python -m pytest tests/test_policy.py -v`

Expected: 安全矩阵和允许用例全部通过。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/policy.py tests/test_policy.py
git commit -m "feat: enforce deterministic patch safety policy"
```

### Task 7: DeepSeekProvider 与可替换 FakeLLM（Day 7）

**Files:**
- Create: `src/pyrepair/deepseek.py`
- Create: `tests/fakes.py`
- Create: `tests/test_deepseek.py`

**Interfaces:**
- Consumes: OpenAI-compatible `messages`、工具 Schema、`ModelTurn`。
- Produces: `ModelClient` Protocol；`DeepSeekClient.complete(messages, tools) -> ModelTurn`；测试用 `FakeLLM`。

- [ ] **Step 1: 写消息转换、Thinking 回传、重试和脱敏测试**

```python
def test_complete_maps_tool_call_and_usage(fake_openai):
    fake_openai.queue(tool_response(
        reasoning_content="inspect file",
        call_id="call-1",
        name="read_file",
        arguments='{"path":"app.py"}',
        prompt_tokens=12,
        completion_tokens=7,
    ))
    turn = make_client(fake_openai).complete([{"role": "user", "content": "fix"}], [])
    assert turn.reasoning_content == "inspect file"
    assert turn.tool_calls[0].arguments == {"path": "app.py"}
    assert turn.prompt_tokens == 12


def test_complete_enables_thinking_and_uses_configured_model(fake_openai):
    fake_openai.queue(text_response("done"))
    make_client(fake_openai, model="deepseek-v4-flash").complete([], [])
    request = fake_openai.last_request
    assert request["model"] == "deepseek-v4-flash"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request["reasoning_effort"] == "high"
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_deepseek.py -v`

Expected: 缺少 `pyrepair.deepseek`。

- [ ] **Step 3: 实现协议与官方请求格式**

```python
class ModelClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        ...


class DeepSeekClient:
    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 90.0) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        message = response.choices[0].message
        calls = tuple(ToolCallRequest(
            id=call.id,
            name=call.function.name,
            arguments=json.loads(call.function.arguments),
        ) for call in (message.tool_calls or ()))
        usage = response.usage
        return ModelTurn(
            content=message.content or "",
            reasoning_content=getattr(message, "reasoning_content", None),
            tool_calls=calls,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            stop_reason=response.choices[0].finish_reason,
        )
```

对网络超时、429 和 5xx 最多重试 2 次，退避 1 秒、2 秒；无效 JSON tool arguments 直接返回 `DeepSeekError("invalid_tool_arguments")`，不得执行工具。错误字符串不得拼入 API Key 或完整请求头。

- [ ] **Step 4: 实现确定性的 FakeLLM 并验证**

```python
class FakeLLM:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = deque(turns)
        self.requests: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def complete(self, messages, tools) -> ModelTurn:
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        if not self.turns:
            raise AssertionError("FakeLLM 没有剩余响应")
        return self.turns.popleft()
```

Run: `python -m pytest tests/test_deepseek.py -v`

Expected: 消息映射、Thinking 参数、JSON 拒绝、重试和 FakeLLM 测试全部通过。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/deepseek.py tests/fakes.py tests/test_deepseek.py
git commit -m "feat: add DeepSeek V4 model client and fake LLM"
```

### Task 8: RepairAgent Tool Calling 循环（Day 8）

**Files:**
- Create: `src/pyrepair/repair_agent.py`
- Create: `tests/test_repair_agent.py`

**Interfaces:**
- Consumes: `ModelClient`、`ToolRegistry`、`FailureReport`、上一轮证据字符串。
- Produces: `RepairAgent.run(report, previous_evidence=()) -> AgentRun`。

- [ ] **Step 1: 写两次工具调用、reasoning_content 回传和上限测试**

```python
def test_agent_executes_tool_calls_and_returns_results(registry):
    llm = FakeLLM([
        model_tool_turn("call-1", "read_file", {"path": "app.py"}, reasoning="inspect"),
        model_tool_turn("call-2", "replace_text", {
            "path": "app.py", "old_text": "return a - b", "new_text": "return a + b"
        }, reasoning="repair"),
        model_text_turn("repair complete"),
    ])
    result = RepairAgent(llm, registry, max_tool_calls=8).run(failure_report())
    assert result.completed is True
    assert '"role": "tool"' in json.dumps(llm.requests, default=str)
    assert llm.requests[1][0][-2]["reasoning_content"] == "inspect"


def test_agent_stops_at_tool_call_limit(registry):
    llm = FakeLLM([model_tool_turn(f"call-{i}", "show_diff", {}) for i in range(4)])
    result = RepairAgent(llm, registry, max_tool_calls=3).run(failure_report())
    assert result.completed is False
    assert result.failure_reason == "max_tool_calls_exceeded"
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_repair_agent.py -v`

Expected: 缺少 `pyrepair.repair_agent`。

- [ ] **Step 3: 实现固定系统提示和循环**

系统提示必须包含：只修生产源码、寻找根因、最小修改、禁止测试绕过、必须查看 Diff 并运行目标测试、工具错误需要调整参数而不是伪造成功。

```python
def _assistant_message(turn: ModelTurn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.content,
        "reasoning_content": turn.reasoning_content,
        "tool_calls": [{
            "id": call.id,
            "type": "function",
            "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
        } for call in turn.tool_calls],
    }


class RepairAgent:
    def run(self, report: FailureReport, previous_evidence: tuple[str, ...] = ()) -> AgentRun:
        messages = self._initial_messages(report, previous_evidence)
        turns: list[ModelTurn] = []
        calls_used = 0
        while calls_used < self.max_tool_calls:
            turn = self.client.complete(messages, self.registry.schemas())
            turns.append(turn)
            messages.append(_assistant_message(turn))
            if not turn.tool_calls:
                return AgentRun(True, tuple(turns))
            for call in turn.tool_calls:
                calls_used += 1
                if calls_used > self.max_tool_calls:
                    return AgentRun(False, tuple(turns), "max_tool_calls_exceeded")
                result = self.registry.execute(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result.to_json()})
        return AgentRun(False, tuple(turns), "max_tool_calls_exceeded")
```

- [ ] **Step 4: 验证未知工具、工具参数错误和无工具结束**

```python
def test_agent_returns_unknown_tool_result_to_model(registry):
    llm = FakeLLM([
        model_tool_turn("call-1", "delete_repository", {}),
        model_text_turn("cannot use that tool"),
    ])
    result = RepairAgent(llm, registry, max_tool_calls=3).run(failure_report())
    assert result.completed is True
    assert "unknown_tool" in json.dumps(llm.requests, default=str)


def test_agent_can_end_without_tool_call(registry):
    result = RepairAgent(
        FakeLLM([model_text_turn("not enough evidence")]), registry, max_tool_calls=3
    ).run(failure_report())
    assert result.completed is True
```

工作区是否真正产生 Diff 由 Coordinator 检查；RepairAgent 不自行宣称补丁成功。

Run: `python -m pytest tests/test_repair_agent.py -v`

Expected: 所有 Agent Loop 测试通过，并明确证明 `reasoning_content` 随工具调用回传。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/repair_agent.py tests/test_repair_agent.py
git commit -m "feat: implement bounded repair agent loop"
```

### Task 9: 独立只读 Review Agent（Day 9）

**Files:**
- Create: `src/pyrepair/review_agent.py`
- Create: `tests/test_review_agent.py`

**Interfaces:**
- Consumes: 独立 `ModelClient` 会话、`FailureReport`、`PatchSnapshot`。
- Produces: `ReviewAgent.review(report, snapshot) -> ReviewResult`；不接收 ToolRegistry。

- [ ] **Step 1: 写批准、拒绝和坏 JSON 测试**

```python
def test_review_approves_low_risk_root_cause_fix():
    llm = FakeLLM([model_text_turn(
        '{"approved":true,"risk":"low","findings":[],"reason":"修复边界条件"}'
    )])
    result = ReviewAgent(llm).review(failure_report(), patch_snapshot())
    assert result.approved is True
    assert llm.requests[0][1] == []


def test_review_rejects_invalid_json():
    result = ReviewAgent(FakeLLM([model_text_turn("looks fine")])).review(
        failure_report(), patch_snapshot()
    )
    assert result.approved is False
    assert result.risk == "high"
    assert "invalid_review_json" in result.findings
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_review_agent.py -v`

Expected: 缺少 `pyrepair.review_agent`。

- [ ] **Step 3: 实现严格字段校验**

Review 请求只包含故障摘要、traceback 和 Diff，提示模型返回单个 JSON 对象。手写校验：`approved` 必须为 bool，`risk` 必须属于 low/medium/high，`findings` 必须为字符串列表，`reason` 必须为非空字符串；解析或校验失败时返回高风险拒绝结果，不抛出裸 JSON 异常。

```python
def _parse_review(content: str) -> ReviewResult:
    try:
        data = json.loads(content)
        valid = (
            isinstance(data.get("approved"), bool)
            and data.get("risk") in {"low", "medium", "high"}
            and isinstance(data.get("findings"), list)
            and all(isinstance(item, str) for item in data["findings"])
            and isinstance(data.get("reason"), str)
            and bool(data["reason"].strip())
        )
        if not valid:
            raise ValueError("invalid fields")
        return ReviewResult(data["approved"], data["risk"], tuple(data["findings"]), data["reason"])
    except (json.JSONDecodeError, TypeError, ValueError):
        return ReviewResult(False, "high", ("invalid_review_json",), "Review 输出无法安全解析")
```

- [ ] **Step 4: 验证 Review 没有写权限**

测试断言 Review 的模型请求 `tools == []`，并在 review 前后比较 `snapshot.text` 不变。

Run: `python -m pytest tests/test_review_agent.py -v`

Expected: 所有测试通过。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/review_agent.py tests/test_review_agent.py
git commit -m "feat: add independent read-only patch reviewer"
```

### Task 10: 目标、全量、回归和最终策略验证（Day 10）

**Files:**
- Create: `src/pyrepair/verifier.py`
- Create: `tests/test_verifier.py`

**Interfaces:**
- Consumes: `TestRunner`、基线失败 node id 集合、`FailureReport`、`PatchSnapshot`、`PatchPolicyGate`。
- Produces: `Verifier.verify(repo, target_node_id, baseline_failures, snapshot) -> VerificationResult`。

- [ ] **Step 1: 写完整成功和新增回归测试**

```python
def test_verify_requires_target_full_suite_and_policy(runner, allowed_snapshot):
    runner.queue(exit_code=0, stdout="1 passed")
    runner.queue(exit_code=0, stdout="12 passed")
    result = Verifier(runner, PatchPolicyGate()).verify(
        Path("work"), "tests/test_app.py::test_add", {"tests/test_app.py::test_add"}, allowed_snapshot
    )
    assert result.passed is True


def test_verify_reports_new_failure_as_regression(runner, allowed_snapshot):
    runner.queue(exit_code=0, stdout="1 passed")
    runner.queue(exit_code=1, stdout="FAILED tests/test_other.py::test_other - AssertionError")
    result = Verifier(runner, PatchPolicyGate()).verify(
        Path("work"), "tests/test_app.py::test_add", {"tests/test_app.py::test_add"}, allowed_snapshot
    )
    assert result.full_suite_passed is False
    assert result.regression_failures == ("tests/test_other.py::test_other",)
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_verifier.py -v`

Expected: 缺少 `pyrepair.verifier`。

- [ ] **Step 3: 实现固定顺序验证**

```python
class Verifier:
    def verify(
        self,
        repo: Path,
        target_node_id: str,
        baseline_failures: set[str],
        snapshot: PatchSnapshot,
    ) -> VerificationResult:
        target = self.runner.run(repo, target_node_id)
        if target.exit_code != 0:
            return VerificationResult(False, False, (), self.policy.check(snapshot))
        full = self.runner.run(repo)
        current = extract_failed_node_ids(full.stdout + "\n" + full.stderr)
        regressions = tuple(sorted(current - baseline_failures))
        return VerificationResult(
            target_passed=True,
            full_suite_passed=full.exit_code == 0,
            regression_failures=regressions,
            patch_check=self.policy.check(snapshot),
        )
```

- [ ] **Step 4: 覆盖短路和策略二次拒绝**

新增测试：目标测试失败时不运行全量测试；最终 Diff 超过 80 行时，即使两个测试返回通过，`passed` 仍为 False。

Run: `python -m pytest tests/test_verifier.py -v`

Expected: 验证顺序、回归集合和最终规则测试全部通过。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/verifier.py tests/test_verifier.py
git commit -m "feat: verify target tests full suite and regressions"
```

### Task 11: 产物记录器（Day 10）

**Files:**
- Create: `src/pyrepair/recorder.py`
- Create: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `RunResult` 相关 dataclass、`PatchSnapshot`、事件字典和 pytest 文本。
- Produces: `.pyrepair/runs/<UTC-run-id>/fix.patch`、`report.json`、`trace.jsonl`、`pytest.log`。

- [ ] **Step 1: 写四产物与密钥脱敏测试**

```python
def test_recorder_writes_four_artifacts_and_redacts_secrets(tmp_path):
    recorder = RunRecorder(tmp_path, run_id="20260812T120000Z-test")
    recorder.write_patch(patch_snapshot())
    recorder.write_report({"status": "success", "api_key": "sk-secret"})
    recorder.append_event({"type": "model", "authorization": "Bearer sk-secret"})
    recorder.append_pytest("1 passed")
    names = {p.name for p in recorder.run_dir.iterdir()}
    assert names == {"fix.patch", "report.json", "trace.jsonl", "pytest.log"}
    combined = "".join(p.read_text(encoding="utf-8") for p in recorder.run_dir.iterdir())
    assert "sk-secret" not in combined
    assert "[REDACTED]" in combined
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_recorder.py -v`

Expected: 缺少 `pyrepair.recorder`。

- [ ] **Step 3: 实现原子写入和递归脱敏**

```python
SENSITIVE_KEYS = {"api_key", "authorization", "token", "secret"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
```

`report.json` 使用 `json.dumps(..., ensure_ascii=False, indent=2)`；`trace.jsonl` 每次追加一个脱敏 JSON 对象；pytest.log 为基线、目标和全量输出添加明确段落标题。

- [ ] **Step 4: 验证 JSON 可重新读取和失败运行无 Patch**

新增测试：`json.loads(report.json)` 成功；失败运行允许 `fix.patch` 内容为空，但文件必须存在并在 report 中写 `status=failed`。

Run: `python -m pytest tests/test_recorder.py -v`

Expected: 所有产物和脱敏测试通过。

- [ ] **Step 5: 提交**

```powershell
git add src/pyrepair/recorder.py tests/test_recorder.py
git commit -m "feat: record reproducible repair artifacts"
```

### Task 12: Coordinator 三轮闭环与真实 CLI（Day 11）

**Files:**
- Create: `src/pyrepair/coordinator.py`
- Modify: `src/pyrepair/cli.py`
- Create: `tests/test_coordinator.py`
- Modify: `tests/test_cli.py`
- Create: `examples/buggy_bank/bank.py`
- Create: `examples/buggy_bank/tests/test_bank.py`

**Interfaces:**
- Consumes: 前面全部模块；构造注入 `TestRunner`、`PytestParser`、Agent 工厂、Policy、Review、Verifier、Recorder、WorkspaceManager。
- Produces: `RepairCoordinator.run(request: RepairRequest) -> RunResult`；CLI 退出码 0=成功/诊断完成，1=业务失败，2=配置或基础设施错误。

构造签名固定为：

```python
class RepairCoordinator:
    def __init__(
        self,
        workspaces: WorkspaceManager,
        runner: TestRunner,
        parser: PytestParser,
        registry_factory: Callable[[WorkspaceSession, str], ToolRegistry],
        agent_factory: Callable[[ToolRegistry], RepairAgent],
        policy: PatchPolicyGate,
        reviewer: ReviewAgent,
        verifier: Verifier,
        recorder_factory: Callable[[Path], RunRecorder],
    ) -> None:
        self.workspaces = workspaces
        self.runner = runner
        self.parser = parser
        self.registry_factory = registry_factory
        self.agent_factory = agent_factory
        self.policy = policy
        self.reviewer = reviewer
        self.verifier = verifier
        self.recorder_factory = recorder_factory
```

- [ ] **Step 1: 写 FakeLLM 成功闭环和三轮失败测试**

```python
def test_coordinator_generates_patch_without_touching_original(tmp_path, coordinator):
    repo = make_buggy_repo(tmp_path)
    original = (repo / "bank.py").read_text(encoding="utf-8")
    result = coordinator.run(RepairRequest(repo=repo))
    assert result.status == "success"
    assert (repo / "bank.py").read_text(encoding="utf-8") == original
    assert (result.artifact_dir / "fix.patch").read_text(encoding="utf-8")


def test_coordinator_stops_after_three_rejected_attempts(tmp_path, rejecting_coordinator):
    result = rejecting_coordinator.run(RepairRequest(repo=make_buggy_repo(tmp_path), max_attempts=3))
    assert result.status == "failed"
    assert result.attempts == 3
    assert result.failure_reason == "max_attempts_exceeded"
```

- [ ] **Step 2: 确认测试失败**

Run: `python -m pytest tests/test_coordinator.py -v`

Expected: 缺少 `pyrepair.coordinator`。

- [ ] **Step 3: 实现 Python 掌控的状态机**

```python
def run(self, request: RepairRequest) -> RunResult:
    session = self.workspaces.create(request.repo)
    recorder = self.recorder_factory(request.repo)
    evidence: list[str] = []
    try:
        baseline = self.runner.run(session.working, request.test_target)
        recorder.append_pytest("BASELINE\n" + baseline.stdout + baseline.stderr)
        report = self.parser.parse(baseline)
        if baseline.exit_code == 0:
            return self._finish(recorder, "failed", 0, "tests_already_pass")
        if not report.parseable or not report.node_id:
            return self._finish(recorder, "failed", 0, "unparseable_pytest_output", report=report)
        if request.dry_run:
            return self._finish(recorder, "dry_run", 0, None, report=report)
        baseline_failures = extract_failed_node_ids(baseline.stdout + baseline.stderr)
        for attempt in range(1, request.max_attempts + 1):
            session.restore_working_from_baseline()
            registry = self.registry_factory(session, report.node_id)
            agent_run = self.agent_factory(registry).run(report, tuple(evidence))
            snapshot = session.snapshot()
            check = self.policy.check(snapshot)
            if not snapshot.changes:
                evidence.append("no_patch_generated")
                continue
            if not agent_run.completed or not check.allowed:
                evidence.append(self._attempt_evidence(agent_run, check))
                continue
            review = self.reviewer.review(report, snapshot)
            if not review.approved:
                evidence.append(self._review_evidence(review))
                continue
            verification = self.verifier.verify(
                session.working, report.node_id or "", baseline_failures, snapshot
            )
            if verification.passed:
                recorder.write_patch(snapshot)
                return self._finish(recorder, "success", attempt, None,
                                    report=report, review=review, verification=verification)
            evidence.append(self._verification_evidence(verification))
        return self._finish(recorder, "failed", request.max_attempts, "max_attempts_exceeded")
    finally:
        session.cleanup()
```

所有早退路径必须调用 Recorder；`finally` 必须清理临时目录。每轮开始从 baseline 恢复，上一轮只把结构化失败证据带给模型，不保留违规文件修改。

- [ ] **Step 4: 把 CLI 接到 Coordinator 并验证用户可读输出**

CLI 根据选项构造 `RepairRequest`，加载 Config 和依赖，显示 `baseline → attempt N → policy → review → verify → artifact` 阶段。捕获 `ConfigError/WorkspaceError/DeepSeekError` 后只显示中文原因和产物位置；`--verbose` 才显示异常类型，但永不显示 API Key。

Run: `python -m pytest tests/test_coordinator.py tests/test_cli.py -v`

Expected: 成功、dry-run、策略拒绝、Review 拒绝、回归、三轮上限、异常清理和 CLI 退出码测试全部通过。

- [ ] **Step 5: 运行离线质量门并提交**

Run: `python -m pytest --cov=pyrepair --cov-report=term-missing -q`

Run: `python -m ruff check src tests benchmarks`

Expected: 0 failures；核心模块总覆盖率至少 85%；Ruff 无错误。

```powershell
git add src/pyrepair/cli.py src/pyrepair/coordinator.py tests examples/buggy_bank
git commit -m "feat: complete safe repair workflow and CLI"
```

### Task 13: DeepSeek live smoke（Day 12）

**Files:**
- Create: `tests/test_live_deepseek.py`
- Create: `.env.example`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `DEEPSEEK_API_KEY`、`DeepSeekClient`、只读 `show_diff` 测试工具 Schema。
- Produces: 手动 `python -m pytest -m live -v` 鉴权和 Tool Calling 兼容性证据。

- [ ] **Step 1: 写默认跳过的真实 API 测试**

```python
@pytest.mark.live
def test_deepseek_v4_flash_can_request_a_tool():
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        pytest.skip("set DEEPSEEK_API_KEY to run paid live test")
    client = DeepSeekClient(key, "deepseek-v4-flash", "https://api.deepseek.com")
    turn = client.complete(
        [{"role": "user", "content": "必须调用 show_diff 工具查看候选修改。"}],
        [{"type": "function", "function": {
            "name": "show_diff", "description": "Show candidate diff",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        }}],
    )
    assert turn.tool_calls
    assert turn.tool_calls[0].name == "show_diff"
    assert turn.reasoning_content is not None
```

- [ ] **Step 2: 证明普通测试不会调用网络**

Run: `python -m pytest -q`

Expected: live 用例显示 deselected，其他测试全部通过；没有 `DEEPSEEK_API_KEY` 也能完成。

- [ ] **Step 3: 添加安全环境变量示例**

```dotenv
# .env.example
DEEPSEEK_API_KEY=replace-with-your-own-key
PYREPAIR_MODEL=deepseek-v4-flash
```

`.gitignore` 必须包含 `.env`，但不得忽略 `.env.example`。

- [ ] **Step 4: 手动运行一次真实调用**

PowerShell 当前会话设置密钥：`$env:DEEPSEEK_API_KEY="你自己的密钥"`

Run: `python -m pytest -m live -v`

Expected: 1 个 live 测试通过，返回 `show_diff` Tool Call 和非空 `reasoning_content`。若 API 返回 400，优先检查含 Tool Call 的 assistant 消息是否原样保留 `reasoning_content`。

- [ ] **Step 5: 提交，不提交密钥和实时响应正文**

```powershell
git status --short
git add tests/test_live_deepseek.py .env.example .gitignore
git commit -m "test: add opt-in DeepSeek V4 live smoke"
```

### Task 14: 15 个真实 benchmark 任务与指标（Day 12–13）

**Files:**
- Create: `benchmarks/manifest.json`
- Create: `benchmarks/run_benchmark.py`
- Create: `benchmarks/cases/case_01/` through `benchmarks/cases/case_15/`
- Create: `tests/test_benchmark_manifest.py`
- Create: `docs/benchmark-results.md`

**Interfaces:**
- Consumes: `RepairCoordinator` 和 15 个可独立复制的 Python/pytest 小项目。
- Produces: JSONL 原始运行记录和 Markdown 汇总；指标为最终成功率、首轮成功率、平均尝试数、平均耗时、Token、回归数、策略拦截数。

- [ ] **Step 1: 写 manifest 完整性测试**

```python
def test_manifest_has_fifteen_non_leaking_cases():
    manifest = json.loads(Path("benchmarks/manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["cases"]) >= 15
    assert {case["category"] for case in manifest["cases"]} >= {
        "condition", "boundary", "exception", "state", "conversion"
    }
    forbidden = {"answer", "fixed_code", "patch"}
    assert all(not (forbidden & case.keys()) for case in manifest["cases"])
```

- [ ] **Step 2: 建立 15 个单 Bug 用例**

每个 case 固定包含 `src/`、`tests/`、`pyproject.toml`、`case.json`。五类错误各 3 个：条件反转/分支遗漏；零值/上下界；错误异常类型/吞异常；状态未更新/更新顺序；字符串-数字/日期/布尔转换。每个项目初始必须恰好有 1 个失败测试，其余测试通过。

Run: `python -m pytest tests/test_benchmark_manifest.py -v`

Expected: manifest 数量、类别、无答案泄漏和每例单失败检查全部通过。

- [ ] **Step 3: 实现可恢复 benchmark runner**

```python
def summarize(records: list[dict[str, Any]]) -> dict[str, float | int]:
    completed = [record for record in records if record["status"] == "success"]
    return {
        "case_count": len(records),
        "success_rate": len(completed) / len(records),
        "first_attempt_success_rate": sum(r["attempts"] == 1 for r in completed) / len(records),
        "average_attempts": sum(r["attempts"] for r in records) / len(records),
        "average_duration_seconds": sum(r["duration_seconds"] for r in records) / len(records),
        "total_prompt_tokens": sum(r["prompt_tokens"] for r in records),
        "total_completion_tokens": sum(r["completion_tokens"] for r in records),
        "regression_count": sum(r["regression_count"] for r in records),
        "policy_rejection_count": sum(r["policy_rejection_count"] for r in records),
    }
```

runner 每完成一例立即追加 `benchmarks/results/<timestamp>.jsonl`，支持 `--case case_03`、`--model deepseek-v4-flash` 和 `--resume <jsonl>`；提示词只能看到失败输出与仓库内容，不能看到 `case.json` 中的内部分类备注。

- [ ] **Step 4: 运行 Flash 全量评测并写真实结果**

Run: `python benchmarks/run_benchmark.py --model deepseek-v4-flash`

Expected: 15 条 JSONL 记录和一份 `docs/benchmark-results.md`。报告必须保留失败案例和原因，不删除低分任务，不声称未测的 Pro 结果。

- [ ] **Step 5: 提交任务、脚本和结果**

```powershell
git add benchmarks tests/test_benchmark_manifest.py docs/benchmark-results.md
git commit -m "feat: add reproducible PyRepair benchmark suite"
```

### Task 15: GitHub Actions、README 与求职演示（Day 14）

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/pyrepair-demo.yml`
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/demo-script.md`
- Create: `tests/test_readme_commands.py`

**Interfaces:**
- Consumes: 已可安装的 CLI、离线测试、live/benchmark 产物。
- Produces: 公开仓库可复现说明、手动 GitHub Actions Artifact 和 2–3 分钟演示脚本。

- [ ] **Step 1: 写 README 命令一致性测试**

```python
def test_readme_documents_real_commands():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "pip install -e ." in readme
    assert "pyrepair fix" in readme
    assert "python -m pytest" in readme
    assert "安全边界" in readme
    assert "benchmark" in readme.lower()
```

- [ ] **Step 2: 创建完全离线 CI**

```yaml
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install -e ".[dev]"
      - run: python -m ruff check src tests benchmarks
      - run: python -m pytest --cov=pyrepair --cov-report=term-missing -q
```

CI 文件不得读取 `DEEPSEEK_API_KEY`，不得运行 `-m live`。

- [ ] **Step 3: 创建手动演示 workflow**

```yaml
name: PyRepair Demo
on:
  workflow_dispatch:
jobs:
  repair:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install -e ".[dev]"
      - run: pyrepair fix --repo examples/buggy_bank
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: pyrepair-run
          path: examples/buggy_bank/.pyrepair/runs/
```

该 workflow 只读仓库内容并上传 Artifact，不 Commit、不 Push、不评论 PR；外部 fork PR 不会自动获得 Secret。

- [ ] **Step 4: 完成 README、架构和演示脚本**

README 固定顺序：一句话定位；30 秒动图/终端输出；安装；本地使用；工作流图；安全边界；测试层次；benchmark 真实表格；局限；路线图。`docs/demo-script.md` 按时间列出：制造失败、运行 `pyrepair fix`、查看 `fix.patch/report.json/trace.jsonl`、手动应用 Patch、重跑测试。简历表述只写已测数据，例如：

```text
独立开发 PyRepair Agent：基于 DeepSeek V4 Tool Calling 构建 pytest 故障诊断与候选补丁闭环，
通过临时工作区、确定性 Patch 策略、独立 Review 与全量回归验证限制高风险修改；
建立 15 个真实 Bug 任务的可复现评测，最终成功率为报告中的实测值。
```

- [ ] **Step 5: 本地最终验收**

Run: `python -m build`

Run: `python -m ruff check src tests benchmarks`

Run: `python -m pytest --cov=pyrepair --cov-report=term-missing -q`

Run: `python -m pip install --force-reinstall dist/pyrepair_agent-0.1.0-py3-none-any.whl`

Run: `pyrepair fix --help`

Expected: wheel 和 sdist 构建成功；Ruff 0 错误；离线测试 0 failures；安装后的 CLI 能显示帮助。

- [ ] **Step 6: 检查敏感信息和提交历史**

Run: `git grep -n -I -E "sk-[A-Za-z0-9]{12,}|DEEPSEEK_API_KEY=" -- . ":(exclude).env.example"`

Expected: 没有匹配真实密钥。

Run: `git log --oneline --decorate -15`

Expected: 能看到 Task 1–15 的小步提交，而不是单个“大作业”提交。

```powershell
git add .github README.md docs/architecture.md docs/demo-script.md tests/test_readme_commands.py
git commit -m "docs: publish PyRepair usage evaluation and demo"
```

## 2. 每日时间分配

每天 4–6 小时按同一节奏执行：30–60 分钟学习当天所需概念；2–3 小时完成当前 Task 的红-绿测试循环；1 小时重构和补反例；30 分钟写提交说明与当天记录。若当天任务未完成，不跨过失败测试去堆新模块。

| Day | 交付物 | 必须掌握的知识 |
|---|---|---|
| 1 | Task 1 | Hello Agents 7.5.1/7.5.2、包、dataclass、CLI、Git 四命令 |
| 2 | Task 2 | subprocess 参数列表、退出码、超时 |
| 3 | Task 3 | 正则基础、保守解析、原始日志兜底 |
| 4 | Task 4 | pathlib、临时目录、复制与清理 |
| 5 | Task 5 | Tool Schema、注册表、路径越界 |
| 6 | Task 6 | unified diff、纯函数规则、参数化测试 |
| 7 | Task 7 | OpenAI-compatible SDK、Thinking、Tool Call 消息 |
| 8 | Task 8 | Agent Loop、停止条件、FakeLLM |
| 9 | Task 9 | 独立上下文、JSON 校验、只读 Review |
| 10 | Task 10–11 | 全量回归、结构化记录、脱敏 |
| 11 | Task 12 | Coordinator、依赖注入、失败回滚 |
| 12 | Task 13–14 开始 | live marker、真实 API、评测用例 |
| 13 | Task 14 完成 | 指标、失败分析、可复现结果 |
| 14 | Task 15 | GitHub Actions、README、演示和简历证据 |

## 3. 进度落后时的删减顺序

可以删除：Pro 对比、复杂 CLI 参数、彩色终端、多个同时失败测试的联合诊断、自动 PR、并行工具和上下文压缩。

不能删除：临时工作区、路径边界、PatchPolicyGate、目标与全量测试、FakeLLM 离线测试、至少 15 个 benchmark、真实结果和失败说明。

## 4. 计划自检清单

- 设计中的 CLI、临时副本、五工具、DeepSeek Thinking、三轮循环、Policy、Review、Verifier、四产物、离线测试、live smoke、15 个 benchmark 和两条 Actions 流程均有对应 Task。
- 所有生产模块都有至少一个直接测试文件；模型主流程有 FakeLLM，不要求普通测试联网。
- `reasoning_content` 的保存和回传在 Task 7–8 明确实现并测试。
- 成功判定始终由 Python 的规则与 pytest 结果完成，未交给 LLM 自我声明。
- 用户不需要先掌握分支和 PR；开发阶段只使用 status/add/commit/log，自动化也不写回仓库。

## 5. 参考资料

- [DeepSeek Tool Calls 官方文档](https://api-docs.deepseek.com/guides/tool_calls)
- [DeepSeek Thinking Mode 官方文档](https://api-docs.deepseek.com/guides/thinking_mode)
- [DeepSeek Models & Pricing 官方文档](https://api-docs.deepseek.com/quick_start/pricing/)
- [pytest 官方文档](https://docs.pytest.org/)
- [Typer 官方文档](https://typer.tiangolo.com/)
