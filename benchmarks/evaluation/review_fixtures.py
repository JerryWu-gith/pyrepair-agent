"""Offline, fail-closed preparation of fixed Review inputs and separate labels."""

from __future__ import annotations

import difflib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from pyrepair.context_builder import validate_task_contract
from pyrepair.models import FailureReport, FileChange, PatchSnapshot, TestRun
from pyrepair.pytest_parser import PytestParser, parse_text_failures
from pyrepair.recorder import _atomic_write
from pyrepair.review_agent import REVIEW_SYSTEM_PROMPT, _review_messages

from .cases import (
    case_fingerprint,
    contained,
    load_cases,
    prepare_case,
    safe_relative,
)
from .experiment import ROOT, digest, runtime_identity
from .grading import _tree_hashes, grade_patch, run_tests
from .patching import apply_patch_checked, patch_paths
from .review_assets import (
    dataset_metadata,
    file_hash,
    fixture_hash,
    make_asset_binding,
    validate_asset_binding,
    validate_dataset,
)

PROTOCOL = "review-contract-v1"


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def review_runtime(*, fixtures: Path | None = None) -> dict:
    cli = ROOT / "benchmarks/run_review_evaluation.py"
    fixtures = fixtures if fixtures is not None else ROOT / "benchmarks/review_cases"
    return {
        "runtime": runtime_identity(),
        "cli_hash": file_hash(cli) if cli.exists() else None,
        "prompt_hash": digest(REVIEW_SYSTEM_PROMPT),
        "fixture_hash": fixture_hash(fixtures),
    }


def messages_for_input(value: dict, *, with_contract: bool) -> list[dict]:
    # Explicit whitelist: grading/provenance/labels never cross this boundary.
    report = FailureReport(**value["failure"])
    snapshot = PatchSnapshot(tuple(FileChange(**c) for c in value["changes"]))
    return _review_messages(
        report, snapshot, task_contract=value["task_contract"] if with_contract else ""
    )


def load_prepared(path: Path, *, check_runtime: bool = True) -> dict:
    document = json.loads((path / "prepared.json").read_text(encoding="utf-8"))
    data = document["payload"]
    if document.get("digest") != digest(data) or data.get("protocol") != PROTOCOL:
        raise ValueError("invalid prepared digest/protocol")
    if check_runtime:
        if "asset_binding" in data:
            fixtures = validate_asset_binding(data["asset_binding"])
            current = review_runtime(fixtures=fixtures)
        else:
            current = review_runtime()  # Legacy packages retain their original rule.
        if digest(data["runtime"]) != digest(current):
            raise ValueError("prepared runtime/fixture identity changed; prepare again")
    if not data["inputs"] or set(data["inputs"]) != set(data["labels"]):
        raise ValueError("invalid input/label identity")
    if "dataset" in data:
        validate_dataset(data["dataset"], list(data["inputs"]))
    for key, value in data["inputs"].items():
        safe_relative(key)
        if "/" in key or type(data["labels"][key]) is not bool:
            raise ValueError("invalid candidate identity/label")
        if set(value) != {"failure", "changes", "task_contract"}:
            raise ValueError("unexpected public input fields")
        validate_task_contract(value["task_contract"], required=True)
        messages_for_input(value, with_contract=True)
    return data


def _assertion_failure(result: dict) -> bool:
    outcomes = result["outcomes"]
    return (
        result["status"] == "failed"
        and result["returncode"] == 1
        and bool(outcomes)
        and "failed" in outcomes.values()
        and set(outcomes.values()) <= {"failed", "passed"}
        and set(result["required"]) <= outcomes.keys()
        and set(result.get("assertion_failures", ()))
        == {node for node, outcome in outcomes.items() if outcome == "failed"}
    )


