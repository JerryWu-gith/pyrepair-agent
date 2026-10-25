"""Internal container entry; not a host sandbox or a public evaluation backend.

Host unit tests may invoke it only with self-authored fixtures. Upstream tasks
must be dispatched by the verified Docker backend (implemented separately).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# File execution with -I must resolve the image's own harness, never cwd.
TRUSTED_ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(TRUSTED_ROOT))

from benchmarks.evaluation.container_protocol import (
    IDENTITY,
    ProtocolError,
    checked_root,
    input_inventory,
    inventory_hash,
    is_link,
    output_files,
    read_json,
    read_stage_output,
    validate_inventory,
    validate_request,
    validate_stage_result,
)


def _write_new_json(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)


def _check_roots(input_root: Path, work_root: Path, output_root: Path) -> None:
    roots = (input_root, work_root, output_root)
    for root in roots:
        if any(is_link(p) for p in (root, *root.parents)):
            raise ProtocolError("linked execution root")
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            a, b = left.resolve(), right.resolve()
            if a.is_relative_to(b) or b.is_relative_to(a):
                raise ProtocolError("execution roots overlap")
    checked_root(input_root)
    for root in (work_root, output_root):
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise ProtocolError("execution work/output root must be empty")


def _stop_child(process: subprocess.Popen) -> None:
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=15,
            )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def execute_tests(
    repo: Path, output: Path, paths: list[str], timeout: int, *, agent_mode: bool = False
) -> int:
    # Keep only runtime essentials, not user Python/pytest options or credentials.
    allow = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allow}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONIOENCODING="utf-8")
    command = [
        sys.executable,
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        "--pytest-agent-child" if agent_mode else "--pytest-child",
        str(repo.resolve()),
        str((output / "probe.json").resolve()),
        *paths,
    ]
    with (output / "pytest.log").open("xb") as log:
        process = subprocess.Popen(
            command,
            cwd=repo,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                output_files(output)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    return process.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            _stop_child(process)
            raise


def run_stage(request: dict, input_root: Path, work_root: Path, output_root: Path) -> int:
    """Run one isolated-work-copy stage; caller must supply the Docker boundary."""
    validate_request(request)
    _check_roots(input_root, work_root, output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    identity = {k: request[k] for k in IDENTITY}
    try:
        inventory = validate_inventory(read_json(input_root / "inventory.json"))
        if inventory_hash(inventory) != request["input_hash"]:
            raise ProtocolError("request inventory digest mismatch")
        source = input_root / "repo"
        if input_inventory(source, tuple(request["paths"])) != inventory:
            raise ProtocolError("staging inventory mismatch")
        work_root.mkdir(parents=True, exist_ok=True)
        for name in inventory:
            target = work_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        before = input_inventory(work_root, tuple(request["paths"]))
        if before != inventory:
            raise ProtocolError("copied inventory mismatch")
        if "pyproject.toml" not in before:
            raise ProtocolError("stage requires a pinned pyproject.toml")
        agent_mode = request["version"] == 2
        selections = (
            [request["target"]]
            if agent_mode and request["target"] is not None
            else request["paths"]
        )
        code = execute_tests(
            work_root, output_root, selections, request["timeout"], agent_mode=agent_mode
        )
        # No cache exclusions: -B and no:cacheprovider prevent expected cache writes.
        after = input_inventory(work_root, ())
        integrity = {"before": before, "after": after, "unchanged": before == after}
        _write_new_json(output_root / "integrity.json", integrity)
        output_files(output_root)
        result = {
            **identity,
            "pytest_returncode": code,
            "probe": read_json(output_root / "probe.json"),
            "integrity": integrity,
        }
        checked = validate_stage_result(result, request)
        _write_new_json(output_root / "result.json", result)
        read_stage_output(output_root, request)
        return 0 if checked["passed"] else 2 if checked["status"] == "grader_error" else 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        try:
            _write_new_json(
                output_root / "error.json",
                {
                    **identity,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:2000],
                },
            )
        except OSError:
            # Do not overwrite evidence supplied by a failed/untrusted stage.
            # The supervising backend must honor exit 2 even if no error record
            # can be written (e.g. output full or error.json already exists).
            pass
        return 2


def _pytest_child(
    repo: Path, probe_path: Path, paths: list[str], *, agent_mode: bool = False
) -> int:
    import pytest

    # Import the trusted plugin before exposing repository modules to import.
    from benchmarks.evaluation import pytest_probe

    plugins = [pytest_probe]
    if agent_mode:
        from benchmarks.evaluation import agent_pytest_capture

        plugins.append(agent_pytest_capture)
    sys.path.insert(1, str(repo))
    os.environ["PYREPAIR_EVAL_PROBE"] = str(probe_path)
    return int(
        pytest.main(
            [
                "-q",
                "--tb=short",
                "--rootdir=" + str(repo),
                "-c",
                str(repo / "pyproject.toml"),
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                *paths,
            ],
            plugins=plugins,
        )
    )


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] in ("--pytest-child", "--pytest-agent-child"):
        raise SystemExit(
            _pytest_child(
                Path(sys.argv[2]),
                Path(sys.argv[3]),
                sys.argv[4:],
                agent_mode=sys.argv[1] == "--pytest-agent-child",
            )
        )
    if len(sys.argv) != 1:
        raise SystemExit("container entry accepts only its fixed mounted input")
    raise SystemExit(
        run_stage(
            read_json(Path("/input/request.json")),
            Path("/input"),
            Path("/work"),
            Path("/output"),
        )
    )
