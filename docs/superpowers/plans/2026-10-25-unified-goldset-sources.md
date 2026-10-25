# 统一 Gold Set：开源来源登记 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户已要求开始，按现有低开销偏好在当前独立 worktree 内执行，不再询问执行方式。

**Goal:** 为累计三十道开源缺陷建立固定来源清单和只读校验入口，清楚区分来源已核对与题目已验收。

**Architecture:** 新增独立的来源目录，不修改旧 manifest 或旧白名单。纯数据验证器拒绝重复缺陷、不匹配父提交及越界路径；只读 CLI 输出数量、仓库分布及尚不能模型评测的状态。源码准备、容器环境和任务覆盖层使用后续独立实施单元，不在本单元伪造已完成状态。

**Tech Stack:** Python >=3.11、标准库 json/pathlib/datetime、pytest、现有 `safe_relative`；无新依赖。

## Global Constraints

- 依据 [已批准设计](../specs/2026-10-25-unified-goldset50-design.md)；先三十道开源，再二十道自建，全部五十题冻结后才运行 DeepSeek。
- 最终三十道开源题包含已有二题；本清单保留两个 dev 和二十八个未用于调优的 holdout 候选，不称三十道全部未见。
- `src/pyrepair/`、`pyproject.toml`、旧任务资产和旧成绩不修改。
- 来源固定为已合并生产修复及其第一父提交；不用 PR 可移动 base SHA。
- 不执行、导入上游源码，不启动 Docker、不读密钥、不创建模型客户端、不请求 DeepSeek。
- 仅来源清单合格不等于 gold set 建成；所有条目仍需固定源码、许可、公开/隐藏测试和离线校准。
- 不提交到远程、不创建 PR、不提前更新 README/简历中的成果数字。

## 本实施单元与完整设计的对应

本计划只完成完整设计第一阶段中的“来源登记及只读检查”交付。后续按同一已批准设计依次推进：固定源码与参考补丁准备；src 导入及每任务环境绑定；三十题行为覆盖层和离线校准；二十题自建任务；五十题冻结与统一执行入口。每个单元有自己的定向测试与记录，不预先虚构尚未核对的二十三题行为和依赖。

## 文件边界

- 新建 `benchmarks/opensource_catalog30.json`：三十个固定来源、二十八新增与二已有标记，以及被排除候选及理由；不是可执行的 EvaluationCase manifest。
- 新建 `benchmarks/evaluation/source_catalog.py`：纯数据校验、文件读取与只读汇总；不接入现有 live 入口。
- 新建 `benchmarks/inspect_source_catalog.py`：仅检查和打印来源清单，不能启动模型或运行源码。
- 新建 `tests/test_source_catalog.py`：验证器、重复项、边界路径、只读 CLI 与真实目录的定向测试。
- 新建 `docs/opensource-catalog30.md`：人类可读目录、状态、来源及后续任务；同时追加现有工程日志。

## Task 1: 来源清单纯数据契约

**Files:** Create `benchmarks/evaluation/source_catalog.py`; Test `tests/test_source_catalog.py`.

**Interfaces:**

- `validate_catalog(data: object) -> dict`：返回经过校验的独立 JSON 值；失败抛 `CatalogError(ValueError)`。
- `load_catalog(path: Path) -> dict`：只读 UTF-8 JSON，限制 512 KiB，拒绝重复 JSON 键。
- `summarize_catalog(data: dict) -> dict`：返回来源数量、仓库分布、dev/holdout 数量；`ready_for_model_evaluation` 固定为 false，不能从来源信息推断资产或成绩。

顶层字段固定为 `version`, `kind`, `stage`, `agent_baseline_commit`, `expected_count`, `minimum_repositories`, `entries`, `exclusions`。version 为 1，kind 为 `pyrepair-opensource-source-catalog`，stage 为 `provenance_checked`。

每个 entry 固定字段为 `id`, `revision`, `source_kind`, `split`, `repository`, `pull_request`, `title`, `buggy_commit`, `fixed_commit`, `fixed_parents`, `merged_at`, `source_root`, `reference_source_paths`, `upstream_test_paths`, `upstream_ai_assistance`, `legacy_manifest`。不提供可执行命令，不将 reference_source_paths 当作公开编辑白名单。

