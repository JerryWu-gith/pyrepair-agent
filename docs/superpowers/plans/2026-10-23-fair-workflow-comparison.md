# Fair Workflow Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for Inline execution. Steps use checkbox (`- [ ]`) syntax. User selected lower-overhead Inline; no per-task delegation or automatic commits.

**Goal:** Implement single-response patch generation, frozen public evidence and an auditable offline paired-comparison protocol without enabling paid runs.

**Architecture:** Evaluation-only modules capture public baseline evidence and freeze task/runtime/environment identities. A guarded model wrapper, independent candidate methods and an append-only scheduler separate response durability, patch acceptance and grading. CLI exposes only prepare/verify/simulate; existing production and experiment-v2 behavior stay unchanged.

**Tech Stack:** Python dataclasses/Protocol, existing pytest/ModelClient/coordinator/patching/grader, verified Docker image and standard-library JSON/file locks. No new dependencies.

**Checkpoint (2026-10-23):** Offline phase complete under approved layered comparison protocol2:20/20 core calibration, final pack verify and120 scripted CLI slots/resume complete. Actual Docker dual-method layered integration passed1test/66.25s; final full offline regression869passed/7deselected/358.98s. Old844-test checkpoint and all failed preparations retained. Details in `2026-10-23-layered-acceptance.md`; no paid API, production-source or Git publication changes. Real-model experiments remain a separate unapproved phase.

## Global Constraints

- Approved spec: `docs/superpowers/specs/2026-10-23-fair-workflow-comparison-design.md`.
- Reuse evaluation-v2 detached managed worktree; no main/source modification, new worktree, commit/merge/push/PR, credential reads or real model requests.
- Original comparison protocol1, superseded for new packages by the approved layered comparison protocol2; this remains separate from the legacy experiment protocol2 and historical results. No automatic migration.
- Both groups receive the same frozen initial public facts; tool/output instructions differ explicitly. No hidden/gold/wrong/private metadata reaches worker inputs.
- Same existing independent policy/grader, always concrete verified Docker in user-facing new preparation; host fixture tests only use self-authored code.
- Single-shot accepts raw ordinary unified diff or exactly one diff/patch fence with whitespace outside; no explanations, tools, second response or repair retry.
- All roles share durable call reservations; evaluation clients have max_retries=0. Unknown usage remains unknown, no claimed RMB price/HTTP retry measurements.
- Frozen scope20cases×3trials×2methods=120slots is a planned offline protocol, not API authorization or measured performance.
- Interrupted response/candidate/grade recovery cannot automatically invoke another model call; infrastructure/API errors pause, ordinary patch failure remains a recorded method outcome.
- Keep old files/results; one final offline full suite plus focused RED/GREEN and explicit real Docker verification separately. Record issues/solutions in engineering log.

## File map

- Create `benchmarks/evaluation/comparison_evidence.py`: public evidence serialization/validation, capture and frozen parser/context wrappers; no private case access after staging.
- Create `comparison_budget.py`: exclusive durable shared quota ledger, guarded no-retry clients and response/candidate persistence hooks.
- Create `comparison_methods.py`: strict single-shot response handling and existing full-agent assembly with frozen evidence/guarded clients.
- Create `comparison_pack.py`: case/runtime/environment/public-evidence identities, exclusive preparation and verify-before-model checks.
- Create `comparison_journal.py`: per-slot append-only durable state and safe local-only resume.
- Create `comparison_reporting.py`: planned-denominator grouped metrics and explicit simulated/unrun/technical-error statuses.
- Create `benchmarks/run_comparison.py`: offline-only prepare/verify/simulate entry; no live/run or credential configuration path.
- Create focused corresponding `tests/test_comparison_*.py` and explicit `tests/test_comparison_docker.py`; modify docs only outside these new files unless a verified integration defect requires a bounded existing-evaluation fix.

## Task 1: Public evidence and frozen consumers

