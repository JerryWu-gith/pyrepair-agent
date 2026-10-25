# Agent Docker Test Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for Inline execution. Steps use checkbox (`- [ ]`) syntax for tracking. User prefers fewer subagents and no automatic Git publication; these preferences override skill defaults.

**Goal:** Make all three Agent test paths use verified Docker execution during open-source evaluation while preserving the default CLI, existing repair strategy and independent grading.

**Architecture:** Introduce a small production TestExecutor interface and one optional assembly injection. Evaluation owns public-input filtering, a versioned diagnostic container protocol and a TestRun adapter. Grader v1 remains strict; Agent v2 adds precise node selection and legitimate pytest diagnostic failures without permitting host fallback.

**Tech Stack:** Existing Python >=3.11 project, dataclasses/Protocol, pytest, Docker Linux/amd64, pinned Python3.13.5 and pytest9.1.1 image, FakeLLM for offline integration.

**Final status (2026-10-22):** Tasks1–8 complete for this engineering phase. Full offline suite774passed/6deselected; separately selected actual Docker5passed; final environment9/9checks; independent upstream grader recalibration2/2valid. See `docs/agent-docker-adapter-offline.md`. No real model calls, live-gate expansion, Git integration or publication. Fair-baseline/frozen-pack/new-budget/performance work remains outside this plan.

## Global Constraints

- Approved spec: `docs/superpowers/specs/2026-10-22-agent-docker-test-adapter-design.md`.
- Reuse detached managed evaluation-v2 worktree, not main. No commit/merge/push/PR or deletion of legacy assets/results.
- No real model requests, no reused72-call authorization. `require_live_cases` continues to reject opensource.
- No upstream import/execution on host. Host entry/probe tests use only self-authored harmless fixtures.
- Docker never implicitly builds/pulls/installs or retries. New harness requires a new prepared and checked environment before upstream execution.
- Default host CLI and repair prompts/strategy/budgets remain unchanged. Production imports must not depend on benchmarks.
- Public full-suite means selected visible files, not all upstream tests or hidden acceptance.
- Preserve grader v1 strict identity/integrity/outcome semantics; Agent v2 errors cannot weaken grader results.
- Changed production allowlist: testing.py, cli.py, coordinator.py, tools.py, verifier.py. All other protected source/assets/history retain original digests; separately record authorized changed files.
- Use apply_patch; collect RED/GREEN evidence, then one final full suite and one bounded consolidated review rather than repeated whole-suite runs.

## File structure and interfaces

- `src/pyrepair/testing.py`: `TestExecutor(Protocol).run(repo: Path, target: str | None = None) -> TestRun`.
- `src/pyrepair/cli.py`: `build_coordinator(config, model_enabled, *, runner: TestExecutor | None = None)`; same concrete default.
- Existing coordinator/tools/verifier: type annotations only, consume TestExecutor.
- `benchmarks/evaluation/agent_input.py`: immutable `PublicTaskSpec`; `prepare_agent_input(case, destination) -> PublicTaskSpec`; `stage_public_snapshot(repo, destination, visible_tests) -> dict` returning inventory/excluded evidence. Descriptor contains no private paths/nodes/answers.
- `benchmarks/evaluation/agent_container_protocol.py`: `validate_agent_request(request)`, `validate_agent_result(result, expected)`; standalone strict v2 validation using common safe-path/inventory primitives.
- `benchmarks/evaluation/agent_pytest_capture.py`: trusted additional plugin collecting bounded failure diagnostics in the existing probe envelope; no production/model imports.
- Existing entry/protocol/runner/environment/Dockerfile: explicit v2 dispatch, precise pytest selections, new trusted modules in whitelist/hash lock; v1 call signature/results stay compatible.
- `benchmarks/evaluation/agent_test_runner.py`: `AgentExecutionError`; `DockerAgentTestRunner(environment_lock, public_spec, output_root).run(repo, target=None) -> TestRun`.
- `benchmarks/evaluation/agent_worker.py`: evaluation assembly helper and explicit descriptor/backend arguments, validate before model setup; preserve existing synthetic run path and live gate.
- `benchmarks/evaluation/agent_usage.py`: immediate response ledger wrappers, preserving known usage on tool crashes without changing repair_agent.py. Counts ModelClient invocations; HTTP retries remain unknown and are not mislabeled as measured requests.
- Focused tests: test_executor_injection.py, test_agent_input.py, test_agent_container_protocol.py, test_agent_container_entry.py, test_agent_test_runner.py, test_agent_worker_docker.py; explicit real tests in test_agent_docker_integration.py.