- [x] **Step 1: 写行为测试并观察 RED。** 使用以下独立样例；测试从函数内部 import 尚不存在的模块，以断言式导入检测显示缺少实现，不靠测试文件收集错误完成 RED。

```python
def source_fixture():
    return {
        "version": 1, "kind": "pyrepair-opensource-source-catalog",
        "stage": "provenance_checked", "agent_baseline_commit": "c" * 40,
        "expected_count": 1, "minimum_repositories": 1,
        "entries": [{
            "id": "os_sample_7", "revision": 1, "source_kind": "opensource",
            "split": "holdout", "repository": "owner/sample", "pull_request": 7,
            "title": "Fix escaped values", "buggy_commit": "a" * 40,
            "fixed_commit": "b" * 40, "fixed_parents": ["a" * 40],
            "merged_at": "2026-01-01T00:00:00Z", "source_root": "src/sample",
            "reference_source_paths": ["src/sample/parser.py"],
            "upstream_test_paths": ["tests/test_parser.py"],
            "upstream_ai_assistance": "not established from inspected information",
            "legacy_manifest": None,
        }], "exclusions": [],
    }

def test_source_review_does_not_authorize_model_evaluation():
    import importlib.util
    assert importlib.util.find_spec("benchmarks.evaluation.source_catalog") is not None
    from benchmarks.evaluation.source_catalog import summarize_catalog, validate_catalog
    result = summarize_catalog(validate_catalog(source_fixture()))
    assert result["source_count"] == 1
    assert result["ready_for_model_evaluation"] is False
    assert result["split_counts"] == {"dev": 0, "holdout": 1}
```

Run: `python -m pytest tests/test_source_catalog.py -q -p no:cacheprovider`。预期因为缺少 source_catalog 实现而断言失败。

- [x] **Step 2: 补独立反例测试。** 手工修改 fixture 的 ID、repo/PR、fixed_commit、第一父 SHA、源码路径、stage 和未知字段，断言真实验证器拒绝；增加重复键 JSON、过大文件和读取后调用方修改返回值不影响原值的测试。

- [x] **Step 3: 最小实现。** 验证固定字段集合、正整数且不接受 bool、完整小写 40 位 SHA、`owner/repo`、UTC 合并时间和安全相对路径。按大小写无关 ID、repo/PR、repo/fixed_sha 去重。要求 fixed_parents[0] 等于 buggy_commit、修复与缺陷提交不同、参考 Python 文件都在 source_root 内且不是测试路径、目录数量满足声明。使用 `json.loads(json.dumps(data))` 返回独立副本。阶段不接受 assets/calibrated 等伪升级值。

```python
def summarize_catalog(data):
    value = validate_catalog(data)
    repositories = Counter(e["repository"] for e in value["entries"])
    splits = Counter(e["split"] for e in value["entries"])
    return {
        "stage": "provenance_checked", "source_count": len(value["entries"]),
        "repository_count": len(repositories), "repositories": dict(sorted(repositories.items())),
        "split_counts": {"dev": splits["dev"], "holdout": splits["holdout"]},
        "ready_for_model_evaluation": False,
        "calibration_status": "not assessed by source catalog",
    }
```

- [x] **Step 4: 运行同一测试得到 GREEN；只对新增验证逻辑做小范围重构。**
- [x] **Step 5: 定向 lint 后保存验证器和测试。** 与 Task 2/3 组成同一自洽来源登记提交；不修改旧白名单来让新任务提前可执行。

## Task 2: 固定三十题来源数据

**Files:** Create `benchmarks/opensource_catalog30.json`; extend `tests/test_source_catalog.py`.

**Consumes:** `validate_catalog`、`load_catalog`。
**Produces:** 三十个来源条目及两个已有任务的原始 ID/revision 映射；所有新增资产仍未验收。

- [x] **Step 1: 加真实目录测试并观察 RED。**

