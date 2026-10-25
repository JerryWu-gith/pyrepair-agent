# Review 隐蔽错误挑战集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 固定六题十二候选，完成离线标签校准、真实资产绑定和兼容报告，不调用真实 API。

**Architecture:** 保留生产 Agent 与旧资产。review_assets.py 负责定位、摘要绑定及集合元数据校验；prepare_review 负责真实执行验收，run_review 只传递集合信息，report 按映射推导数量。沿用既定 Inline，最终独立只读审查。

**Tech Stack:** Python >=3.11、现有 pytest、pathlib、hashlib、JSON；无新增依赖。

## Global Constraints

- 范围以 ../specs/2026-10-17-review-hard-candidates-design.md 为准。
- 六题十二候选；source_kind=synthetic、split=dev，不是 holdout。
- src/pyrepair/、旧 cases/eval_cases/eval_descriptions/eval_private、review_cases/ 和旧结果不修改。
- 真实 API 调用为 0；72 次只使用 FakeLLM 验证调度。
- 不提交、不合并、不推送、不 PR、不删除旧工作区或证据。
- Windows 运行须 PYTHONPATH 指向当前 worktree，使用新 D: 临时目录并移除进程内 API Key。

## Task 1：资产绑定（完成，含独立审查修复）

**Files:** 新建 benchmarks/evaluation/review_assets.py、tests/test_review_assets.py；修改 review_fixtures.py。
**Interfaces:**
- `make_asset_binding(cases_manifest: Path, fixtures: Path, case_ids: list[str]) -> dict`
- `validate_asset_binding(binding: dict) -> Path`：验证实际资产，返回选中的 fixtures。
- `review_runtime(*, fixtures: Path | None = None) -> dict`：None 保留旧默认。
- 定位字段为 kind=repository/external、path；绑定 version=1，包含 fixtures、cases_manifest、fixture_hash、manifest_hash、cases 指纹映射。

- [x] 保存 2919 个受保护文件的 SHA-256，运行现有全部 non-live 基线。
- [x] 写失败测试：实际 prepare 两候选后改补丁、说明、源码、hidden、两类 manifest 或删除资产；load_prepared 必须拒绝，并在 run_review 的 client_factory 前停止。
```python
prepared = prepare_review(manifest, fixtures, tmp_path / "prepared")
(fixtures / "positive.patch").write_text("changed", encoding="utf-8")
with pytest.raises(ValueError, match="identity|asset"):
    load_prepared(prepared)
```
- [x] 运行新测试观察旧实现不拒绝，记录 RED。
- [x] 用现有 contained/public_files/case_fingerprint 计算选定集合，不哈希无关旧集合；新准备包写 asset_binding，load 时先验证绑定再计算选中 runtime。缺少绑定的旧包沿用 review_runtime()。
- [x] 再测试有效包、无关 fixture 修改不影响绑定、错误 locator/version/空映射拒绝、资产在准备中变动拒绝 ready。
- [x] 跑资产/既有 fixture/evaluation/CLI 回归。

## Task 2：固定候选和真实标签

**Files:** 新建 benchmarks/manifest_review_hard_v1.json、benchmarks/review_cases_hard_v1/{README.md,manifest.json,private/<case>/gold.patch,wrong.patch,hidden_tests/test_acceptance.py}、tests/test_review_hard_cases.py；修改 pyproject.toml 的 norecursedirs。
**Interfaces:** EvaluationCase v2 与候选 manifest v1 保持不变；candidate ID=hard_v1_<case_id>_positive/negative；每题 revision=2。

