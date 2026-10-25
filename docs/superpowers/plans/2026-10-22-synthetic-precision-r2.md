# Synthetic precision revision Implementation Plan

> **For agentic workers:** 依用户降低调度开销的偏好，由主线程Inline执行，使用executing-plans与TDD。复用evaluation-v2隔离工作区；默认commit步骤替换为检查点记录，不改变Git状态。Steps use checkbox syntax.

**Goal:** 以新增集合/revision把已有金额精度验收纳入18题修复评测，不改旧资产或模型流程。

**Architecture:** 现有动态manifest和grader无需新增接口；复制校准私有三文件、记录来源，构造新18题清单；先自有RED/GREEN，再实际校准全18题。

**Tech Stack:** Python标准库、现有pytest与benchmarks.evaluation，PowerShell文件复制、apply_patch编辑。

## Global Constraints

- [设计](../specs/2026-10-22-synthetic-precision-r2-design.md)；范围继承已确认收尾标准和精度设计。
- worktree `C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent`；Python `D:/Project/PyRepair Agent/.venv/Scripts/python.exe`。
- 每次测试设置新D: tmp目录、显式worktree src/root PYTHONPATH、PYTEST_ADDOPTS=--rootdir=.、移除进程DEEPSEEK_API_KEY；不读取.env或凭据。
- 仅新增manifest_synthetic_v3.json、eval_private/synthetic_v3/case_15/及一份自有测试；不改评分器/src/旧资产/默认CLI，不调用API、不跑上游、不执行Git发布/清理。
- schema version仍2；18题；只有case_15为revision2，其余metadata与旧清单相同；synthetic/dev。
- 新输出目录不得已存在；来源哈希/复制字节不符停止；旧4,130文件保护摘要不变。

## Task 1：精度验收迁移（complete）

**Files:** Create tests/test_synthetic_precision_dataset.py；benchmarks/manifest_synthetic_v3.json；benchmarks/eval_private/synthetic_v3/case_15/{gold.patch,wrong.patch,provenance.json,hidden_tests/test_acceptance.py}。

**Interfaces:** 复用load_cases(Path)->list[EvaluationCase]、validate_case(case,output)->dict、grade_patch(case,patch_text,output)->dict，无新生产函数。

- [x] 写三个自有测试：新清单保留17题metadata及case_15公开输入；新case_15 baseline/gold/wrong实际校准；旧gold在新隐藏验收被拒。测试先assert新清单存在，避免collection error。

核心断言形状：

```python
assert new_manifest.is_file(), "new precision manifest is not prepared"
result = validate_case(case, tmp_path / "validation")
assert result["status"] == "valid", result
node = "hidden_tests/test_acceptance.py::test_exact_cents_independent_of_decimal_context[long-prec28]"
assert result["baseline"]["outcomes"][node] == "failed"
assert result["reference"]["hidden"]["outcomes"][node] == "passed"
assert result["mutant"]["hidden"]["outcomes"][node] == "failed"
legacy = grade_patch(case, old_gold.read_text("utf-8"), tmp_path / "legacy")
assert legacy["status"] == "hidden_failed", legacy
```

- [x] 执行上述测试文件，观察3项因未准备新集合而失败的RED（0.28秒）。
- [x] 核对新目标不存在；读取旧manifest和hard manifest，复制旧18题；case_15仅替换revision/private_path/origin与F2P/P2P列表。

```python
new = copy.deepcopy(original)
item = next(c for c in new["cases"] if c["id"] == "case_15")
precision = next(c for c in hard["cases"] if c["id"] == "case_15")
item["revision"] = 2
item["private_path"] = "eval_private/synthetic_v3/case_15"
item["fail_to_pass"] = precision["fail_to_pass"]
item["pass_to_pass"] = precision["pass_to_pass"]
item["origin"] = {
    **item["origin"],
    "acceptance_revision": "synthetic-precision-r2",
    "note": "Existing exact-cents contract; calibrated precision acceptance migrated from review-hard-v1."
}
```

- [x] 用apply_patch保存新清单和provenance；三个私有源文件通过Copy-Item逐字节复制；核验每份SHA256。provenance同时记录旧gold，仅作legacy reference，不复制为正例。
- [x] 新测试+既有cases/grading/CLI共48项通过（25.77秒）；Ruff检查通过，初次格式检查要求一个字符串换行调整，机械格式化后检查/格式均通过。功能未改评分器或Agent源码。

## Task 2：18题校准与交付（complete）

**Files:** 新benchmarks/results/v2/validate-synthetic-v3-<unique>/；docs/synthetic-precision-offline.md、收尾检查表、工程日志、README和本计划。

- [x] 执行既有CLI，显式指定新集合，输出新目录validate-synthetic-v3-20261022-7026d80d：

```text
python benchmarks/run_evaluation.py validate --manifest benchmarks/manifest_synthetic_v3.json --output benchmarks/results/v2/validate-synthetic-v3-<new-uuid>
```

`<new-uuid>`由执行时uuid4().hex生成，不是可复用字面目录；不使用run/--resume或真实模型。

- [x] CLIexit0、18/18 valid、0system_error。case_15 baseline22节点17失败；gold公开2+隐藏20通过；wrong隐藏6精度失败。旧gold另存grade-synthetic-v3-legacy-gold-20261022-595839aa，hidden_failed/exit1为正常拒绝，不算系统错误或模型成绩。
- [x] 全4,130旧摘要0差异，三个私有文件源/目标哈希一致；最终完整离线回归687passed、2deselected、264.45秒、exit0，XML687tests/0failures/0errors。新增测试Ruff/格式通过。
- [x] 新报告docs/synthetic-precision-offline.md与本地README/检查表/日志已更新，明确显式命令、旧默认/旧54/54保留、人工校准来源与四项剩余工作。不提交/推送/PR，隔离工作区保留；无API或上游执行。

## 计划自查

需求与Task1的三个语义测试、真实18题校准、Task2摘要保护/文档一一对应；无新增Agent接口或Docker改动。当前Inline方式已沿用用户偏好，无需再询问执行方式。新金额验收使用既有18项检查，不扩大契约。实现前尚无新集合或模型结果。
