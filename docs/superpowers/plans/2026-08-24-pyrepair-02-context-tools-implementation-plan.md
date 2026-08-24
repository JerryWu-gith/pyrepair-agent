# PyRepair Phase 2 Context and Structured Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用确定性仓库索引和字符预算构建初始 `ContextBundle`，同时把代码工具升级为可分页、可统计、可恢复的稳定 JSON 接口。

**Architecture:** `RepositoryIndex` 只负责 AST 符号与 import 关系，`ContextBuilder` 根据故障信号评分和截取代码；两者均不调用 LLM。每轮 `ToolRegistry` 在 working 副本建立轻量索引，提供 read/search/symbol/reference/module/edit/diff/test 八类受限工具。

**Tech Stack:** Python 3.11+、标准库 `ast`、`pathlib`、dataclass、JSON、pytest、Ruff。

## Global Constraints

- 先完成 Phase 1 的四个提交；本计划消费 `PytestFailure` 和结构化 `FailureReport`。
- 不引入 Tokenizer、向量数据库、Pydantic、MCP 或新运行依赖。
- 字符预算固定为：`MAX_CONTEXT_CHARS=16_000`、`MAX_SNIPPETS=8`、`MAX_SNIPPET_CHARS=2_500`、`MAX_OVERVIEW_CHARS=2_000`。
- 索引复用 `workspace.EXCLUDED_NAMES`，跳过 `.git/.venv/venv/__pycache__/.pytest_cache/.ruff_cache/.mypy_cache/.pyrepair/.worktrees/worktrees`。
- 仓库源码、注释、文档和字符串全部标记为不可信数据，不取得 system prompt 权限。
- `replace_text` 仍只允许 Python 源码、拒绝 tests 路径、要求 old text 唯一匹配。
- 测试命令使用仓库内 `--basetemp`；每个任务独立提交。

---

### Task 1: AST RepositoryIndex

**Files:**
- Create: `src/pyrepair/repository_index.py`
- Create: `tests/test_repository_index.py`

**Interfaces:**
- Produces: `SymbolInfo`、`ImportInfo`、`ModuleInfo`、`RepositoryIndex`。
- Produces: `build_repository_index(root: Path) -> RepositoryIndex`。
- Produces: `RepositoryIndex.symbols_named(name)`、`module_for_path(path)`、`import_neighbors(path)`。

- [ ] **Step 1: 写符号、import、排除和语法错误测试**

```python
def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_index_extracts_functions_methods_and_imports(tmp_path):
    write(tmp_path / "src/service.py", """
from helpers.money import cents
class Cart:
    def total(self, value):
        return cents(value)
def checkout(cart):
    return cart.total(10)
""")
    index = build_repository_index(tmp_path)
    module = index.module_for_path("src/service.py")
    assert [(item.name, item.kind) for item in module.symbols] == [
        ("Cart", "class"), ("Cart.total", "method"), ("checkout", "function")
    ]
    assert module.imports == (ImportInfo("helpers.money", ("cents",)),)


def test_index_skips_excluded_and_keeps_parse_error(tmp_path):
    write(tmp_path / ".venv/ignored.py", "VALUE = 1")
    write(tmp_path / "broken.py", "def broken(:")
    index = build_repository_index(tmp_path)
    assert [item.path for item in index.modules] == ["broken.py"]
    assert index.modules[0].parse_error == "SyntaxError"
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p2-t1 tests/test_repository_index.py -v`

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现不可变索引模型与 AST Visitor**

```python
@dataclass(frozen=True)
class SymbolInfo:
    path: str
    name: str
    kind: Literal["function", "class", "method"]
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ImportInfo:
    module: str
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleInfo:
    path: str
    module: str
    symbols: tuple[SymbolInfo, ...]
    imports: tuple[ImportInfo, ...]
    parse_error: str | None = None


@dataclass(frozen=True)
class RepositoryIndex:
    root: Path
    modules: tuple[ModuleInfo, ...]
```

```python
def build_repository_index(root: Path) -> RepositoryIndex:
    modules: list[ModuleInfo] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            modules.append(_module_info(relative, tree))
        except UnicodeDecodeError:
            continue
        except SyntaxError:
            modules.append(ModuleInfo(
                relative.as_posix(), _module_name(relative), (), (), "SyntaxError"
            ))
    return RepositoryIndex(root.resolve(), tuple(modules))
```

