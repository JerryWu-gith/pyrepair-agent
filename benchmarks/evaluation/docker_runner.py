"""Fail-closed Docker stage supervisor; never imports or executes upstream code.

Only preparation may build/pull. A stage uses a checked local endpoint and a
full local image ID. All stage directories and evidence are retained.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import uuid
from pathlib import Path

from . import container_protocol as protocol

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = {
    "pytest": "9.1.1",
    "iniconfig": "2.1.0",
    "packaging": "25.0",
    "pluggy": "1.6.0",
    "pygments": "2.19.2",
    "click": "8.3.0",
}
PROFILE = {
    "network": "none",
    "cpus": 2,
    "memory": 2147483648,
    "memory_swap": 2147483648,
    "pids": 128,
    "work_bytes": 268435456,
    "tmp_bytes": 67108864,
    "user": "65532:65532",
    "stage_timeout": 120,
    "startup_timeout": 30,
    "cleanup_timeout": 30,
    "log_bytes": 16777216,
    "output_bytes": 67108864,
    "output_files": 8,
}
TMPFS = {
    "/work": "rw,nosuid,nodev,size=268435456,uid=65532,gid=65532,mode=0700",
    "/tmp": "rw,nosuid,nodev,noexec,size=67108864,mode=1777",
}
ENTRYPOINT = ["python", "-I", "-B", "/opt/pyrepair/benchmarks/evaluation/container_entry.py"]
CONTAINER_ENV = (
    "PYTHONIOENCODING=utf-8",
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
    "HOME=/tmp",
)
CHECKS = (
    "non_root",
    "readonly_root",
    "readonly_input",
    "credentials_absent",
    "external_network_blocked",
    "loopback_available",
    "seccomp_active",
    "profile_inspected",
    "timeout_stopped",
)
SAFETY_NODES = tuple(
    "environment_probe.py::test_" + name for name in (*CHECKS[:7], "runtime_versions")
)


def _runtime_user() -> str:
    if os.name == "nt":
        return "65532:65532"
    uid, gid = os.getuid(), os.getgid()
    if uid <= 0 or gid <= 0:
        raise ValueError("root host identities are not supported; use a non-root local user")
    return f"{uid}:{gid}"


def _profile() -> dict:
    return {**PROFILE, "user": _runtime_user()}


def _tmpfs(lock: dict) -> dict:
    uid, gid = lock["profile"]["user"].split(":")
    return {**TMPFS, "/work": f"rw,nosuid,nodev,size=268435456,uid={uid},gid={gid},mode=0700"}


def _read_evidence(path: Path) -> dict:
    protocol.checked_root(path.parent)
    info = path.lstat()
    if protocol.is_link(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("environment evidence must be an ordinary unlinked file")
    return protocol.read_json(path)


def _write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _harness_hashes() -> dict:
    paths = [
        *(
            ROOT / "benchmarks/evaluation" / name
            for name in (
                "container_entry.py",
                "container_protocol.py",
                "pytest_probe.py",
                "agent_container_protocol.py",
                "agent_pytest_capture.py",
                "docker_runner.py",
                "docker_environment.py",
            )
        ),
        *(
            ROOT / "benchmarks/docker" / name
            for name in ("Dockerfile", "requirements.lock", "environment_probe.py")
        ),
    ]
    return {p.name: _hash(p) for p in paths}


def _cli(
    arguments: list[str],
    *,
    host: str | None = None,
    timeout: float = 30,
    preparation_network: bool = False,
) -> str:
    allow = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME"}
    if preparation_network:
        allow.update({"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"})
    env = {k: v for k, v in os.environ.items() if k.upper() in allow}
    command = ["docker", *(["--host=" + host] if host else []), *arguments]
    completed = subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=max(0.001, timeout),
        check=False,
    )
    if len(completed.stdout.encode("utf-8")) + len(completed.stderr.encode("utf-8")) > 16777216:
        raise OSError("Docker client output limit exceeded")
    if completed.returncode:
        raise OSError(
            f"Docker {arguments[0]} failed ({completed.returncode}): " + completed.stderr[:2000]
        )
    return completed.stdout


def _engine() -> dict:
    if any(
        os.environ.get(k)
        for k in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        )
    ):
        raise ValueError(
            "Docker endpoint overrides are not permitted; select a local context explicitly"
        )
    contexts = json.loads(_cli(["context", "inspect"]))
    if not isinstance(contexts, list) or len(contexts) != 1:
        raise ValueError("ambiguous Docker context")
    endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
    if not isinstance(endpoint, str) or not (
        re.fullmatch(r"npipe:////\./pipe/[A-Za-z0-9_.-]+", endpoint)
        or re.fullmatch(r"unix:///[^\x00-\x20]+", endpoint)
    ):
        raise ValueError("only local npipe/unix Docker endpoints are supported")
    info = json.loads(_cli(["info", "--format", "{{json .}}"], host=endpoint))
    if info.get("OSType") != "linux" or info.get("Architecture") not in ("x86_64", "amd64"):
        raise ValueError("Docker must be a local Linux/amd64 engine")
    options = info.get("SecurityOptions")
    if (
        not isinstance(options, list)
        or any(not isinstance(option, str) for option in options)
        or [option for option in options if option.startswith("name=seccomp")]
        != ["name=seccomp,profile=builtin"]
    ):
        raise ValueError("Docker engine must report builtin seccomp")
    return {"host": endpoint, "context": contexts[0].get("Name"), "info": info}


def _load_lock(path: Path) -> dict:
    protocol.checked_root(path.parent)
    lock = _read_evidence(path)
    if (
        type(lock.get("version")) is not int
        or lock["version"] != 1
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(lock.get("image_id")))
        or not re.fullmatch(
            r"docker.io/library/python@sha256:[0-9a-f]{64}", str(lock.get("base_image"))
        )
        or lock.get("platform") != "linux/amd64"
        or lock.get("python") != "3.13.5"
        or lock.get("pytest") != "9.1.1"
        or lock.get("dependencies") != DEPENDENCIES
        or json.dumps(lock.get("profile"), sort_keys=True) != json.dumps(_profile(), sort_keys=True)
        or lock.get("harness_hashes") != _harness_hashes()
    ):
        raise ValueError("invalid or stale Docker environment lock")
    return lock


def _image(lock: dict, host: str) -> dict:
    image = json.loads(
        _cli(["image", "inspect", "--format", "{{json .}}", lock["image_id"]], host=host)
    )
    if (
        image.get("Id") != lock["image_id"]
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
    ):
        raise ValueError("locked local image is missing or has the wrong identity/platform")
    return image


def _inspect(cid: str, host: str, timeout: float = 30) -> dict:
    value = json.loads(_cli(["inspect", "--format", "{{json .}}", cid], host=host, timeout=timeout))
    if (
        not isinstance(value, dict)
        or value.get("Id") != cid
        or not isinstance(value.get("State"), dict)
    ):
        raise ValueError("Docker container inspection identity mismatch")
    return value


def _inspect_profile(value: dict, lock: dict, mounts: dict[str, Path]) -> None:
    config, host = value["Config"], value["HostConfig"]
    if not isinstance(config, dict) or not isinstance(host, dict):
        raise TypeError("invalid container configuration inspection")
    expected = {
        "NetworkMode": "none",
        "ReadonlyRootfs": True,
        "NanoCpus": 2000000000,
        "Memory": 2147483648,
        "MemorySwap": 2147483648,
        "PidsLimit": 128,
        "Privileged": False,
        "PidMode": "",
        "IpcMode": "private",
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true"],
        "AutoRemove": False,
        "Tmpfs": _tmpfs(lock),
    }
    if (
        any(host.get(k) != v for k, v in expected.items())
        or any(host.get(k) for k in ("CapAdd", "Devices", "Binds", "DeviceRequests"))
        or host.get("RestartPolicy", {}).get("Name") != "no"
        or host.get("LogConfig", {}).get("Type") != "none"
    ):
        raise ValueError("container security/resource profile was not enforced")
    if (
        config.get("User") != lock["profile"]["user"]
        or config.get("Image") != lock["image_id"]
        or config.get("Entrypoint") != ENTRYPOINT
    ):
        raise ValueError("container user/image/entrypoint mismatch")
    env = config.get("Env", [])
    allowed = {row.partition("=")[0] for row in CONTAINER_ENV} | {
        "PATH",
        "LANG",
        "GPG_KEY",
        "PYTHON_VERSION",
        "PYTHON_SHA256",
        "PYTHON_PIP_VERSION",
        "PYTHON_SETUPTOOLS_VERSION",
        "PYTHON_GET_PIP_URL",
        "PYTHON_GET_PIP_SHA256",
    }
    if (
        not isinstance(env, list)
        or any(not isinstance(row, str) for row in env)
        or not set(CONTAINER_ENV) <= set(env)
        or any(row.partition("=")[0] not in allowed for row in env)
        or len({row.partition("=")[0] for row in env}) != len(env)
    ):
        raise ValueError("container environment mismatch")
    entries = value["Mounts"]
    if not isinstance(entries, list) or any(not isinstance(m, dict) for m in entries):
        raise ValueError("invalid mount inspection")
    if any(
        m.get("Type") != "bind"
        and not (m.get("Type") == "tmpfs" and m.get("Destination") in _tmpfs(lock))
        for m in entries
    ):
        raise ValueError("unexpected container mount")
    binds = [m for m in entries if m.get("Type") == "bind"]
    if len(binds) != 2 or {m["Destination"] for m in binds} != set(mounts):
        raise ValueError("container mounts mismatch")
    if any(
        m.get("RW") is not (m["Destination"] == "/output")
        or _mount_source(m.get("Source")) != _mount_source(str(mounts[m["Destination"]]))
        for m in binds
    ):
        raise ValueError("container input/output mount permissions mismatch")


def _mount_source(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("invalid mount source")
    value = value.replace("\\", "/").rstrip("/")
    for prefix in ("/run/desktop/mnt/host/", "/host_mnt/"):
        if value.startswith(prefix) and re.match(r"[a-zA-Z]/", value[len(prefix) :]):
            value = value[len(prefix)] + ":" + value[len(prefix) + 1 :]
    return value.casefold() if re.match(r"^[a-zA-Z]:/", value) else value


def _create_command(lock: dict, stage: Path, run_id: str) -> list[str]:
    return [
        "create",
        "--pull=never",
        "--name=pyrepair-" + run_id,
        "--cidfile",
        str(stage / "container.cid"),
        "--network=none",
        "--read-only",
        "--user=" + lock["profile"]["user"],
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--cpus=2",
        "--memory=2147483648",
        "--memory-swap=2147483648",
        "--pids-limit=128",
        "--ipc=private",
        "--restart=no",
        "--log-driver=none",
        *("--tmpfs=" + k + ":" + v for k, v in _tmpfs(lock).items()),
        *(argument for env in CONTAINER_ENV for argument in ("--env", env)),
        "--mount",
        f"type=bind,src={stage / 'input'},dst=/input,readonly",
        "--mount",
        f"type=bind,src={stage / 'output'},dst=/output",
        lock["image_id"],
    ]


def _recorded_cid(stage: Path) -> str | None:
    path = stage / "container.cid"
    if not path.exists():
        return None
    if protocol.is_link(path) or path.stat().st_size > 65:
        raise ValueError("invalid container ID file")
    value = path.read_text("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid container ID")
    return value


def _stage(
    lock_path: Path,
    lock: dict,
    engine: dict,
    repo: Path,
    paths: tuple[str, ...],
    output: Path,
    timeout: int,
    required: tuple[str, ...] = (),
    *,
    agent_mode: bool = False,
    target: str | None = None,
) -> dict:
    result = {
        "passed": False,
        "status": "environment_error",
        "returncode": None,
        "outcomes": {},
        "required": list(required),
        "backend": "docker",
        "started": False,
        "cleanup_errors": [],
    }
    cid, stage, state, exit_code = None, None, None, None
    try:
        output = output.absolute()
        if output.exists() or protocol.is_link(output):
            raise protocol.ProtocolError("refusing to overwrite an existing stage log")
        if output.is_relative_to(repo.resolve()):
            raise protocol.ProtocolError("output cannot be inside the input repository")
        if any(protocol.is_link(p) for p in (output.parent, *output.parents)):
            raise protocol.ProtocolError("linked output parent")
        output.parent.mkdir(parents=True, exist_ok=True)
        inventory = protocol.input_inventory(repo, paths)
        request = protocol.validate_request(
            {
                "version": 2 if agent_mode else 1,
                "run_id": uuid.uuid4().hex,
                "stage_id": uuid.uuid4().hex,
                "input_hash": protocol.inventory_hash(inventory),
                "environment_hash": _hash(lock_path),
                "paths": list(paths),
                "required": list(required),
                "timeout": timeout,
                **({"mode": "agent", "target": target} if agent_mode else {}),
            }
        )
        candidate = output.with_name(output.name + ".docker")
        if "," in str(candidate) or any(ord(c) < 32 for c in str(candidate)):
            raise protocol.ProtocolError(
                "comma/control character in Docker mount source is unsupported"
            )
        candidate.mkdir()
        stage = candidate
        (stage / "input/repo").mkdir(parents=True)
        (stage / "output").mkdir()
        for name in inventory:
            destination = stage / "input/repo" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo / name, destination)
        if protocol.input_inventory(stage / "input/repo", paths) != inventory:
            raise protocol.ProtocolError("input changed during staging")
        _write_json(stage / "input/request.json", request)
        _write_json(stage / "input/inventory.json", inventory)
        result.update(identity={k: request[k] for k in protocol.IDENTITY}, artifacts=str(stage))
        startup = time.monotonic() + 30
        command = _create_command(lock, stage, request["run_id"])
        result["command"] = ["docker", *command]
        created = _cli(command, host=engine["host"], timeout=startup - time.monotonic()).strip()
        cid = _recorded_cid(stage)
        if cid is None or cid != created:
            raise ValueError("Docker create response disagrees with recorded ID")
        result["container_id"] = cid
        _write_json(stage / "container.json", {"container_id": cid, **result["identity"]})
        _inspect_profile(
            _inspect(cid, engine["host"], startup - time.monotonic()),
            lock,
            {"/input": stage / "input", "/output": stage / "output"},
        )
        _cli(["start", cid], host=engine["host"], timeout=startup - time.monotonic())
        result["started"] = True
        deadline = time.monotonic() + timeout
        while True:
            protocol.output_files(stage / "output")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(["docker", "wait", cid], timeout)
            try:
                waited = _cli(["wait", cid], host=engine["host"], timeout=min(1, remaining)).strip()
            except subprocess.TimeoutExpired:
                continue
            if not re.fullmatch(r"[0-9]{1,3}", waited):
                raise ValueError("invalid container wait exit code")
            exit_code = int(waited)
            break
    except subprocess.TimeoutExpired:
        result.update(status="timeout", error="container stage/startup timeout")
    except (protocol.ProtocolError, ValueError, TypeError, KeyError) as exc:
        result.update(status="grader_error", error=str(exc)[:2000])
    except (OSError, subprocess.SubprocessError) as exc:
        result.update(status="environment_error", error=str(exc)[:2000])
    finally:
        # cidfile can survive a failing/interrupted Docker create client.
        if stage is not None and stage.is_dir():
            try:
                cid = cid or _recorded_cid(stage)
            except (OSError, ValueError) as exc:
                result["cleanup_errors"].append(str(exc))
        if cid is not None:
            result["container_id"] = cid
            cleanup = time.monotonic() + 30
            cleanup_interrupt = None
            for action in ("stop", "inspect", "rm"):
                try:
                    remaining = cleanup - time.monotonic()
                    if remaining <= 0:
                        raise OSError("container cleanup deadline exceeded")
                    # Keep time inside the same deadline for the final exact-ID rm.
                    budget = max(0.001, remaining - (2 if action == "stop" else 1))
                    if action == "rm":
                        budget = remaining
                    if action == "inspect":
                        state = _inspect(cid, engine["host"], budget)
                        if state["State"].get("Running") is not False:
                            raise ValueError("container still running after stop")
                    else:
                        args = [action, *(["--time=1"] if action == "stop" else ["--force"]), cid]
                        _cli(args, host=engine["host"], timeout=budget)
                except KeyboardInterrupt as exc:
                    cleanup_interrupt = exc
                    result["cleanup_errors"].append(f"{action}: KeyboardInterrupt")
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                    subprocess.SubprocessError,
                ) as exc:
                    result["cleanup_errors"].append(f"{action}: {str(exc)[:1000]}")
            if state is not None:
                _write_json(stage / "container-state.json", state)
            _write_json(stage / "execution.json", result)
            if cleanup_interrupt is not None:
                raise cleanup_interrupt
    if result["cleanup_errors"]:
        result.update(passed=False, status="environment_error", error="container cleanup failed")
    elif exit_code is not None:
        try:
            runtime = state["State"]
            if runtime.get("OOMKilled") or runtime.get("Error") or exit_code not in (0, 1):
                raise OSError("container resource/runtime failure")
            if type(runtime.get("ExitCode")) is not int or runtime["ExitCode"] != exit_code:
                raise ValueError("container wait/inspect exit code mismatch")
            checked = protocol.read_stage_output(stage / "output", request)
            expected = 0 if checked["passed"] else 2 if checked["status"] == "grader_error" else 1
            if exit_code != expected:
                raise ValueError("container entry exit code contradicts stage evidence")
            result.update(checked)
            # Copy only the bounded, validated ordinary log after container removal.
            with output.open("xb") as log:
                log.write((stage / "output/pytest.log").read_bytes())
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result.update(
                passed=False,
                status="environment_error" if isinstance(exc, OSError) else "grader_error",
                error=str(exc)[:2000],
            )
    if stage is not None and stage.is_dir():
        _write_json(stage / "supervisor-result.json", result)
    return result


class DockerTestRunner:
    """Callable run_tests replacement; immutable evidence is rechecked per stage."""

    def __init__(self, environment_lock: Path):
        self.environment_lock = Path(environment_lock).absolute()

    def assert_environment_verified(self) -> dict:
        lock = _load_lock(self.environment_lock)
        try:
            check = _read_evidence(self.environment_lock.with_name("environment-check.json"))
        except OSError as exc:
            raise ValueError("Docker environment check evidence is missing or unreadable") from exc
        if (
            type(check.get("version")) is not int
            or check["version"] != 1
            or check.get("status") != "environment_verified"
            or check.get("lock_hash") != _hash(self.environment_lock)
            or check.get("image_id") != lock["image_id"]
            or not isinstance(check.get("checks"), dict)
            or set(check["checks"]) != set(CHECKS)
            or any(check.get("checks", {}).get(k) is not True for k in CHECKS)
        ):
            raise ValueError("Docker environment has not passed the owned safety probes")
        for name, status in (("safety_stage", "passed"), ("timeout_stage", "timeout")):
            stage = check.get(name)
            if (
                not isinstance(stage, dict)
                or stage.get("passed") is not (status == "passed")
                or stage.get("status") != status
                or stage.get("cleanup_errors") != []
                or not re.fullmatch(r"[0-9a-f]{64}", str(stage.get("container_id")))
                or not isinstance(stage.get("identity"), dict)
                or stage["identity"].get("environment_hash") != check["lock_hash"]
            ):
                raise ValueError("environment probe stage evidence is missing or inconsistent")
        engine = _engine()
        _image(lock, engine["host"])
        return {
            "backend": "docker",
            "environment_hash": _hash(self.environment_lock),
            "image_id": lock["image_id"],
            "engine": engine,
            "lock": lock,
        }

    def __call__(
        self,
        repo: Path,
        paths: tuple[str, ...],
        output: Path,
        timeout: int,
        required: tuple[str, ...] = (),
    ) -> dict:
        return self._execute(repo, paths, output, timeout, required)

    def run_agent(
        self,
        repo: Path,
        paths: tuple[str, ...],
        output: Path,
        timeout: int,
        *,
        target: str | None = None,
    ) -> dict:
        """Explicit diagnostic execution, never substituted for grader-v1 acceptance."""
        required = () if target is None else (target,)
        return self._execute(repo, paths, output, timeout, required, agent_mode=True, target=target)

    def _execute(
        self,
        repo: Path,
        paths: tuple[str, ...],
        output: Path,
        timeout: int,
        required: tuple[str, ...],
        *,
        agent_mode: bool = False,
        target: str | None = None,
    ) -> dict:
        try:
            verified = self.assert_environment_verified()
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            return {
                "passed": False,
                "status": "environment_error",
                "returncode": None,
                "outcomes": {},
                "required": list(required),
                "error": str(exc)[:2000],
                "backend": "docker",
                "cleanup_errors": [],
            }
        return _stage(
            self.environment_lock,
            verified["lock"],
            verified["engine"],
            Path(repo),
            paths,
            Path(output),
            timeout,
            required,
            agent_mode=agent_mode,
            target=target,
        )


def prepare_environment(output: Path) -> dict:
    """Explicit network/build operation; never called implicitly by a runner."""
    from .docker_environment import prepare_environment as prepare

    return prepare(output)


def check_environment(lock: Path, output: Path) -> dict:
    """Run only owned probes against an already-built, locked image."""
    from .docker_environment import check_environment as check

    return check(lock, output)
