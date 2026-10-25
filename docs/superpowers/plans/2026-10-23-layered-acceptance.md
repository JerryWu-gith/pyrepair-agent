# Layered Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. User chose Inline, no commits or paid execution.

**Goal:** Version more r2's defect-related acceptance separately from its unchanged upstream extended regression, without converting timeouts into success.

**Architecture:** A data-only asset builder creates a new public tree and controller-side extended descriptor. Evaluation-side orchestration reuses existing core grading and verified Docker execution; comparison protocol 2 binds separate results, calibration, and reporting. Production Agent and trusted container code remain unchanged.

**Tech Stack:** Python 3.13, pytest, existing DockerTestRunner, existing manifests, immutable JSON evidence.

## Global Constraints

- Approved spec: ../specs/2026-10-23-layered-acceptance-design.md; user confirmed after the task/test-count explanation.
- No API, .env reads, publishing, Git mutations, source refactors, dependency installs or Docker profile changes.
- Preserve r1/opensource_v2, synthetic_v3, hidden tests, gold/wrong, historical results and initial production hashes.
- 18 synthetic + 2 opensource tasks; three trials per method; 120 scripted slots are not model performance.
- Stage timeout stays 120 seconds. Unsafe/contradictory evidence pauses; safe extended timeout is unknown and does not erase core acceptance.
- Reuse managed evaluation-v2 worktree. Fresh short artifact directories only; no delete/overwrite.

## Task 1: Versioned assets and selected nodes

**Files:** Create evaluation/layered_assets.py, tests/test_layered_assets.py, manifest_opensource_v3.json, eval_cases/opensource_v2/os_more_seekable_1269/ (generated copy + bridge), regression_opensource_v3.json.

**Interfaces:** build_more_revision(destination: Path) -> Path writes a complete manifest without executing upstream code; load_regression(case) -> dict | None reads the explicitly versioned controller descriptor. An explicit builder CLI flag or callable is offline only.

- [x] Write a static integration test that calls the missing builder, loads the produced manifest, stages the public snapshot, checks byte equality of every r1 file, all hidden/gold/wrong unchanged, exact added file, 19 inherited/own P2P nodes, public spec has no hidden descriptor. Missing builder must fail inside test body.
- [x] Run `pytest tests/test_layered_assets.py -q -p no:cacheprovider` and observe valid failures.
- [x] Implement data-only copy/bridge/manifest/descriptor creation with exclusive writes. Bridge imports original two unittest classes; existing paths/ID semantics remain strict.
- [x] Run focused tests and materialize assets once in the new paths. Compare task fingerprints and verify old protection snapshot.

Example acceptance assertion:
```python
new = load_cases(build_more_revision(tmp_path / "assets"))[0]
assert new.revision == 2
assert len(new.pass_to_pass) == 22  # original 3 + upstream 19
assert new.gold_patch.read_bytes() == old.gold_patch.read_bytes()
```

## Task 2: Layered grading and durable recovery

**Files:** Create evaluation/layered_grading.py, tests/test_layered_grading.py; modify comparison_journal.py and its tests.

**Interfaces:** grade_layered(case, patch_text, output, *, test_runner, expected_nodes=None) -> dict; validate_layered(case, output, *, test_runner, core_validator=validate_case) -> dict; validate_layered_grade(value, output=None, *, candidate_patch=None, frozen_case=None) validates the saved v2 aggregate and separate artifact identities. Opensource extension requires the full frozen expected_nodes from calibration. Descriptor absent means extension not_applicable.

- [x] Add RED tests for real patch application with a small owned repo and a stage-result double: core pass + extended timeout retains core but is not fully verified; extended failure differs from core failure; core failure skips extension; environment/cleanup error stays technical; interrupted extension does not execute twice; changed result cannot resume as passed.
- [x] Implement reuse of grade_patch for core and independent prepare_case/apply_patch_checked for public-only extension. Persist core-grade.json before extended work, durable started marker before stage; reuse saved stages without replay, interrupted stage becomes unknown.
- [x] Implement predetermined 3x more core calibration and one baseline/reference extended check; failed calibration prevents pack. Bind every result's digest; no hidden assets in extension.
- [x] Journal v2 grading uses a deterministic per-slot grading folder, consumes saved partial stages after interruption and validates separate artifacts. V1 fixtures remain supported; no started slot re-calls executor.
- [x] Run focused real-component tests plus existing grading/journal tests.

Example result contract:
```python
assert result["core"]["status"] == "passed"
assert result["extended"]["status"] == "timeout"
assert result["fully_verified"] is False
assert result["status"] == "core_passed"
```

## Task 3: Frozen identities, reporting and offline verification

**Files:** Modify comparison_pack.py, comparison_reporting.py, run_comparison.py; tests/test_comparison_pack.py, test_comparison_cli.py, test_comparison_docker.py; new focused reporting tests; docs/README/checklist/log.

**Interfaces:** New prepared packs version 2 with assessment policy and per-case regression/calibration identities; existing method inputs remain PublicTaskSpec v1. CLI stays prepare/verify/simulate only, default opensource_v3. New reporting exposes core_acceptance_rate and extended status counts, not unlabeled success_rate.

- [x] RED tests: regression description/calibration tamper refuses verify, scope differs by method refuses, v2 simulated slots bind layered result with all real proportions None; core+timeout report is unverified, not complete success.
- [x] Implement new identity/hash coverage and calibrated preparation; preserve explicit legacy fixture behavior. Update CLI default only after new assets exist.
- [x] Run targeted suite and lint/format; run actual Docker fixture both methods with independent layered core/extension acceptance (no host execution).
- [x] Execute actual predetermined more r2 calibration and extension baseline/reference in fresh short output; do not retry failure until pass. Then prepare/verify fresh full 20-task pack and simulate all 120 scripted slots plus resume without reexecution.
- [x] Run one final full offline test suite, inspect XML, compare original production and legacy asset hashes; bounded independent review if still required, no per-task agent dispatch.
- [x] Update engineering log for all errors and fixes, README/checklist/spec status and final report with actual evidence. No real performance claims or publication.

**Final evidence:** pack `D:/Project/PyRepair Agent/tmp/lp-1023-74d56f08`, simulation `D:/Project/PyRepair Agent/tmp/ls-1023-fe4ef31f`, XML `D:/Project/PyRepair Agent/tmp/layered-9c8476e9`.20/20 core valid, more3x26nodes and reference766 extended passed;120 scripted slots and unchanged-journal resume.869passed/7deselected/358.98s; explicit Docker1passed/66.25s;10-file static/format passed. Production22files unchanged,174legacy task assets unchanged;4130old protected entries retain only5previously authorized differences. Four scoped findings plus actual4MiB evidence write root cause addressed with RED/GREEN and bounded review. Keep detached worktree as requested, no Git mutations or API.

Example report assertion:
```python
assert summary["groups"][0]["core_acceptance_rate"] == 1.0
assert summary["extended"]["timeout"] == 1
assert summary["extended"]["fully_verified"] == 0
```

## Checkpoints

Plan self-review: covers unchanged hidden data, 19 inherited nodes, no stage replay, safe timeout versus environment failure, reference calibration, version/fingerprints, denominator and simulation boundaries. A newly discovered incompatibility must be documented before changing these decisions.
