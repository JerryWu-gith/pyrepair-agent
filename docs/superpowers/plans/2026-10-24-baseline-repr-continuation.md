# Baseline repr fix and bounded continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. User already chose Inline Execution; do not dispatch additional agents or ask for the choice again. Steps use checkbox syntax for tracking.

**Status (2026-10-25):** Completed Inline: 54 retained + 66 live suffix = 120 staged outcomes; Agent59/60, single36/60. New272/1221 reservations, old error and all failures retained. See [final report](../../controlled-comparison-r2-results.md). No integration/publishing or B.

**Goal:** Fix a proven baseline-address comparison error and finish exactly the remaining 66 method slots without spending again on the original 54 normal results.

**Architecture:** Keep the old pack/run read-only. Create a new metadata-rebased pack by copying unchanged public/calibration assets, binding the original source checkpoint and original run digest. A separate continuation controller validates the exact 54-normal-plus-one-zero-call-error prefix, executes only the original suffix, and reports both stages with explicit provenance. The ordinary old pack verifier stays strict and unchanged.

**Tech Stack:** Python 3.13, pytest, existing Docker backend/grade_layered, existing guarded DeepSeek ModelClient, append-only comparison journal.

## Global Constraints

- Same 20 dev tasks, public input agent-public-r2/exact-public-facts-r2, same scoring/config/environment; no production src changes.
- New requests at most 1,221 ModelClient reservations; provider/SDK retries zero; not a currency cap. User approved public task/source/error data to api.deepseek.com, deepseek-flash.
- Preserve original artifacts and 54 results, including all ordinary failures. Original technical error remains an event, not a fabricated successful old result.
- Exactly original slots[54:] (66 methods, 33 of each); no arbitrary subset selector. API/protocol/worker/container technical error stops.
- No repeated 982-test full suite, 20-case calibration, extra paid smoke, B, Git commit/merge/push/PR.
- Existing externally managed evaluation-v2 worktree is reused. Source checkpoint was saved before changes at D:/Project/PyRepair Agent/tmp/repr-1024-a184/source-checkpoint.json: 66 source files, original runtime matched, 6,632 original run artifacts bound by aggregate digest.

---

### Task 1: Narrow baseline comparison

**Files:** Modify benchmarks/evaluation/comparison_evidence.py; extend tests/test_comparison_evidence.py.

**Interface:** FrozenParser.parse(run, preferred_node_id=None) retains its signature and returns its original frozen report.

- [x] Add a test with the same `assert 1 == 3` and `<cart.Cart object at 0x...>` at different addresses; require `parser.parse(actual) is parser.report` and unchanged serialized initial_facts.
- [x] Add rejection examples for changed assertion, ordinary hex, object type, node, and non-default repr. Example core assertion:

```python
with pytest.raises(ValueError, match="baseline"):
    parser.parse(failed_run("assert 2 == 3"))
```

- [x] Run `python -m pytest tests/test_comparison_evidence.py -q -p no:cacheprovider`; observe the new same-object-address test fail, while negative cases retain strict rejection.
- [x] Implement a private canonical comparison that substitutes only address digits inside default `<qualified.Type object at 0xHEX>` repr in summary/traceback; compare all other fields verbatim, then return self.report.
- [x] Rerun the file and replay the actual saved case_10 run from adapter-result/probe without Docker or a model request; confirm raw initial facts unchanged.

### Task 2: Bound immutable assets and prepare a new identity

**Files:** Create benchmarks/evaluation/continuation_assets.py and tests/test_comparison_continuation.py.

**Interfaces:** `source_files(root=ROOT) -> dict`; `tree_hash(root) -> str`; `verify_source_change(checkpoint, root=ROOT) -> dict`; `prepare_continuation(checkpoint_path, cases, output) -> Path`.

- [x] Write failing tests: only comparison_evidence.py may change among existing runtime files; only continuation_assets.py/comparison_continuation.py and run_continuation.py may be added. Agent/grader edits or unlisted files must reject. Example:

```python
with pytest.raises(ValueError, match="source"):
    verify_source_change(checkpoint, altered_root)
```

- [x] Test a complete owned 120-slot pack with exactly 54 normal terminal records and a zero-call worker error at index54; changed original candidates, wrong prefix length, nonzero fault calls, or dirty supervision must reject before output/credentials.
- [x] Watch failures, implement the smallest guards. Validate the checkpoint's old source digest against the original runtime, unchanged Python/packages/platform, old config/plan/authorization, old tree digest, original pack metadata and zero-call error.
- [x] Copy public/calibration assets unchanged into a new directory; write a new pack.json differing only in runtime identity plus a sidecar binding the original checkpoint/old artifacts/new pack/source delta. `verify_pack(new_pack, cases)` must pass unchanged. No calibration rerun and no old pack mutation.
- [x] Run targeted tests and verify old pack/run aggregate digests unchanged.

### Task 3: Execute only suffix and report provenance

**Files:** Create benchmarks/evaluation/comparison_continuation.py and benchmarks/run_continuation.py; extend tests/test_comparison_continuation.py.

**Interfaces:** `inspect_continuation(pack_path,cases,output,call_limit=1221) -> dict`; `execute_continuation(...,authorization,resume=False,offline_executor=None,credential_getter=None) -> dict`.

- [x] Add failing tests for plan suffix length/order (66), invalid auth before credential/output, normal failure continuation, technical stop, recovery without resending, and aggregation that keeps exactly 120 slots and the original technical event separately.
- [x] Implement a separate controller using original public_job/run_worker, CallBudget, run_slots and grade_layered; do not relax existing inspect/execute/verify.
- [x] Bind the new plan to sidecar, current pack/runtime, fixed suffix and independent output; use validate_authorization before any output/quota/credential access.
- [x] Combine `old_records[:54] + suffix_records` only for a new provenance-labeled report. Add role usage from old formal and new stage exactly once; smoke remains separate. Original grade paths stay original.
- [x] CLI defaults to inspect; prepare, execute, resume are explicit. Example operation is `run_continuation.py inspect --pack NEW_PACK --output NEW_OUTPUT`; no credential read in prepare/inspect.
- [x] Run affected tests (evidence, continuation, old pack/live plan/controller, reporting/budget/journal) and lint changed files once; run the owned 66-slot schedule/recovery once, no API/Docker.

### Task 4: Frozen live continuation and final report

**Files:** New checkpoint/output directories only; update docs/controlled-comparison-r2-results.md, docs/evaluation-completion-checklist.md, docs/evaluation-v2-engineering-log.md and README.md.

- [x] Prepare new pack, verify unchanged facts/assets/Agent/grader and original prefix once; self-review new limited diff. Save exact inspected plan, auth hash and new source identity after tests. Human permission is the user's approval of the complete preceding design/question (2026-10-24 “继续吧”).
- [x] Execute exactly 66 suffix slots, cap1,221, process key only after validation. Do not print/read .env or use the chat-pasted old key. Do not perform probe calls or automatic technical retries.
- [x] At end, verify new journal/candidates/grades and original artifacts, then report grouped core/extended results, paired trials, failure categories, role usage and unknown monetary/HTTP cost. Clearly label adapter-fixed staged completion; if another technical stop occurs, preserve it and report unfinished status.
- [x] Update progress/documents accurately, retain all failures and original history; do not begin B or publish.

Self-review: all seven design sections map to tasks1–4; 54+66=120, 33+33=66, 33+33×36=1,221. No public model inputs or scoring changes. No commits because user explicitly withheld Git publishing/integration actions.