- [x] 写真实校准测试，prepare_review 后逐一断言正例 passed、负例 hidden_failed + AssertionError；核对 6 个公共 baseline 不含 hidden_tests，候选输出为 12，未知/空/缺失候选拒绝。
```python
for name, label in data["labels"].items():
    grade = data["grading"][name]
    assert grade["visible"]["passed"]
    assert grade["status"] == ("passed" if label else "hidden_failed")
    if not label:
        assert _assertion_failure(grade["hidden"])
```
- [x] 运行并确认缺少新集合导致 RED。
- [x] 构建补丁及 literal 隐藏断言：页码 0 拒绝；带空白 True；长金额 12345678901234567890123456789.01 -> 1234567890123456789012345678901；逐项折扣反例总额 1/161；超量预订报错且库存仍 3；parser 偏移必须 0。
- [x] 金额正例复制人工校准补丁，负例复制历史精度反例；其余按设计构建。来源保留 SHA-256，库存正例增加普通非整数拒绝，不能以未定义 bool 行为决定标签。
- [x] 新 hidden 保留旧验收含义并增加边界，F2P/P2P 根据实际 buggy 执行结果声明，不推测。正例不是模型新成绩。
- [x] 所有六题 validate_case、十二候选 prepare 全部通过，观察预先定义的负例断言；保留失败现场，任何错标签先修并记录。

## Task 3：集合元数据、扩容调度及旧报告兼容

**Files:** 修改 review_assets.py、review_fixtures.py、review_evaluation.py、review_reporting.py；扩展 tests/test_review_hard_cases.py，新建 tests/test_review_dataset.py；既有 tests/test_review_reporting.py 保持回归覆盖。
**Interfaces:**
- `dataset_metadata(manifest: dict) -> dict | None`：新集合 metadata 原始 id/source_kind/split，通过 rows 推导 candidate_cases。
- `validate_dataset(dataset: dict, candidate_ids: list[str]) -> None`：要求字段/ID/映射完整有效。
- prepared.dataset -> run manifest.dataset，不进入 messages_for_input。

- [x] 先写测试期望 12 候选 × 2 组 × 3 次 = 72 个 FakeLLM 请求；报告必须说明 6 题/12 候选，不能沿用旧三题解释。
```python
assert len(client.requests) == 72
assert len(set(manifest["dataset"]["candidate_cases"].values())) == 6
assert "PRIVATE_LABEL_CANARY" not in json.dumps(client.requests)
assert summary["planned_requests"] == 72
```
- [x] 运行 RED，再加可选 dataset 字段传播、白名单校验和动态边界说明；旧无 metadata 分支文字保持原样。
- [x] 验证每对请求只在公开 task_contract 不同；私有 labels/basis/category/hidden 不进入；71 cap 不初始化客户端，source 修改同样不初始化。
- [x] 旧 36 次真实结果复制到临时目录，用真实 report CLI 重建，比较 summary/report bytes；原始证据 SHA-256 不变。

## Task 4：离线交付与只读审查

**Files:** README.md、docs/review-hard-candidates-offline.md、docs/evaluation-v2-engineering-log.md、设计和本计划。
- [x] 最终代码稳定后，真实 CLI prepare 使用新 manifest 与 fixtures，在新 results/review/prepared-hard-v1-20261018-02 目录创建 ready 包；默认旧集 prepared-legacy-check-20261018-02 验证兼容。01 为修复前产物，保留不覆盖。
- [x] 执行根目录全量 `python -m pytest -q -p no:cacheprovider -m 'not live'`：383 passed, 1 deselected in 238.50s；相关 ruff、git diff --check 通过。范围包括 tests，并检查新业务资产不会误收集；测试失败先复现原因，不削弱断言。
- [x] 按 requesting-code-review 派独立只读审查，检查设计/标签/输入隔离/旧兼容。发现显式忽略资产和执行副本完整性缺口；先真实 RED，再补充绑定/前后检查，10 项针对性 GREEN，最终只读复核通过。
- [x] 比较本轮前后所有受保护文件哈希：2919 个文件内容不变；原 manifest_v2.json 单独核对未改。检查本地文档链接和密钥形式（不读取环境密钥）。
- [x] 记录实际 baseline、RED/GREEN、标签证据、完整回归、遇到的问题及解决办法，见工程日志步骤 26–28；只报离线工程成果，明确新集合模型表现尚未知。
- [x] 按用户既定选择保留工作区，不执行 Git 发布动作；交付可点击报告与后续可选真实对照（另需预算）。

## 自查

四项任务覆盖设计 3–9 节；元数据与资产绑定留在评测层，旧包和旧 report 的兼容分别验证。上述所有运行均离线，实施方式已确定，不再次询问。
