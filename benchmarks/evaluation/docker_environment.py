"""Explicit Docker image preparation and owned safety checks, not upstream tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import docker_runner as runner

BASE_TAG = "docker.io/library/python:3.13.5-slim-bookworm"


def _read_release_metadata(name: str, url: str) -> tuple[dict, int, list[str]]:
    deadline = time.monotonic() + 30
    attempts = 0
    transient_errors = []
    while attempts < 3:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        attempts += 1
        try:
            with urllib.request.urlopen(url, timeout=remaining) as response:
                value = json.load(response)
            if deadline - time.monotonic() <= 0:
                break
            return value, attempts, transient_errors
        except (ssl.SSLEOFError, urllib.error.URLError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            if not isinstance(reason, ssl.SSLEOFError):
                raise
            transient_errors.append("SSLEOFError")
            if attempts == 3:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min((0.25, 0.5)[attempts - 1], remaining))
    detail = transient_errors[-1] if transient_errors else "URLBudgetExpired"
    raise OSError(
        f"official release metadata request failed for {name} ({url}) "
        f"after {attempts} attempts: {detail}"
    ) from None


def _release_metadata() -> dict:
    """Read only official release metadata; install nothing on the host."""
    lock_text = (runner.ROOT / "benchmarks/docker/requirements.lock").read_text("utf-8")
    expected = dict(re.findall(r"([a-z]+)==[\d.]+ --hash=sha256:([0-9a-f]{64})", lock_text))
    records = {}
    for name, version in runner.DEPENDENCIES.items():
        url = f"https://pypi.org/pypi/{name}/{version}/json"
        value, attempts, transient_errors = _read_release_metadata(name, url)
        wheels = [
            row
            for row in value["urls"]
            if row["packagetype"] == "bdist_wheel" and row["filename"].endswith("-py3-none-any.whl")
        ]
        if (
            value["info"]["version"] != version
            or len(wheels) != 1
            or wheels[0]["digests"]["sha256"] != expected.get(name)
        ):
            raise ValueError("official release metadata disagrees with dependency wheel lock")
        records[name] = {
            "version": version,
            "wheel": wheels[0]["filename"],
            "sha256": expected[name],
            "source": url,
            "attempts": attempts,
            "transient_errors": transient_errors,
            "requires_python": value["info"].get("requires_python"),
            "requires_dist": value["info"].get("requires_dist"),
        }
    return records


def _fresh_directory(path: Path) -> None:
    if any(runner.protocol.is_link(p) for p in (path, *path.parents)):
        raise ValueError("linked environment output")
    path.mkdir(parents=True, exist_ok=False)


def _owned_repo(parent: Path, name: str, content: str) -> Path:
    repo = parent / (name + "-repo")
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / name).write_text(content, encoding="utf-8")
    return repo


def prepare_environment(output: Path) -> dict:
    """Explicitly resolve official base digest, build a narrow context and lock.

    output is a new directory. This operation needs separate build/network
    authorization; the runner and check_environment never invoke it themselves.
    """
    output = Path(output).absolute()
    result = {"status": "environment_error", "environment_verified": False}
    owned = False
    try:
        _fresh_directory(output)
        owned = True
        engine = runner._engine()
        metadata = _release_metadata()
        runner._write_json(output / "pypi-metadata.json", metadata)
        manifest = json.loads(
            runner._cli(
                ["buildx", "imagetools", "inspect", "--raw", BASE_TAG],
                host=engine["host"],
                preparation_network=True,
            )
        )
        matches = [
            row
            for row in manifest["manifests"]
            if row.get("platform", {}).get("os") == "linux"
            and row["platform"].get("architecture") == "amd64"
            and row["platform"].get("variant") in (None, "")
        ]
        if len(matches) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", matches[0]["digest"]):
            raise ValueError("official Python manifest has no unique Linux/amd64 digest")
        base = "docker.io/library/python@" + matches[0]["digest"]
        runner._write_json(output / "base-manifest.json", manifest)
        context = output / "build-context"
        context.mkdir()
        for name in ("Dockerfile", "requirements.lock", "environment_probe.py"):
            shutil.copyfile(runner.ROOT / "benchmarks/docker" / name, context / name)
        for name in (
            "container_entry.py",
            "container_protocol.py",
            "pytest_probe.py",
            "agent_container_protocol.py",
            "agent_pytest_capture.py",
        ):
            shutil.copyfile(runner.ROOT / "benchmarks/evaluation" / name, context / name)
        runner._cli(
            [
                "build",
                "--platform=linux/amd64",
                "--pull",
                "--build-arg",
                "BASE_IMAGE=" + base,
                "--iidfile",
                str(output / "image-id.txt"),
                str(context),
            ],
            host=engine["host"],
            timeout=600,
            preparation_network=True,
        )
        image_id = (output / "image-id.txt").read_text("ascii").strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("build did not produce a full local image ID")
        lock = {
            "version": 1,
            "image_id": image_id,
            "base_image": base,
            "platform": "linux/amd64",
            "python": "3.13.5",
            "pytest": "9.1.1",
            "dependencies": dict(runner.DEPENDENCIES),
            "profile": runner._profile(),
            "harness_hashes": runner._harness_hashes(),
        }
        runner._image(lock, engine["host"])
        provisional = output / "build-lock.json"
        runner._write_json(provisional, lock)
        content = (
            "import sys\nfrom importlib.metadata import version\n"
            "def test_versions():\n    assert sys.version_info[:3] == (3, 13, 5)\n"
            + "".join(
                f"    assert version({name!r}) == {version!r}\n"
                for name, version in runner.DEPENDENCIES.items()
            )
        )
        repo = _owned_repo(output, "test_versions.py", content)
        probe = runner._stage(
            provisional,
            lock,
            engine,
            repo,
            ("test_versions.py",),
            output / "versions.log",
            120,
            ("test_versions.py::test_versions",),
        )
        if not probe["passed"]:
            raise ValueError("built image failed the owned exact-version probe")
        runner._write_json(output / "environment-lock.json", lock)
        result.update(
            status="environment_prepared",
            lock=str(output / "environment-lock.json"),
            image_id=image_id,
            base_image=base,
            engine=engine,
            versions_probe=probe,
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result["error"] = str(exc)[:2000]
    if owned:
        runner._write_json(output / "preparation.json", result)
    return result


def check_environment(lock: Path, output: Path) -> dict:
    """Write a fresh canonical check JSON only after real owned stages pass.

    output must be lock.parent / 'environment-check.json'. Existing evidence
    is never replaced. Real integration tests use a copied lock in a new root.
    """
    lock_path, output = Path(lock).absolute(), Path(output).absolute()
    result = {"version": 1, "status": "environment_error", "checks": {}}
    owned = False
    previous_sentinel = os.environ.get("PYREPAIR_CREDENTIAL_SENTINEL")
    try:
        if output != lock_path.with_name("environment-check.json"):
            raise ValueError("check output must be the lock's canonical environment-check.json")
        if output.exists() or runner.protocol.is_link(output):
            raise ValueError("refusing to overwrite existing environment check evidence")
        current = runner._load_lock(lock_path)
        engine = runner._engine()
        runner._image(current, engine["host"])
        root = output.with_name(output.name + ".docker-check")
        _fresh_directory(root)
        owned = True
        result.update(
            lock_hash=runner._hash(lock_path), image_id=current["image_id"], engine=engine
        )
        os.environ["PYREPAIR_CREDENTIAL_SENTINEL"] = "worthless-owned-docker-sentinel"
        content = (runner.ROOT / "benchmarks/docker/environment_probe.py").read_text("utf-8")
        repo = _owned_repo(root, "environment_probe.py", content)
        names = runner.CHECKS[:7]
        stage = runner._stage(
            lock_path,
            current,
            engine,
            repo,
            ("environment_probe.py",),
            root / "safety.log",
            120,
            runner.SAFETY_NODES,
        )
        result["safety_stage"] = stage
        if not stage["passed"] or stage["cleanup_errors"]:
            raise ValueError("owned container safety probe failed")
        result["checks"].update({key: True for key in (*names, "profile_inspected")})
        repo = _owned_repo(
            root, "test_timeout.py", "import time\ndef test_timeout(): time.sleep(120)\n"
        )
        timeout = runner._stage(
            lock_path, current, engine, repo, ("test_timeout.py",), root / "timeout.log", 1
        )
        result["timeout_stage"] = timeout
        if (
            timeout["status"] != "timeout"
            or timeout["cleanup_errors"]
            or timeout.get("started") is not True
            or not timeout.get("container_id")
        ):
            raise ValueError("owned timeout probe did not stop/remove its recorded container")
        if runner._hash(lock_path) != result["lock_hash"]:
            raise ValueError("environment lock changed during probes")
        result["checks"]["timeout_stopped"] = True
        result["status"] = "environment_verified"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result["error"] = str(exc)[:2000]
    finally:
        if previous_sentinel is None:
            os.environ.pop("PYREPAIR_CREDENTIAL_SENTINEL", None)
        else:
            os.environ["PYREPAIR_CREDENTIAL_SENTINEL"] = previous_sentinel
    if owned:
        runner._write_json(output, result)
    return result