`_module_info()` 用父类栈把方法命名为 `Class.method`；end line 使用 `end_lineno or lineno`；import 与 symbol 按路径、行号、名称稳定排序。`import_neighbors(path)` 将模块名映射回项目文件，只返回一层正向或反向 import 邻居。

- [ ] **Step 4: 完成绿灯、Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p2-t1 tests/test_repository_index.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/repository_index.py tests/test_repository_index.py`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/repository_index.py tests/test_repository_index.py
git commit -m "feat: index Python symbols and imports"
```

---

### Task 2: 确定性 ContextBuilder 与字符预算

**Files:**
- Create: `src/pyrepair/context_builder.py`
- Create: `tests/test_context_builder.py`

**Interfaces:**
- Consumes: `FailureReport`、`RepositoryIndex`。
- Produces: `ContextSnippet`、`ContextBundle`。
- Produces: `ContextBuilder.build(root, report, index=None) -> ContextBundle`。
- Produces: `empty_context_bundle() -> ContextBundle`。

- [ ] **Step 1: 写评分、预算、稳定排序与降级测试**

```python
def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_context_prioritizes_failed_test_traceback_and_import(tmp_path):
    write(tmp_path / "tests/test_cart.py",
          "from src.cart import total\n\ndef test_total(): assert total([]) == 0\n")
    write(tmp_path / "src/cart.py", "def total(items):\n    return sum(items) + 1\n")
    report = FailureReport(
        "tests/test_cart.py::test_total", "AssertionError",
        "src/cart.py:2: in total", "assert 1 == 0",
        ("tests/test_cart.py", "src/cart.py"),
    )
    bundle = ContextBuilder().build(tmp_path, report)
    scores = {item.path: item.score for item in bundle.snippets}
    assert scores["src/cart.py"] >= 100
    assert scores["tests/test_cart.py"] >= 90
    assert bundle.total_chars <= 16_000


def test_context_is_deterministic_and_respects_all_limits(tmp_path):
    for index in range(12):
        write(tmp_path / f"module_{index}.py", "def needle():\n    return 'x' * 3000\n")
    report = FailureReport(None, "ValueError", "needle", "needle", ())
    first = ContextBuilder().build(tmp_path, report)
    second = ContextBuilder().build(tmp_path, report)
    assert first == second
    assert len(first.snippets) <= 8
    assert all(len(item.content) <= 2_500 for item in first.snippets)
    assert first.total_chars <= 16_000
```

增加 AST 构建抛错测试，断言返回最小空 Bundle；增加 `.venv`、`.pyrepair` 排除测试。

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p2-t2 tests/test_context_builder.py -v`

Expected: FAIL，`ContextBuilder` 尚不存在。

- [ ] **Step 3: 实现模型、评分和截取**

```python
MAX_CONTEXT_CHARS = 16_000
MAX_SNIPPETS = 8
MAX_SNIPPET_CHARS = 2_500
MAX_OVERVIEW_CHARS = 2_000


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

```python
SCORES = {
    "traceback_file": 100, "failed_test": 90, "exception_symbol": 70,
    "test_import": 60, "import_neighbor": 40, "summary_identifier": 30,
    "test_module_similarity": 20, "keyword": 10,
}


def _rank_key(candidate):
    return (-candidate.score, candidate.path, candidate.start_line,
            candidate.symbol or "")
```

`build()` 先生成不超过 2000 字符的文件/模块概览，再按失败测试、traceback 源码、符号、一层 import、关键词累加候选；同一路径和重叠行范围合并，只添加不会突破 16000 字符的前 8 段。代码内容使用 `<repository_data path="src/app.py" trusted="false">` 形式的标签；任何异常返回 `empty_context_bundle()`。

- [ ] **Step 4: 完成绿灯、Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p2-t2 tests/test_repository_index.py tests/test_context_builder.py -v`

Expected: PASS。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/context_builder.py tests/test_context_builder.py`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/context_builder.py tests/test_context_builder.py
git commit -m "feat: build deterministic repair context"
```

---

### Task 3: 稳定 JSON ToolResult、分页 read/search 与执行语义

**Files:**
- Modify: `src/pyrepair/tools.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Produces: `ToolErrorInfo(code, message, retryable)`。
- Produces: `ToolResult(ok, data, error, metadata).to_json()`。
- Produces: read/search/diff/test 的固定字段与分页游标。

- [ ] **Step 1: 写 ToolResult 和 read/search 分页失败测试**

