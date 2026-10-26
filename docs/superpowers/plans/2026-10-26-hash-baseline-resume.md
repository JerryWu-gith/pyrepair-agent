# Hash baseline correction and167-slot continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Design approved; execute through API launch without routine confirmation.

**Goal:** Correct proven dynamic-hash noise, preflight remaining public baselines, execute only167 never-called slots.

**Architecture:** One narrow runtime fix and separately pinned outer continuation/report scripts; reuse typed cases, strict pack verifier, Docker adapter, supervisor, budget, journal and reporting.

**Tech Stack:** Existing Python/pytest/stdlib/Docker, no dependency change.

## Global Constraints

- Existing managed detached worktree C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent, base8e7851a. Preserve dirty owned engineeringlog and main D checkout.
- Only frozen runtime change permitted: benchmarks/evaluation/comparison_evidence.py. No production Agent, task, model, prompt, retry, scoring, CLI, Docker harness or environment changes.
- D:/Project/PyRepair Agent/tmp contains oldpack g50p-1026-a01, oldroots g50live-1026-a01/g50r-1026-a01, oldcombined g50combined-1026-a01, prechange g50-hash-prechange-1026-a01.json. Keep immutable.
- Exact normalprefix133;506oldresponses; latest os_packaging_hash_1232--1--full-agent fault has0calls/no candidate and clean exitedworker. New167slots=84full+83single, cap3107, cumulativeworst3613<=5550.
- No API/Docker/key access by unit tests or implementers. Parent real-data operations only. Format before final tests, no300slot simulations or repeated historical experiments. No push/PR.

### Task 1: Strict dynamic-hash signature

**Files:** benchmarks/evaluation/comparison_evidence.py and tests/test_comparison_evidence.py only.

**Interfaces:** FrozenParser.parse remains unchanged externally and returns original frozenreport; initial_facts/evidence byte-equivalent. Private helper permitted.

- [ ] RED: saved values575258657340867558/5828956449428120566 versus5558181234910447655/6198252884123138357 in complete pytest summary+traceback, with source `assert hash(first) == hash(second)`. FrozenParser must accept only changed dynamic outputs and preserve initialfacts serialization.
- [ ] Recognize only unequal hash-result integers, matching corresponding where/and outputs and stable expressions. Require summary/traceback agreement and a hash-vs-hash source assertion. Preserve all other text/numbers and old address rule. No task-ID bypass or generic numeric stripping.
- [ ] Negatives: ordinarynumbers, mixed hash/literal, nonhashsource, missing/mismatched annotations, changed expression/type/node/exception/source, equal outputs, malformed/oversized ints, unrelated numeric diagnostic must reject.
- [ ] Run only test_comparison_evidence.py plus Ruff/format --no-cache on2files. Format before finaltest. Record RED/GREEN and scopedcommit2files.

### Task 2: Adapter-fixed third stage

**Files:** Create scripts/goldset50_adapter_resume.py, scripts/goldset50_adapter_report.py, tests/test_goldset50_adapter_resume.py only. Do not edit prior recovery scripts/runtime. Parent owns docs/realoperations.

**Interfaces:** `inspect_resume(checkpoint,dataset,original_pack,new_pack,original_output,recovery_descriptor,recovery_authorization,recovery_output,preflight,output)->dict`; `execute_resume(descriptor,authorization,*,credential_getter=None)->dict`; `report_resume(descriptor,output)` in reporthelper. CLI inspect/execute/report pathflags. Normal sharedexecutor, no offline_executor.

- [ ] RED for module/167schedule/3107cap, badsourcedelta/incompletepreflight/changedoldauthority/callsinzero-callfault; use owned fixtures and mocked externalworker/environment boundaries only.
- [ ] Verify prechange80-source map reconstructs originalruntime; current inventory has no added/removed/changed runtime except comparison_evidence.py. CLIs/packages/platform/old recovery scripts unchanged. Newpack identical oldidentity exceptruntime, identicalp/control files, strict currentgoldset_pack.verify passes; never weakenverify_pack.
- [ ] Validate rawoldpack/auth/execution and `_events` for original130 with1envfault, recovery5 withlatestzero-callWorkerError/no candidate/grade and cleanreturn2. No locks/unknownworkers. Oldnormal129+recoveryfirst4 exactly original[:133]. `_calls` quotas5550/3145 fullyanswered506, noneforlatestfault. Pin oldtrees, criticalfiles and ownscripts.
- [ ] Require complete28-case public preflightreceipt bound to newpack/runtime, fingerprints/spec/evidence. Reconstruct savedTestRun and run FrozenParser on those saveddata; reject source/collection/technical/incomplete baseline mismatch. No generation or grading during inspect/report.
- [ ] Derive distinct adapterresumeplan via goldset_live.describe_plan, exactslots[133:],3107cap,previous506, source/preflight/checkpoint identities. Reject pathaliases/overlap with oldroots/dataset/packs/env/scripts/approval before writes/key.
- [ ] Reuse live_comparison.execute_comparison verifier/planner/job hooks, freshoutput/budget, no bootstrap/fakeoldslots. Pin source/oldcritical/newpack/preflight before each worker. No automatic replay if newoutput exists. CLI exit2 for technicalsummary even if report succeeds.
- [ ] Combine verifiedold133normal+newstage records into300denominator, `_add_usage` for3budgets, retain2technicalevents/oldsource/newsource/adapter-change in JSON+Markdown. Reuse summarize_comparison/summarize_goldset and existing pure renderhelpers; copy genuine timing with source mapping, unknown staysunknown. Report only savedresults.
- [ ] Focused TDD invalidapproval/source/preflight beforekey, smallworker integration/technicalstop/no replay, handcomputedpartial/fullmerge/usage/time/exitcode. No300simulation/repeatedlongfixtures; format before finaltests, report RED/GREEN, scopedcommit3files.

### Task 3: Parent integration and live execution

**Files:** engineeringlog and generated localpack/preflight/authorization/launch artifacts only.

- [ ] Read reports, independently review eachdiff spec+quality, fixscopedfindings, finalintegrationreview without duplicate suites.
- [ ] Metadata-only clone oldp/control into newpack, update runtime onlyafterallowed_delta proof, strictverify; no hidden/reference recalibration.
- [ ] Run28publicbaselines once through DockerAgentTestRunner/FrozenParser, retain rawobservedTestRun+receipt. May run after Task1static while Task2 outside-runtime scripts develop; all28pass required.
- [ ] Inspect actual133prefix+zero-callfault, authorize167/3107 under user'sdesign, launchhiddenone-shot, verifynewresponse andunchangedold506.
- [ ] Readonly30minheartbeat; no retries/clearlocks/resume. FinalSTAGED results/problem log andremoveheartbeat onterminal. Preserveworktree/localcommits, noGitHubpush.