def _review_run_tests(repo, paths, output, timeout, required=()):
    # Bind the actual executable copies as well as the immutable source assets.
    # Generic tree hashes intentionally ignore venv/cache names.
    declared_hashes = {p: file_hash(contained(repo, p)) for p in paths}
    result = run_tests(
        repo,
        paths,
        output,
        timeout,
        required,
        extra_plugins=("benchmarks.evaluation.review_probe",),
    )
    result["assertion_failures"] = []
    try:
        if declared_hashes != {p: file_hash(contained(repo, p)) for p in paths}:
            raise ValueError("declared verification files changed")
    except (OSError, ValueError) as exc:
        result.update(passed=False, status="grader_error", error=f"test integrity failed: {exc}")
        return result
    if result["status"] not in {"passed", "failed"} or result["returncode"] not in {0, 1}:
        return result
    try:
        probe = json.loads(output.with_suffix(".probe.assertions.json").read_text(encoding="utf-8"))
        if (
            probe.get("version") != 1
            or probe.get("finished") is not True
            or probe.get("exit_code") != result["returncode"]
            or not isinstance(probe.get("failures"), list)
        ):
            raise ValueError("invalid assertion evidence")
        seen = set()
        for failure in probe["failures"]:
            if (
                not isinstance(failure, dict)
                or set(failure) != {"nodeid", "phase", "is_assertion", "exception_type"}
                or failure["nodeid"] not in result["outcomes"]
                or failure["phase"] not in {"setup", "call", "teardown"}
                or type(failure["is_assertion"]) is not bool
                or (failure["nodeid"], failure["phase"]) in seen
            ):
                raise ValueError("invalid assertion evidence record")
            seen.add((failure["nodeid"], failure["phase"]))
            if failure["phase"] == "call" and failure["is_assertion"]:
                result["assertion_failures"].append(failure["nodeid"])
        result["exception_evidence"] = probe["failures"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result.update(
            passed=False, status="grader_error", error=f"assertion evidence unavailable: {exc}"
        )
    return result


def _snapshot(case, repo: Path, text: str) -> PatchSnapshot:
    before = {p: contained(repo, p).read_text(encoding="utf-8") for p in patch_paths(text)}
    apply_patch_checked(case, repo, text)
    changes = []
    for path, old in before.items():
        new = contained(repo, path).read_text(encoding="utf-8")
        lines = list(
            difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), fromfile="a/" + path, tofile="b/" + path
            )
        )
        if old != new:
            changes.append(
                FileChange(
                    path,
                    old,
                    new,
                    "".join(lines),
                    sum(x.startswith("+") and not x.startswith("+++") for x in lines),
                    sum(x.startswith("-") and not x.startswith("---") for x in lines),
                )
            )
    return PatchSnapshot(tuple(changes))


def _precision(case, patch_text: str, test: Path, output: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="pyrepair-review-precision-") as temp:
        repo = prepare_case(case, Path(temp) / "repo")
        apply_patch_checked(case, repo, patch_text)
        target = repo / "precision_tests/test_money_precision.py"
        target.parent.mkdir()
        target.write_bytes(test.read_bytes())
        hashes = _tree_hashes(repo)
        result = _review_run_tests(
            repo, ("precision_tests/test_money_precision.py",), output, case.timeout_seconds
        )
        if hashes != _tree_hashes(repo):
            raise ValueError("candidate changed precision verification files")
        return result