```python
def test_tool_error_serializes_with_stable_shape():
    result = ToolResult(False, {}, ToolErrorInfo(
        "file_not_found", "File does not exist.", False
    ))
    assert json.loads(result.to_json()) == {
        "ok": False, "data": {},
        "error": {"code": "file_not_found",
                  "message": "File does not exist.", "retryable": False},
        "metadata": {},
    }


def test_read_file_returns_lines_and_next_cursor(tool_registry):
    result = tool_registry.execute(
        "read_file", {"path": "app.py", "start_line": 1, "end_line": 1}
    )
    assert result.data == {
        "path": "app.py", "start_line": 1, "end_line": 1,
        "total_lines": 2, "content": "1: def add(a, b):",
        "truncated": True, "next_start_line": 2,
    }


def test_search_code_paginates_without_losing_total(tool_registry):
    result = tool_registry.execute(
        "search_code", {"query": "needle", "offset": 10, "limit": 5}
    )
    assert len(result.data["matches"]) == 5
    assert result.data["total_matches"] == 55
    assert result.data["next_offset"] == 15
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p2-t3 tests/test_tools.py -v`

Expected: FAIL，现有结果仍使用 `content/error: str`。

- [ ] **Step 3: 迁移 ToolResult 与错误帮助函数**

```python
JSONScalar = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


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

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def tool_error(code: str, message: str, *, retryable: bool = False) -> ToolResult:
    return ToolResult(False, {}, ToolErrorInfo(code, message, retryable))
```

- [ ] **Step 4: 迁移五个现有工具的固定 data**

```python
# read_file
{"path": path, "start_line": start, "end_line": actual_end,
 "total_lines": total, "content": numbered, "truncated": actual_end < total,
 "next_start_line": actual_end + 1 if actual_end < total else None}

# search_code
{"query": query, "path": scope, "matches": matches,
 "total_matches": len(all_matches), "offset": offset, "limit": limit,
 "next_offset": offset + len(matches) if offset + len(matches) < len(all_matches) else None}

# replace_text
{"path": relative.as_posix(), "replacements": 1}

# show_diff
{"diff": limited_diff, "changed_files": paths, "added_lines": added,
 "deleted_lines": deleted, "truncated": len(raw_diff) > MAX_DIFF_CHARS}

# run_target_test
{"target": node_id, "passed": run.exit_code == 0, "exit_code": run.exit_code,
 "stdout_tail": run.stdout[-4000:], "stderr_tail": run.stderr[-4000:],
 "duration_ms": run.duration_ms, "timed_out": False}
```

pytest 正常启动但失败返回 `ok=True, data["passed"]=False`；timeout 和 launch error 返回结构化 `ok=False`。所有参数错误带公开消息，不包含绝对临时路径或异常堆栈。

- [ ] **Step 5: 完成绿灯、Ruff 与提交**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p2-t3 tests/test_tools.py tests/test_repair_agent.py -v`

Expected: PASS；Agent 测试改为读取 `data/error.code`。

Run: `.\.venv\Scripts\python.exe -m ruff check src/pyrepair/tools.py tests/test_tools.py tests/test_repair_agent.py`

Expected: `All checks passed!`

```powershell
git add src/pyrepair/tools.py tests/test_tools.py tests/test_repair_agent.py
git commit -m "refactor: return structured code tool results"
```

---

### Task 4: 符号工具、Context Prompt 与 Coordinator 接入

**Files:**
- Modify: `src/pyrepair/tools.py`
- Modify: `src/pyrepair/repair_agent.py`
- Modify: `src/pyrepair/coordinator.py`
- Modify: `src/pyrepair/cli.py`
- Modify: `src/pyrepair/recorder.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_repair_agent.py`
- Modify: `tests/test_coordinator.py`

**Interfaces:**
- Produces: `find_symbol(name)`、`find_references(name)`、`inspect_module(path)`。
- Consumes: `ContextBuilder.build(session.baseline, failure_report)`，每个 run 只构建一次。
- Extends: `RepairAgent.run(report, previous_evidence=(), *, context=None)`。

- [ ] **Step 1: 写三个新工具和 prompt 失败测试**

```python
def test_registry_exports_eight_tools(tool_registry):
    names = {item["function"]["name"] for item in tool_registry.schemas()}
    assert names == {
        "read_file", "search_code", "find_symbol", "find_references",
        "inspect_module", "replace_text", "show_diff", "run_target_test",
    }