**Interfaces:** `capture_evidence(repo, spec, runner) -> dict`; `read_evidence(value, spec) -> (FailureReport, ContextBundle)`; `FrozenParser(evidence,spec).parse(run,preferred_node_id=None)`; `FrozenContext(evidence,spec).build(root,report)`.

- [x] Record current worktree identity and all production-source hashes. Run existing experiment/input/worker tests as relevant baseline, using explicit checkout PYTHONPATH and a fresh D: temp root.
- [x] Write failing behavior tests: owned failure/context round-trip, hidden/unknown fields rejected, source text/amount numbers preserved, changed baseline failure rejected before a model can run. Example:

```python
evidence = capture_evidence(repo, spec, owned_runner)
report, context = read_evidence(evidence, spec)
assert report.node_id == 'tests/test_app.py::test_add'
assert 'assert -1 == 5' in report.summary
assert context.task_contract == 'Return the sum of two integers, including zero.\n'
```

- [x] Observe expected missing-module RED, implement strict public schema using existing dataclasses, bounded strings and safe public paths. Exclude only actual timing/path noise, not source literal values. Frozen consumers compare new baseline facts and return the exact frozen model-visible report/context.
- [x] Run `python -m pytest tests/test_comparison_evidence.py tests/test_agent_input.py -q -p no:cacheprovider`; record RED/GREEN. No commit.

## Task 2: Shared no-retry call budget and durable responses

**Interfaces:** `CallBudget(root,limit).reserve(slot,role,slot_limit) -> int`; `GuardedClient(client,budget,slot,role,slot_limit,response_dir).complete(messages,tools) -> ModelTurn`; `read_usage(root) -> dict`.

- [x] Add RED tests for quota exhaustion before external call, simultaneous reservations never exceeding limit, interruption retaining charge, zero/missing token usage unknown and response surviving an immediately following consumer crash. A third reservation with global limit2 must raise without changing two already-recorded reservations.
- [x] Implement exclusive per-operation lock, append+flush+fsync reservations and usage events. Validate journal state on reopen; stale lock fails closed, no automatic deletion. GuardedClient sets known evaluation client max_retries=0; rejects unsupported hidden retry policy for actual provider wrappers. Persist bounded ModelTurn response before returning it; never store key or arbitrary exception messages.
- [x] Run `python -m pytest tests/test_comparison_budget.py tests/test_agent_usage_ledger.py -q -p no:cacheprovider`; record findings, no commit.

## Task 3: Candidate methods with common initial facts

**Interfaces:** `single_shot(evidence,spec,client,output) -> dict`; `full_agent(repo,spec,evidence,runner,client,budget,output,slot) -> dict`; `extract_patch(turn) -> str`.

- [x] Add RED tests with literal correct/wrong/malformed diffs, additional response text, multiple fences, tool calls and empty/truncated replies. Assert one response only, response persisted before patch parsing, initial fact payload equal to full-agent initial failure/context, no extra source files in baseline prompt.
- [x] Implement separate frozen baseline instructions, exactly one ModelClient response and strict diff parser via existing patch_paths; applying/allowlisting remains in common grader. Example accepted fixture:

```diff
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
```

- [x] Assemble full workflow through build_evaluation_coordinator then replace only evaluation parser/context/factories with frozen/guarded wrappers. Use existing coordinator/tool/Policy/Review/Verifier, no production edits. Respond/candidate durability must retain charges if a tool fails.
- [x] Run method tests plus existing worker/experiment/closed-live-gate tests. Ensure simulated/owned clients never become a new user-facing paid route.

## Task 4: Immutable prepared comparison package

**Interfaces:** `prepare_pack(cases,output,environment_lock,model,trials=3) -> Path`; `verify_pack(path,cases) -> dict`; `paired_slots(case_ids,trials) -> list[dict]`.