## Task 1: Shared TestExecutor injection

- [x] Verify existing isolated Git identity and relevant current CLI/testing/coordinator/verifier baseline, without reinstallation.
- [x] Add behavior tests for caller-supplied runner reaching baseline, tool target and Verifier, including a falsey runner. Example critical contract:

```python
coordinator = build_coordinator(AppConfig("", "deepseek-flash"), False, runner=owned_runner)
result = coordinator.run(RepairRequest(repo=repo, dry_run=True))
assert result.status == "dry_run"
assert owned_runner.calls == [(None,)]
registry = coordinator.registry_factory(session, "test_owned.py::test_owned")
assert registry.execute("run_target_test", {}).data["exit_code"] == 1
```

- [x] Observe RED from missing injection; add Protocol and keyword-only injection, update only five authorized production files.
- [x] Run new tests plus existing CLI/testing/coordinator/verifier tests. Check default dry-run behavior with a real self-authored fixture and no key.
- [x] Record modified-file hashes/checkpoint, no Git commit.

## Task 2: Public task descriptor and filtered snapshots

- [x] Write tests that a normal source/TASK/test survives, .omp/skills/SKILL.md and credentials/caches do not, answers never copy, original files remain; invalid descriptors/required-path collisions/links/outside paths are rejected.
- [x] Observe RED while agent_input module is absent. Implement descriptor strict fields: version, case_id, revision, source_kind, visible_tests, timeout_seconds, input_policy, public_input_hash; policy literal agent-public-r1, timeout1..120, SHA256 and safe relative test paths.
- [x] Implement snapshot copying with ordinary-file/link/size checks and immutable filtered inventory. Use the same policy for initial public input and every edited working snapshot. Example rejection:

```python
payload = spec.to_dict() | {"private_path": "hidden_tests"}
with pytest.raises(ValueError):
    PublicTaskSpec.from_dict(payload)
```

- [x] Run focused input tests and legacy evaluation-cases tests. Record filtered input hashes; do not change old task assets/fingerprints.

## Task 3: Agent v2 protocol and trusted diagnostics

- [x] Write hand-constructed v2 request/result tests covering passed/AssertionError/setup/teardown/collection failures, exact node selection, skipped/xfail/missing/duplicate reports, changed integrity, contradictory exits and bounded diagnostics; keep all existing v1 tests.
- [x] Observe RED from unsupported version2; implement separate v2 module, common dispatch only. Request adds mode=agent and target=None or a fixed node. Keep paths as safe files and required=[] or [target].
- [x] Implement trusted diagnostic plugin and entry dispatch using pytest_probe plus agent_pytest_capture. Agent capture attaches failures before the existing probe sessionfinish serialization; aggregate subtests by parent/phase without hiding failures.
- [x] Exercise actual internal entry on self-authored files. Required example:

```python
request.update(version=2, mode="agent", target="test_owned.py::test_selected",
               required=["test_owned.py::test_selected"])
assert run_stage(request, staging, work, output) == 0
checked = read_stage_output(output, request)
assert checked["probe"]["collected"] == ["test_owned.py::test_selected"]
```

- [x] A valid test/collection failure returns normal failed stage evidence; internal/usage/no-tests/skip/contradictory evidence fails closed. Run v1/v2 protocol and owned entry tests together, no upstream host execution. Confirmed targeted import SyntaxError may return4: accept only with target-file collection failure evidence, not a plain missing-node usage error.

## Task 4: Verified supervisor and immutable environment integration

- [x] Add DockerBoundary-based RED tests for `DockerTestRunner.run_agent(repo, paths, output, timeout, target=None)` emitting v2 only, exact selectors, correct stage-result mapping and existing timeout/cleanup safety.
- [x] Extend the verified concrete runner and stage builder with explicit Agent mode; keep __call__ v1 untouched. Example dispatch is `_stage(..., agent_mode=True, target=target)` only after environment evidence verification.
- [x] Add the two new trusted modules to harness hashes, explicit build whitelist and Dockerfile COPY; update whitelist behavior tests with exact expected files. Do not relax existing hash/profile checks.
- [x] Run supervisor/preparation/protocol/entry tests without real Docker. Note that prior environment lock is now historical and must not be used to execute the changed harness.