def test_symbol_and_module_tools_return_locations(tool_registry):
    symbol = tool_registry.execute("find_symbol", {"name": "add"})
    module = tool_registry.execute("inspect_module", {"path": "app.py"})
    assert symbol.data["definitions"][0]["path"] == "app.py"
    assert module.data["symbols"][0]["name"] == "add"


def context_bundle(path: str) -> ContextBundle:
    snippet = ContextSnippet(path, 1, 2, "add", "traceback_file", 100,
                             "def add(a, b):\n    return a - b")
    return ContextBundle("files: app.py", (snippet,), (path,), 60, False)


def test_agent_initial_payload_contains_untrusted_context(registry):
    llm = FakeLLM([model_text_turn("stop")])
    RepairAgent(llm, registry).run(
        failure_report(), context=context_bundle("src/app.py")
    )
    payload = json.loads(llm.requests[0][0][1]["content"])
    assert payload["context"]["snippets"][0]["path"] == "src/app.py"
    assert payload["context"]["snippets"][0]["trusted"] is False
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-p2-t4 tests/test_tools.py tests/test_repair_agent.py tests/test_coordinator.py -v`

Expected: FAIL，新工具和 context 参数尚不存在。

- [ ] **Step 3: 实现 AST 辅助工具并注册**

```python
class FindSymbolTool(BaseTool):
    name = "find_symbol"
    def execute(self, arguments):
        name = require_string(arguments, "name")
        definitions = [asdict(item) for item in self.index.symbols_named(name)]
        return ToolResult(True, {"name": name, "definitions": definitions})


class InspectModuleTool(BaseTool):
    name = "inspect_module"
    def execute(self, arguments):
        module = self.index.module_for_path(require_string(arguments, "path"))
        if module is None:
            return tool_error("module_not_found", "Python module was not indexed.")
        return ToolResult(True, {
            "path": module.path,
            "symbols": [asdict(item) for item in module.symbols],
            "imports": [asdict(item) for item in module.imports],
            "parse_error": module.parse_error,
        })
```

`FindReferencesTool` 返回 `{"name", "references", "total_matches", "truncated"}`；引用由 AST Name/Attribute 加文本行定位，工具描述明确“possible references, not LSP semantic guarantees”。`ToolRegistry` 在 working 副本建立一次 `RepositoryIndex` 并注入三个工具。

- [ ] **Step 4: 构建一次 ContextBundle 并加入初始消息**

```python
context_bundle = self.context_builder.build(session.baseline, failure_report)
recorder.append_event({
    "type": "context_built",
    "total_chars": context_bundle.total_chars,
    "snippet_count": len(context_bundle.snippets),
    "selected_files": sorted({item.path for item in context_bundle.snippets}),
    "truncated": context_bundle.truncated,
})
agent_run = self.agent_factory(registry).run(
    failure_report, tuple(evidence), context=context_bundle
)
```

```python
payload = {
    "failure": _failure_payload(report),
    "context": {
        "repo_overview": context.repo_overview,
        "snippets": [{
            "path": item.path, "start_line": item.start_line,
            "end_line": item.end_line, "symbol": item.symbol,
            "reason": item.reason, "score": item.score,
            "trusted": False, "content": item.content,
        } for item in context.snippets],
        "truncated": context.truncated,
    },
    "previous_evidence": list(previous_evidence),
}
```

`RepairCoordinator.__init__` 增加必需的 `context_builder: ContextBuilder`；CLI 注入 `ContextBuilder()`。测试里的 `DirectWriteAgent.run` 增加仅接收并忽略的 keyword-only `context=None`。

- [ ] **Step 5: 运行 Phase 2 完整验收**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .\tmp\pytest-phase2 --cov=pyrepair --cov-report=term-missing`

Expected: 所有非 live 测试 PASS，覆盖率不低于 91%。

Run: `.\.venv\Scripts\python.exe -m ruff check src tests benchmarks`

Expected: `All checks passed!`

- [ ] **Step 6: 提交 Task 4**

```powershell
git add src/pyrepair/tools.py src/pyrepair/repair_agent.py src/pyrepair/coordinator.py src/pyrepair/cli.py src/pyrepair/recorder.py tests/test_tools.py tests/test_repair_agent.py tests/test_coordinator.py
git commit -m "feat: provide ranked context and semantic code tools"
```