def prepare_review(cases_manifest: Path, fixtures: Path, output: Path) -> Path:
    cases = {c.id: c for c in load_cases(cases_manifest)}
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    rows = manifest["candidates"]
    if manifest.get("version") != 1 or not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("invalid fixture manifest")
    for row in rows:
        safe_relative(row["id"])
        if (
            "/" in row["id"]
            or row["case_id"] not in cases
            or type(row["expected_approved"]) is not bool
        ):
            raise ValueError("invalid fixture candidate/label")
        contained(fixtures, row["patch"])
    dataset = dataset_metadata(manifest)
    if dataset is not None and any(
        cases[r["case_id"]].source_kind != dataset["source_kind"]
        or cases[r["case_id"]].split != dataset["split"] for r in rows
    ):
        raise ValueError("dataset scope differs from selected tasks")
    binding = make_asset_binding(cases_manifest, fixtures, sorted({r["case_id"] for r in rows}))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data = {
        "protocol": PROTOCOL,
        "runtime": review_runtime(fixtures=fixtures),
        "asset_binding": binding,
        "inputs": {},
        "labels": {},
        "provenance": {},
        "grading": {},
        "baselines": {},
        "cases": {},
        "fixture_manifest": manifest,
        "fixture_manifest_hash": file_hash(fixtures / "manifest.json"),
    }
    reports = {}
    if dataset is not None:
        data["dataset"] = dataset
    for row in rows:
        candidate, case = row["id"], cases[row["case_id"]]
        contract = validate_task_contract(
            case.description.read_text(encoding="utf-8"), required=True
        )
        if case.id not in reports:
            with tempfile.TemporaryDirectory(prefix="pyrepair-review-public-") as temp:
                repo = prepare_case(case, Path(temp) / "repo")
                log = output / "baselines" / (case.id + ".log")
                hashes = _tree_hashes(repo)
                required = tuple(
                    n
                    for n in (*case.fail_to_pass, *case.pass_to_pass)
                    if n.partition("::")[0] in case.visible_tests
                )
                baseline = _review_run_tests(
                    repo, case.visible_tests, log, case.timeout_seconds, required
                )
                if not _assertion_failure(baseline) or hashes != _tree_hashes(repo):
                    raise ValueError("public baseline not a reproducible assertion failure")
                text = log.read_text(encoding="utf-8")
                # Eliminate ephemeral host paths from the frozen public traceback.
                text = text.replace(str(repo), "<public-repo>").replace(
                    repo.as_posix(), "<public-repo>"
                )
                run = TestRun(
                    (), 1, text, "", 0, failures=parse_text_failures(text), capture_source="text"
                )
                report = PytestParser().parse(run)
                if not report.parseable:
                    raise ValueError("public failure could not be parsed")
                reports[case.id] = report
                data["baselines"][case.id] = baseline
                data["cases"][case.id] = case_fingerprint(case)
        patch_file = contained(fixtures, row["patch"])
        patch_text = patch_file.read_text(encoding="utf-8")
        grade = grade_patch(
            case, patch_text, output / "grading" / candidate, test_runner=_review_run_tests
        )
        want = "passed" if row["expected_approved"] else "hidden_failed"
        if grade["status"] != want or (
            not row["expected_approved"] and not _assertion_failure(grade["hidden"])
        ):
            raise ValueError(
                f"candidate label failed validation: {candidate}; inspect grading logs"
            )
        if "precision_test" in row:
            precision = _precision(
                case,
                patch_text,
                contained(fixtures, row["precision_test"]),
                output / "precision" / (candidate + ".log"),
            )
            grade["precision"] = precision
            if row["expected_approved"] and not precision["passed"]:
                raise ValueError(f"candidate label failed precision validation: {candidate}")
        with tempfile.TemporaryDirectory(prefix="pyrepair-review-snapshot-") as temp:
            repo = prepare_case(case, Path(temp) / "repo")
            snapshot = _snapshot(case, repo, patch_text)
        data["inputs"][candidate] = {
            "failure": asdict(reports[case.id]),
            "changes": [asdict(c) for c in snapshot.changes],
            "task_contract": contract,
        }
        data["labels"][candidate] = row["expected_approved"]
        data["provenance"][candidate] = {
            "source": row["source"],
            "basis": row["basis"],
            "patch_hash": file_hash(patch_file),
            "contract_hash": digest(contract),
        }
        data["grading"][candidate] = grade
    historical = fixtures / "diagnostics/case_15_historical.patch"
    if "case_15" in reports and historical.exists():
        diagnostic = _precision(
            cases["case_15"],
            historical.read_text(encoding="utf-8"),
            fixtures / "precision_tests/test_money_precision.py",
            output / "precision/historical-excluded.log",
        )
        if not _assertion_failure(diagnostic):
            raise ValueError("historical precision counterexample no longer reproduced")
        data["excluded_historical_precision"] = diagnostic
    validate_asset_binding(binding)
    if digest(data["runtime"]) != digest(review_runtime(fixtures=fixtures)):
        raise ValueError("runtime identity changed during preparation; prepare again")
    save_json(output / "prepared.json", {"payload": data, "digest": digest(data)})
    return output