- [x] Add RED tests for case/source/config/private/public/evidence/environment tampering, rejected links/path overlap, duplicate IDs, deterministic alternating order, failed preflight preserving output but no usable finalized pack. Model construction must be forbidden during preparation/verification.
- [x] Store controller-only case fingerprints and environment/runtime/source/config identity separately from `public/<case>/` snapshot/spec/evidence. Use exclusive files, final identity digest, and explicit completed marker; no partial pack can verify. Reuse runtime_identity and concrete DockerTestRunner safety verification. Every case public baseline uses DockerAgentTestRunner; never infer baseline from gold or hidden nodes.
- [x] Frozen worker consumers recheck public input digest and current diagnostic evidence before model use. `verify_pack` recomputes public hashes, case fingerprints, prompts/runtime and environment identity; any drift creates a new pack, not an in-place update.
- [x] Run pack tests and existing case/environment tests. Record concrete runtime/config limits and provider defaults rather than inventing reproducibility guarantees.

## Task 5: Paired journal, resume and reporting

**Interfaces:** `run_slots(pack,output,executor,grader,simulation=False) -> list[dict]`; `summarize_comparison(slots,records,simulation=False) -> dict`; `render_comparison(summary) -> str`.

- [x] Add RED tests for120unique planned slots, alternating methods, terminal ordinary failures continuing, infrastructure error pausing, response/candidate/grade interruption recovery and no executor call on resumed started slot. Include corrupted/duplicated/out-of-order journal records and concurrent writer refusal.
- [x] Implement append-only stages, durable response/candidate artifacts, immutable slot identity and local-only continuation. Started-without-response/unknown response leaves interrupted technical error; do not respend. Completed candidate may be regraded locally if a grader was interrupted; no hidden feedback enters the executor.
- [x] Report all planned slots per method/source group: accepted, ordinary failure, technical error, unrun, internal-agent-success rejected, known/unknown usage and duration. Acceptance depends on independent grade, not Agent status. Simulation always suppresses real success-rate claims and labels rows simulated.
- [x] Run journal/report tests plus legacy experiment/reporting tests; no old journal semantics changed.

## Task 6: Offline CLI and actual controlled integration

**Files:** new run_comparison.py and test_comparison_cli.py/test_comparison_docker.py.

- [x] Add RED CLI behavior tests for only prepare/verify/simulate, fail-fast invalid environment/assets, no imports of credential setup/client constructor, output exclusivity, and120-slot simulation marked NOT performance.
- [x] Implement offline commands, explicit two manifests and environment lock, no implicit build/pull/model/API route. Simulation consumes verified package and fixed self-authored scripted executor/grader; it cannot read gold/wrong or claim model performance.
- [x] Add/select explicit Docker test for a self-authored case: prepare/capture frozen public evidence, FakeLLM single-shot and actual full workflow, independent visible/hidden grade for both, preserved original and no host test fallback.
- [x] After trusted code stability, verify existing image lock or build/check a fresh environment only if trusted container files changed. Prepare all20public baselines in a fresh short directory and run120-slot offline simulation; preserve failures and do not remove incompatible tasks.

## Task 7: Consolidated verification, review and documentation

- [x] Run Ruff check/format only new/modified evaluation/test files; resolve issues before a single final complete `tests -m 'not live and not docker'` run saving new XML. Explicit Docker tests remain separate.
- [x] Verify all production hashes unchanged against the Task1 snapshot; legacy protected assets retain previously approved baseline. No old results overwritten.
- [x] One narrowly scoped independent review if authorized by existing user preference; no repeated full suites or broad inherited history. Fix concrete findings with RED/GREEN and recheck affected boundaries.
- [x] Update approved spec/plan/checklist/log and new offline report/README with real evidence, simulation distinction and remaining budget/real-experiment steps. Preserve worktree, no Git mutations/publication.

## Inline plan self-review

Spec1–3 map to Tasks1/3/5; frozen/privacy/source/environment requirements to Tasks1/4/6; no-retry/quota/durability and unknown usage to Tasks2/5; independent acceptance/reporting to Tasks3/5/6; all six offline acceptance requirements map to Tasks1–7. New methods depend on existing ModelTurn/FailureReport/ContextBundle rather than new production schema. User's Inline/no-commit choices already resolved the usual handoff options; proceed after this plan is saved.
