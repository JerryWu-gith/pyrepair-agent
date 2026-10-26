# Goldset50 immutable-source recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Recover the original candidate and execute only170 never-started slots, preserving the stopped run.

**Architecture:** An explicitly hashed outer script in scripts/ reuses existing live_comparison hooks and its safe saved-candidate replay. No frozen runtime module is edited. A second helper renders provenance-rich combined reports from129 normal old records plus171 stage records.

**Tech Stack:** Existing Python standard library, pytest, immutable Docker environment, existing supervisor/journal/grader.

## Global Constraints

- User approved recommended recovery in this thread; no new method/Agent/model/test contract or provider retry.
- Exact old pack g50p-1026-a01, output g50live-1026-a01, authorization g50-auth-1026-a01.json, diagnostic g50-regrade-1026-a01 in D:/Project/PyRepair Agent/tmp.
- Old130terminal records include129normal plus environment_error at os_boltons_addlist_458--2--full-agent;492oldrequests allanswered; no mutations or retries in oldroot.
- Newstage171assessment slots, first is savedcandidate and saved independent regrade withzeroLLM;170new generations85/method, newcallcap3145; old+newcap<=5550.
- Frozen runtime files (src/, benchmarks/evaluation/, existing entry CLIs, pyproject) and dataset/environment remain byte-identical. Own scripts SHA enters stage plan and is checked before key access/each worker.
- No API/Docker/credential access from unit tests or implementation subagent. No push/PR, secret output, unknown-worker recovery, automatic technical retry.

### Task 1: Recovery adapter and staged reporting

**Files:** Create scripts/goldset50_recovery.py, scripts/goldset50_recovery_report.py, tests/test_goldset50_recovery.py. Do not edit any other source/test file; parent owns docs.

**Interfaces:** Expose `inspect_recovery(dataset, pack, original_output, original_authorization, regrade, output) -> dict` returning checkpoint+plan, and `execute_recovery(descriptor, authorization, *, credential_getter=None) -> dict`. Helper may add explicit owned-offline dependency parameters for testing at external boundaries but never production bypass flags/CLI. CLI supports inspect (no keys), execute (new stage), report (saved results, no model), accepting descriptor/approval paths. Parent writes descriptor/auth JSON after final inspection.

- [ ] RED test `assert importlib.util.find_spec('scripts.goldset50_recovery') is not None, 'controlled goldset recovery missing'`, then tests for hand-derived171 slots/170new/3145budget and prefix130/129+oneerror.
- [ ] Qualify original authorization via goldset_live.describe_plan and validate_authorization; verify frozen pack via goldset_pack; `_events(original, _selected_pack(pack,oldplan), False)` validates old bindings; `_check_supervision(original)` and no writer locks; `_calls` verifies5550budget and fully responded calls tied to oldslots. Original error candidate statuscandidate, grade environment_error, exact slot. Hash old tree once and critical files for repeated lightweight checks; preserve original artifacts.
- [ ] Qualify saved regrade by validate_layered_grade with frozen_case and original candidate patch. Regrade cannot be technical; enforce same verified environment for actually executed stages. Include raw regrade tree identity.
- [ ] Derive plan from goldset describe_plan, update distinct recovery kind, exact original slots[129:], explicit firstgrade-only/zeroLLM and suffixmaximum3145, original budget/hash/checkpoint and recovery source hashes. Reject all output/protected source aliases/overlap. No credential read during inspect or any rejected approval/source check.
- [ ] Bootstrap only AFTER validate_authorization: write new execution.json matching shared controller identity, CallBudget(new/q,3145), copy original candidate and validated regrade into new/s0000/g, retain authentic timing, seed started/candidate/grade journal bound to selected stage. Record explicit bootstrap provenance and zero newgeneration. Use shared live_comparison.execute_comparison(resume=True, pack_verifier=..., plan_describer=..., job_builder=goldset_jobs.public_job) with normal credential getter. Never call offline_executor for a real stage. Do not alter existing journal to bypass its technical stop.
- [ ] Combined reporting uses summarize_comparison and summarize_goldset, original129normal+stage records, cumulativeusage via existing `_add_usage`, exact300row denominator, explicit STAGED and originaltechnicalerror provenance in JSON and Markdown. Copy real timing files into new combined report's per-slot timing layout with sourcehash mapping; missing timing staysunknown. Report saved results only on report route, never generate/regrade there. Preserve no-overwrite semantics.
- [ ] Tests exercise real file validation, planner, bootstrap and journal replay; mock only slow external Docker/environment/worker boundaries with owned fixtures. Verify zero key/executor on reused first slot, invalid approval/changed source failbeforekey, no duplicate generation on partial startup, technical stop and coherent partial/full combined statistics. Do not repeat300owned slots unnecessarily; use small owned integration boundary plus full literal schedule/prefix tests.
- [ ] Run newfocused tests, Ruff check/format with no cache; oldrelevant tests only once if shared behavior needsclearcheck. Write RED/GREEN commands and outputs to task1report; scoped commit only3ownedfiles.

### Task 2: Parent acceptance and real execution

**Files:** docs/goldset50-execution-log.md, local generated descriptors/authorization/launch records, no source modifications.

- [ ] Read task report, produce diffpackage, independent spec+quality review; fixes through original implementer and scoped rereview.
- [ ] Check original frozen runtime via git diff plus verify_goldset_pack. Inspect actual recovery, write descriptor/auth bound to user's explicit approval and exact171slots/3145newcap. Keep old492calls untouched.
- [ ] Start hidden background one-shot with temporary systemawake request; verify first candidate is reused without API and subsequent freshworker receives real responses.
- [ ] Create read-only15min heartbeat for newstage and combined report, no retries/resume; update log with originalerror/regrade, owncode/plan hashes, actualprocess and APIprogress. Keepworktree/localcommits, noGitHubpush.