```python
def test_checked_catalog_has_thirty_sources_without_recounting_revisions():
    from benchmarks.evaluation.source_catalog import load_catalog, summarize_catalog
    summary = summarize_catalog(load_catalog(ROOT / "benchmarks/opensource_catalog30.json"))
    assert summary["source_count"] == 30
    assert summary["repository_count"] >= 5
    assert summary["split_counts"] == {"dev": 2, "holdout": 28}
    assert summary["ready_for_model_evaluation"] is False
```

- [x] **Step 2: 从已核对的 PR 与 commit API 资料生成数据，再用 apply_patch 保存。** 采用两个已有来源、已选二十八个新增来源；旧两题 ID/revision 与 `manifest_opensource_v3.json` 对照。合并提交有多个父时只取第一父作为缺陷基线，完整父列表保留。
- [x] **Step 3: 保存排除记录。** Click #3201 未直接合并，#2991 的 PR 明确说明复现不稳定，二者不纳入；已有调查排除项保持可追溯。AI 披露只依据实际已读 PR/提交信息，未建立结论不称人工独立修复。
- [x] **Step 4: 验证不重复及来源字段，运行目录测试、旧来源登记相关回归；不执行上游源码。**
- [x] **Step 5: 数据与定向测试保存。** 与校验器、只读CLI一起提交，避免中间版本引用尚未入库的组件；没有将资产或模型执行混入本提交。

## Task 3: 只读检查入口和用户目录

**Files:** Create `benchmarks/inspect_source_catalog.py`, `docs/opensource-catalog30.md`; extend `tests/test_source_catalog.py`; append `docs/external-pilot5-engineering-log.md`.

**Consumes:** `load_catalog`、`summarize_catalog`。
**Produces:** `main(argv=None) -> int`，打印 JSON 汇总；成功返回 0，输入错误返回 2；无执行、准备、模型或写文件选项。

- [x] **Step 1: 加 CLI 行为测试并观察 RED。**

```python
def test_inspect_cli_is_read_only(capsys):
    from benchmarks.inspect_source_catalog import main
    assert main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source_count"] == 30
    assert result["ready_for_model_evaluation"] is False
```

另测缺失文件、重复键 JSON、拒绝 `--execute`；以实际目录前后文件清单比对确认只读，不用 grep 源码断言行为。

- [x] **Step 2: 实现 CLI。**

```python
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "benchmarks/opensource_catalog30.json")
    args = parser.parse_args(argv)
    try:
        result = summarize_catalog(load_catalog(args.catalog))
    except (CatalogError, OSError, UnicodeError) as exc:
        print(f"Source catalog rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
```

- [x] **Step 3: 写人类可读目录，逐题包含来源、缺陷概述、固定提交、AI 披露状态，并说明来源登记不意味着许可、隐藏测试或容器验收已完成。** 更新工程日志中的新范围和本次来源筛选问题。
- [x] **Step 4: 完成下面的收尾检查，再只提交本单元文件。**

```powershell
python -m pytest tests/test_source_catalog.py tests/test_opensource_archive.py tests/test_opensource_assets.py tests/test_opensource_execution_policy.py tests/test_evaluation_cases.py -q -p no:cacheprovider
python -m ruff check benchmarks/evaluation/source_catalog.py benchmarks/inspect_source_catalog.py tests/test_source_catalog.py
python benchmarks/inspect_source_catalog.py
git diff 7c9508e63ff3a133e7599b3a2ca439e935f10295 -- src/pyrepair pyproject.toml
```

最后一个命令必须无输出，证明被测生产代码和配置未被来源建设修改。运行检查前移除子进程中的 DEEPSEEK_API_KEY，并显式设置 PYTHONPATH 指向本 worktree；不会读取或删除用户密钥文件。

## 计划自查

本单元覆盖唯一 ID、数量修正、来源固定、开发/验收标签、源码冻结、只读检查及问题记录。没有把后续资产准备、环境接入、行为测试或正式模型运行写成已完成。所有新增 API 在本计划内定义；没有要求放宽旧入口或修改 Agent。来源条目明确不是现有 live 运行器可接受的任务 manifest。