## Task 5: DockerAgentTestRunner and execution evidence

- [x] Write RED tests against the real adapter with only the external Docker boundary replaced. Cover baseline state, fixed failing target, unknown/option-like node rejection, public full coverage, repeated edited snapshots, result conversion and fatal infrastructure errors.
- [x] Adapter stages a filtered immutable snapshot outside repo and stores stage log/selection/input hash/elapsed metadata under a unique output path. Only concrete verified DockerTestRunner is used, not an is_sandbox flag or arbitrary callback.
- [x] Initial full collection establishes baseline nodes and failed targets; target must be an exact baseline failure. Subsequent full success requires the same node coverage. Collection failure is diagnostic, not fake success or host fallback.
- [x] Convert validated failures to PytestFailure/TestRun, command=(container-pytest,*selection), capture_source=plugin, combined pytest log in stdout; normalize only anchored /work/ source prefixes.
- [x] For timeout/OOM/environment/protocol/integrity/cleanup/internal/usage/no-tests errors raise AgentExecutionError with stage evidence path; never return exit0 or silently invoke host TestRunner. Run adapter plus production completion/feedback tests.

## Task 6: Worker assembly and FakeLLM full repair

- [x] Add RED tests for descriptor/backend mismatch before model construction, safe public identity only, and propagation of execution errors with preserved model usage.
- [x] Add worker descriptor/backend/environment-lock arguments and an assembly helper that injects the adapter into all three paths. Verify initial public input digest before model setup. Existing case-aware run_agent and experiment live gates remain closed for opensource.
- [x] Use FakeLLM to repair a self-authored add bug through actual coordinator/tool/Policy/Review/Verifier components; model responses use replace_text, show_diff, run_target_test then completion. Assert exported patch, unchanged original, stage evidence and no hidden content.
- [x] Use a host TestRunner trap to fail if the injected Docker path ever falls back. Run worker tests and existing experiment/live-gate/partial-usage regression tests.

## Task 7: New real environment and no-model upstream verification

- [x] After trusted files are stable, explicitly prepare a new image/lock and check all existing owned safety/timeout probes. Never overwrite old environment directories.
- [x] Add/select real Docker tests only through explicit marker and environment lock. Exercise owned baseline/target/full, collection failure, two edited snapshots and FakeLLM flow without reading keys; assert separate cleaned containers and actual no-key/no-network properties.
- [x] Run the adapter on two filtered upstream public baselines and reference candidates, only inside verified containers. Reference patches are controller-owned offline calibration material, never delivered as model input or counted as Agent success.
- [x] Revalidate baseline/gold/wrong for manifest_opensource_v2 with the new environment in a new result directory; preserve previous failures/results.
- [x] If preparation/runtime fails, keep evidence and report the blocker; do not change proxy/certificates/security policy or substitute host execution. Initial3/5failure evidence retained; owned RED/GREEN fixes followed by a new prepared environment and complete5/5rerun.

## Task 8: Final verification, review and documentation

- [x] Update spec/checklist/engineering log with actual stages, errors/resolutions, scope and unrun items; README documents verified capabilities only, no new model scores.
- [x] Run related Ruff check/format, then one complete offline suite with live/docker excluded and save JUnit XML in new main tmp directory. Run explicit Docker tests separately, not as implicit full-suite side effects.
- [x] Compare old protected catalog: name the five authorized production files and planned harness changes separately; all unrelated source/assets/history retain old digests. New modules/tests are listed independently.
- [x] One scoped consolidated independent review is allowed under the user's standing delegation instruction; give only approved spec/changed files/evidence, no inherited long history or duplicate full tests. Fix verified findings with focused TDD and reverify affected checks. Both Important findings and the actual-Docker refinements rechecked without remaining concrete findings.
- [x] Leave worktree/main/Git publication state intact. Report adapter engineering completion separately from pending fair-baseline/frozen-pack/new-budget/repeated-performance evaluation. Never mark overall evaluation complete here.

## Plan self-review

Spec sections1–4 map to Tasks1/2/4/6; dataflow to Tasks3/5/6; error/path semantics to Tasks3/5; input/security boundaries to Tasks2/4/7; six acceptance requirements map to Tasks1–8. Typed interfaces above are the source of names for later tasks. No real-model or live-gate expansion is included. No automatic commits are included because user explicitly deferred publication/integration.
