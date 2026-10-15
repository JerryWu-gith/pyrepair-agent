"""Independent acceptance, never trusting the repair Agent's success flag."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from .cases import EvaluationCase, case_fingerprint, contained, prepare_case, public_files
from .patching import PatchRejected, apply_patch_checked


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def read_probe(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or data.get("finished") is not True
        or type(data.get("exit_code")) is not int
        or not isinstance(data.get("collected"), list)
        or any(not isinstance(x, str) for x in data["collected"])
        or len(set(data["collected"])) != len(data["collected"])
        or not isinstance(data.get("reports"), list)
        or not isinstance(data.get("collection_errors"), list)
    ):
        raise ValueError("invalid or unfinished pytest probe")
    for row in data["reports"]:
        if (
            not isinstance(row, dict)
            or row.get("nodeid") not in data["collected"]
            or row.get("when") not in {"setup", "call", "teardown"}
            or row.get("outcome") not in {"passed", "failed", "skipped"}
            or type(row.get("wasxfail")) is not bool
        ):
            raise ValueError("invalid pytest phase report")
    return data


def clean_environment() -> dict[str, str]:
    allow = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "PATHEXT",
        "SYSTEMDRIVE",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in allow}
    env.update(
        PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
    )
    return env


def execute(command: list[str], cwd: Path, env: dict, log: Path, timeout: int) -> int:
    """Terminate only the launched process tree on a timeout."""
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        try:
            return process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=15)
            raise


def node_outcomes(probe: dict) -> dict[str, str]:
    outcomes = {}
    for node in probe["collected"]:
        phases = [r for r in probe["reports"] if r["nodeid"] == node]
        by_phase = {r["when"]: r for r in phases}
        if any(r["wasxfail"] or r["outcome"] == "skipped" for r in phases):
            outcomes[node] = "skipped"
        elif (
            len(phases) == 3
            and set(by_phase) == {"setup", "call", "teardown"}
            and all(r["outcome"] == "passed" for r in phases)
        ):
            outcomes[node] = "passed"
        elif (
            len(phases) == 3
            and by_phase.get("call", {}).get("outcome") == "failed"
            and by_phase.get("setup", {}).get("outcome") == "passed"
            and by_phase.get("teardown", {}).get("outcome") == "passed"
        ):
            outcomes[node] = "failed"
        else:
            outcomes[node] = "error"
    return outcomes


def run_tests(
    repo: Path, paths: tuple[str, ...], output: Path, timeout: int, required: tuple[str, ...] = ()
) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    probe_path = output.with_suffix(".probe.json").resolve()
    env = clean_environment()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["PYREPAIR_EVAL_PROBE"] = str(probe_path)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--rootdir=" + str(repo),
        "-c",
        str(repo / "pyproject.toml"),
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
        "-p",
        "benchmarks.evaluation.pytest_probe",
        *paths,
    ]
    result = {
        "passed": False,
        "status": "failed",
        "command": command,
        "required": list(required),
        "returncode": None,
        "outcomes": {},
    }
    try:
        code = execute(command, repo, env, output, timeout)
        result["returncode"] = code
        probe = read_probe(probe_path)
        if probe["exit_code"] != code:
            raise ValueError("pytest exit code mismatch")
        outcomes = node_outcomes(probe)
        result["outcomes"] = outcomes
        result["passed"] = (
            code == 0
            and bool(outcomes)
            and not probe["collection_errors"]
            and set(required) <= outcomes.keys()
            and all(v == "passed" for v in outcomes.values())
        )
        result["status"] = "passed" if result["passed"] else "failed"
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
    except OSError as exc:
        result.update(
            status="environment_error"
            if not isinstance(exc, FileNotFoundError) or result["returncode"] is None
            else "grader_error",
            error=str(exc),
        )
    except (ValueError, TypeError) as exc:
        result.update(status="grader_error", error=str(exc))
    return result


def _tree_hashes(repo: Path) -> dict[str, str]:
    return {
        p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in public_files(repo)
    }


def install_hidden(case: EvaluationCase, repo: Path) -> None:
    for relative in case.hidden_tests:
        target = contained(repo, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contained(case.private, relative).read_bytes())


def grade_patch(case: EvaluationCase, patch_text: str, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "case_id": case.id,
        "status": "no_patch",
        "visible": None,
        "hidden": None,
        "changed_files": [],
    }
    try:
        if patch_text.strip():
            with tempfile.TemporaryDirectory(prefix="pyrepair-grade-") as temp:
                repo = prepare_case(case, Path(temp) / "repo")
                result["changed_files"] = list(apply_patch_checked(case, repo, patch_text))
                # Hidden assets are absent even during the visible test subprocess.
                for stage, paths in (
                    ("visible", case.visible_tests),
                    ("hidden", case.hidden_tests),
                ):
                    if stage == "hidden":
                        install_hidden(case, repo)
                    expected = tuple(
                        n
                        for n in (*case.fail_to_pass, *case.pass_to_pass)
                        if n.partition("::")[0] in paths
                    )
                    hashes = _tree_hashes(repo)
                    test = run_tests(
                        repo, paths, output / (stage + ".log"), case.timeout_seconds, expected
                    )
                    result[stage] = test
                    if _tree_hashes(repo) != hashes:
                        result.update(
                            status="patch_rejected", error="candidate changed files during tests"
                        )
                        break
                    if not test["passed"]:
                        result["status"] = (
                            stage + "_failed" if test["status"] == "failed" else test["status"]
                        )
                        break
                else:
                    result["status"] = "passed"
    except PatchRejected as exc:
        result.update(status="patch_rejected", error=str(exc))
    except (OSError, subprocess.SubprocessError) as exc:
        result.update(status="environment_error", error=str(exc))
    except ValueError as exc:
        result.update(status="grader_error", error=str(exc))
    write_json(output / "grade.json", result)
    return result


def validate_case(case: EvaluationCase, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="pyrepair-preflight-") as temp:
        repo = prepare_case(case, Path(temp) / "repo")
        install_hidden(case, repo)
        hashes = _tree_hashes(repo)
        baseline = run_tests(
            repo,
            case.visible_tests + case.hidden_tests,
            output / "baseline.log",
            case.timeout_seconds,
            case.fail_to_pass + case.pass_to_pass,
        )
        unchanged = _tree_hashes(repo) == hashes
    reference = grade_patch(case, case.gold_patch.read_text(encoding="utf-8"), output / "reference")
    mutant = grade_patch(case, case.wrong_patch.read_text(encoding="utf-8"), output / "mutant")
    outcomes = baseline["outcomes"]
    valid = (
        unchanged
        and baseline["status"] == "failed"
        and baseline["returncode"] == 1
        and all(outcomes.get(n) == "failed" for n in case.fail_to_pass)
        and all(outcomes.get(n) == "passed" for n in case.pass_to_pass)
        and all(v in {"failed", "passed"} for v in outcomes.values())
        and reference["status"] == "passed"
        and mutant["status"] == "hidden_failed"
    )
    result = {
        "case_id": case.id,
        "status": "valid" if valid else "invalid_task",
        "fingerprint": case_fingerprint(case),
        "baseline": baseline,
        "reference": reference,
        "mutant": mutant,
    }
    write_json(output / "validation.json", result)
    return result
