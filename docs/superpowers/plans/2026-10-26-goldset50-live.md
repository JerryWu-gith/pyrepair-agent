# Unified gold set and unattended live evaluation Implementation Plan

> REQUIRED SUB-SKILL: executing-plans. The user approved the fifty-task design and explicitly authorized proceeding through preparation directly to API evaluation while unavailable. Use bounded independent subagents for the new synthetic assets and live-entry adapter; retain parent control of assembly, freezing and execution. No further routine confirmation is required.

**Goal:** Complete twenty synthetic plus thirty open-source tasks, freeze one new fifty-task experiment, and execute its 300 prescribed independent method slots with `deepseek-flash`.

**Architecture:** Reuse the existing comparison pack, Docker public evidence capture, supervised workers, shared call budget, append-only journal and independent grader. The new fifty-task controller has an explicit experiment profile and cannot silently widen the old twenty-task entry. Core Agent code and method prompts/configuration remain fixed. Reuse offline calibration only when full task fingerprint, environment and scope match.

**Tech Stack:** Python standard library, pytest, existing hash-pinned Docker image and DeepSeek adapter; no new production dependency.

## Global Constraints

- Agent baseline: `7c9508e63ff3a133e7599b3a2ca439e935f10295`, no production source/pyproject/prompt/tool/retry tuning.
- Fifty tasks: twenty synthetic dev, two known open-source dev, twenty-eight open-source holdout not used for Agent tuning.
- Model `deepseek-flash`, existing thinking enabled/reasoning high, three trials, single-shot vs full-agent, 300 slots. Maximum 5,550 model calls is a finite safety reservation, not a target or cost estimate.
- Each slot uses fresh worker, client, work copy, messages and state; no hidden grading feedback into generation. Ordinary method failures remain results.
- API/parse/protocol/environment errors stop and preserve evidence. Never silently retry an initiated request, erase a writer lock, rerun failed slots for better outcomes, or resume unknown liveness.
- Credentials come only from an already configured local ignored env/store, never from chat or printed. No keys in files committed, job JSON, container environment, argv, logs or reports.
- Keep all old tasks/assets/results, the old twenty-case authority gates and old environment locks. No GitHub push/PR or resume score changes.
- User authorization: “开始吧 下一步完成了也别停直接开始调用api测试那些的 我要睡觉了操作不了了” (2026-10-26).

## Task 1: Complete synthetic coverage

**Files:** Create `benchmarks/eval_cases/goldset50/config_merge/`, `.../multi_transfer/`, matching private assets/descriptions and `benchmarks/manifest_synthetic_extra2.json`; test `tests/test_goldset50_synthetic.py`.

- [ ] Read the eighteen existing contracts to avoid duplicate tasks. Add config merge (recursive values, input/output alias isolation, falsey replacement) and transactional transfer (validate before mutation, idempotent success, failed request does not consume identifier).
- [ ] Give each task plain public repros, hidden contract boundaries, preserved behavior, reference production patch and an explicitly artificial incomplete patch that passes public but fails hidden.
- [ ] Observe real buggy/reference/incomplete outcomes on owned synthetic data; do not execute any upstream code on the host. Add structural tests and record scope/origin.
- [ ] Parent combines the unchanged eighteen entries plus two new entries into a new twenty-task manifest without altering old manifests/assets.

## Task 2: Controlled fifty-task live profile

**Files:** Create `benchmarks/evaluation/goldset_live.py` and profile/job adapter as needed; extend the reusable comparison-controller internals and worker validator narrowly; test `tests/test_goldset50_live.py`.

- [ ] Write RED tests for fifty-case profile, exact source/split groups, 300 paired slots and bounded 5,550-call reservation; legacy twenty-case limits continue to reject fifty-case plans.
- [ ] Reuse `execute_comparison` internals through explicit verifier/planner/job dependencies; do not duplicate journals, budgets or provider logic.
- [ ] New worker authority must be distinguishable from v1 jobs and capped to this profile; old v1 remains capped at 2,220. No new prompt/model policy.
- [ ] Validate authorization, selection, slot schedule, asset/runtime/environment identity before credential access; reject unknown/stale/conflicting resumes.
- [ ] Fake owned-worker tests verify technical stop vs ordinary failure and no key reads on inspection. Never call live APIs in unit tests.

## Task 3: Assemble and freeze one experiment

**Files:** Create `benchmarks/evaluation/goldset_pack.py` / `goldset_dataset.py` as required, `benchmarks/run_goldset50.py`; narrow optional offline-calibration reuse in `comparison_pack.py`; tests for assembly and reuse.

- [ ] Build a new unified manifest root with safe rebased asset paths; reject duplicate IDs, overlapping private/public trees and wrong source/split counts. Bind its thirty source entries to the already verified catalog and calibrated a03 assets.
- [ ] Calibrate twenty synthetic tasks in the verified Docker environment; audit unchanged thirty-task evidence by fingerprint/environment. Missing or changed calibration requires new validation, never a fabricated `valid` marker.
- [ ] Prepare frozen public snapshots/evidence through the existing capture adapter; preserve matching validated calibration JSON/artifacts rather than executing it all again. Verify all public facts and declared edit scope match both methods.
- [ ] Runtime/source hash includes the new controller/CLI, method configuration, task fingerprints, environment/check, public spec/evidence and calibration hashes. Freeze exactly 300 slots and do not change code after start.
- [ ] Read-only review and focused regression; check production source unchanged; save local commit only.

## Task 4: Execute without another user action

- [ ] Check credential availability without printing its value. After successful frozen-pack inspect, create one execution authorization bound to the exact plan and the user's above authorization.
- [ ] Launch the new formal controller with finite 5,550-call reservation, key passed only through the existing protected worker channel, no extra API smoke requests.
- [ ] Continue all ordinary failures through the prescribed 300 slots; stop on technical errors and retain original request/budget/journal/cleanup evidence.
- [ ] Monitor with bounded waits, keep a concise progress/problem record, and preserve independent grading. If execution must outlive the turn, use the product's supported monitoring mechanism rather than promising invisible future work.
- [ ] Report actual completion or exact stopped slot. Publish no speculative success rate; summarize all/real/synthetic/dev/holdout groups plus per-task 0/3–3/3, usage and timing after results exist.
