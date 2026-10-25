"""Owned fixtures exercise the real backend at its external Docker boundary."""

import hashlib
import importlib
import io
import json
import os
import ssl
import subprocess
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

IMAGE = "sha256:" + "1" * 64
CID = "2" * 64
RELEASES = {
    "pytest": (
        "9.1.1",
        "37a86b45efb9a47a61a36449063e8e18d0cab3161329fc099eb21783169c4f0c",
    ),
    "iniconfig": (
        "2.1.0",
        "9deba5723312380e77435581c6bf4935c94cbfab9b1ed33ef8d238ea168eb760",
    ),
    "packaging": (
        "25.0",
        "29572ef2b1f17581046b3a2227d5c611fb25ec70ca1ba8554b24b0e69331a484",
    ),
    "pluggy": (
        "1.6.0",
        "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746",
    ),
    "pygments": (
        "2.19.2",
        "86540386c03d588bb81d44bc3928634ff26449851e99741617ecb9037ee5ec0b",
    ),
}


class MetadataClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def metadata_response(name, digest=None):
    version, locked_digest = RELEASES[name]
    value = {
        "info": {
            "version": version,
            "requires_python": ">=3.9",
            "requires_dist": [],
        },
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "filename": f"{name}-{version}-py3-none-any.whl",
                "digests": {"sha256": digest or locked_digest},
            },
            {
                "packagetype": "sdist",
                "filename": f"{name}-{version}.tar.gz",
                "digests": {"sha256": "f" * 64},
            },
        ],
    }
    return io.StringIO(json.dumps(value))


def metadata_package(url):
    name = url.removeprefix("https://pypi.org/pypi/").split("/", 1)[0]
    version = RELEASES[name][0]
    assert url == f"https://pypi.org/pypi/{name}/{version}/json"
    return name


def backend():
    return importlib.import_module("benchmarks.evaluation.docker_runner")


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def docker_action(command):
    return command[2] if command[1].startswith("--host=") else command[1]


class DockerBoundary:
    """Only Docker is replaced; staging, protocol, locks and outputs stay real."""

    def __init__(self, module, monkeypatch):
        self.module = module
        self.commands = []
        self.calls = []
        self.raw_commands = []
        self.problem = None
        self.waiting = 0
        self.exit_code = 0
        self.started = False
        self.mutate_output = lambda output, result: None
        self.mounts = {}
        self.host = "npipe:////./pipe/docker_engine"
        self.security_options = ["name=seccomp,profile=builtin", "name=cgroupns"]
        self.inspect_mutation = lambda value: None
        self.tick = 0
        self.timeout_probe = False
        self.manifest = {
            "manifests": [
                {
                    "digest": "sha256:" + "3" * 64,
                    "platform": {"os": "linux", "architecture": "amd64"},
                }
            ]
        }
        monkeypatch.setattr(module.subprocess, "run", self.run)

    def run(self, command, **kwargs):
        assert isinstance(command, list)
        assert kwargs.get("shell", False) is False
        assert kwargs["timeout"] <= (600 if "build" in command else 30)
        assert not any("KEY" in key or key.startswith("DOCKER_") for key in kwargs["env"])
        self.raw_commands.append(command)
        if len(command) > 1 and command[1].startswith("--host="):
            assert command[1] == "--host=" + self.host
            normalized = [command[0], *command[2:]]
        else:
            normalized = command
        assert not any(part.startswith("--host=") for part in normalized[1:])
        self.commands.append(normalized)
        self.calls.append((normalized, dict(kwargs["env"])))
        action = normalized[1]
        if self.problem == action:
            raise OSError("owned daemon failure")
        value = ""
        if action == "context":
            value = json.dumps(
                [{"Name": "owned-local", "Endpoints": {"docker": {"Host": self.host}}}]
            )
        elif action == "info":
            value = json.dumps(
                {
                    "OSType": "linux",
                    "Architecture": "x86_64",
                    "SecurityOptions": self.security_options,
                }
            )
        elif action == "image":
            value = json.dumps({"Id": IMAGE, "Os": "linux", "Architecture": "amd64"})
        elif action == "buildx":
            assert normalized == [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                "--raw",
                "docker.io/library/python:3.13.5-slim-bookworm",
            ]
            value = json.dumps(self.manifest)
        elif action == "build":
            Path(command[command.index("--iidfile") + 1]).write_text(IMAGE, encoding="ascii")
        elif action == "create":
            for argument in command:
                if argument.startswith("type=bind,"):
                    fields = dict(item.split("=", 1) for item in argument.split(",") if "=" in item)
                    self.mounts[fields["dst"]] = Path(fields["src"])
            assert set(self.mounts) == {"/input", "/output"}
            assert not any(self.mounts["/output"].iterdir())
            cidfile = Path(command[command.index("--cidfile") + 1])
            cidfile.write_text(CID, encoding="ascii")
            value = CID + "\n"
        elif action == "start":
            self.started = True
            request = json.loads((self.mounts["/input"] / "request.json").read_text("utf-8"))
            self.timeout_probe = request["paths"] == ["test_timeout.py"]
            inventory = json.loads((self.mounts["/input"] / "inventory.json").read_text("utf-8"))
            nodes = request["required"] or [request["paths"][0] + "::test_owned"]
            probe = {
                "version": 1,
                "finished": True,
                "exit_code": 0,
                "collected": nodes,
                "collection_errors": [],
                "reports": [
                    {"nodeid": node, "when": phase, "outcome": "passed", "wasxfail": False}
                    for node in nodes
                    for phase in ("setup", "call", "teardown")
                ],
            }
            result = {
                key: request[key]
                for key in ("version", "run_id", "stage_id", "input_hash", "environment_hash")
            }
            result.update(
                pytest_returncode=0,
                probe=probe,
                integrity={"before": inventory, "after": inventory, "unchanged": True},
            )
            if request["version"] == 2:
                probe["failures"] = []
            output = self.mounts["/output"]
            for name, data in {
                "result": result,
                "probe": probe,
                "integrity": result["integrity"],
            }.items():
                write_json(output / (name + ".json"), data)
            (output / "pytest.log").write_text("owned pass\n", encoding="utf-8")
            self.mutate_output(output, result)
            value = CID + "\n"
        elif action == "wait":
            if self.timeout_probe:
                self.tick += 2
                raise subprocess.TimeoutExpired(command, 1)
            if self.waiting:
                self.waiting -= 1
                raise subprocess.TimeoutExpired(command, 1)
            value = str(self.exit_code) + "\n"
        elif action == "inspect":
            value = json.dumps(
                {
                    "Id": CID,
                    "State": {
                        "Running": False,
                        "ExitCode": self.exit_code,
                        "OOMKilled": self.problem == "oom",
                        "Error": "",
                    },
                    "Config": {
                        "User": self.module._profile()["user"],
                        "Image": IMAGE,
                        "Entrypoint": [
                            "python",
                            "-I",
                            "-B",
                            "/opt/pyrepair/benchmarks/evaluation/container_entry.py",
                        ],
                        "Env": [
                            "PYTHONIOENCODING=utf-8",
                            "PYTHONDONTWRITEBYTECODE=1",
                            "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                            "HOME=/tmp",
                        ],
                    },
                    "HostConfig": {
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
                        "CapAdd": None,
                        "Devices": [],
                        "Binds": None,
                        "SecurityOpt": ["no-new-privileges:true"],
                        "RestartPolicy": {"Name": "no"},
                        "LogConfig": {"Type": "none"},
                        "AutoRemove": False,
                        "Tmpfs": {
                            "/work": self.module._tmpfs({"profile": self.module._profile()})[
                                "/work"
                            ],
                            "/tmp": "rw,nosuid,nodev,noexec,size=67108864,mode=1777",
                        },
                    },
                    "Mounts": [
                        {
                            "Type": "bind",
                            "Source": str(path),
                            "Destination": destination,
                            "RW": destination == "/output",
                        }
                        for destination, path in self.mounts.items()
                    ],
                }
            )
            inspected = json.loads(value)
            self.inspect_mutation(inspected)
            value = json.dumps(inspected)
        return subprocess.CompletedProcess(command, 0, value, "")


@pytest.fixture
def setup_backend(tmp_path, monkeypatch):
    module = backend()
    fake = DockerBoundary(module, monkeypatch)
    lock = {
        "version": 1,
        "image_id": IMAGE,
        "base_image": "docker.io/library/python@sha256:" + "3" * 64,
        "platform": "linux/amd64",
        "python": "3.13.5",
        "pytest": "9.1.1",
        "dependencies": {
            "pytest": "9.1.1",
            "iniconfig": "2.1.0",
            "packaging": "25.0",
            "pluggy": "1.6.0",
            "pygments": "2.19.2",
        },
        "profile": module._profile(),
        "harness_hashes": module._harness_hashes(),
    }
    lock_path = tmp_path / "environment-lock.json"
    write_json(lock_path, lock)
    check_path = tmp_path / "environment-check.json"
    write_json(
        check_path,
        {
            "version": 1,
            "status": "environment_verified",
            "lock_hash": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            "image_id": IMAGE,
            "checks": {
                key: True
                for key in (
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
            },
            "safety_stage": {
                "passed": True,
                "status": "passed",
                "container_id": CID,
                "cleanup_errors": [],
                "identity": {
                    "environment_hash": hashlib.sha256(lock_path.read_bytes()).hexdigest()
                },
            },
            "timeout_stage": {
                "passed": False,
                "status": "timeout",
                "container_id": "4" * 64,
                "cleanup_errors": [],
                "identity": {
                    "environment_hash": hashlib.sha256(lock_path.read_bytes()).hexdigest()
                },
            },
        },
    )
    repo = tmp_path / "仓库 with spaces"
    repo.mkdir()
    (repo / "test_owned.py").write_text("def test_owned(): assert True\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    return module, fake, lock_path, repo, tmp_path / "stage.log"


def test_missing_backend_has_concrete_verified_runner_interface():
    module = backend()
    assert callable(module.DockerTestRunner.assert_environment_verified)


def test_docker_host_is_a_global_option_before_each_subcommand(setup_backend):
    module, fake, lock, repo, output = setup_backend
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["passed"] is True
    assert fake.raw_commands[0][:2] == ["docker", "context"]
    assert all(
        command[:2] == ["docker", "--host=" + fake.host] for command in fake.raw_commands[1:]
    )


def test_cli_preparation_network_opt_in_forwards_only_http_proxy_family(monkeypatch):
    module = backend()
    fake = DockerBoundary(module, monkeypatch)
    monkeypatch.setattr(
        module.os,
        "environ",
        {
            "PATH": "owned-path",
            "http_proxy": "http://proxy.test:8080",
            "HTTPS_PROXY": "http://secure-proxy.test:8443",
            "No_Proxy": "localhost,127.0.0.1",
            "ALL_PROXY": "socks5://forbidden.test:1080",
            "DEEPSEEK_API_KEY": "forbidden-secret",
            "DOCKER_CONFIG": "forbidden-docker-override",
        },
    )

    module._cli(["version"], preparation_network=True)

    assert fake.calls[-1][1] == {
        "PATH": "owned-path",
        "http_proxy": "http://proxy.test:8080",
        "HTTPS_PROXY": "http://secure-proxy.test:8443",
        "No_Proxy": "localhost,127.0.0.1",
    }


def test_cli_default_scrubs_host_proxy_and_secret_environment(monkeypatch):
    module = backend()
    fake = DockerBoundary(module, monkeypatch)
    monkeypatch.setattr(
        module.os,
        "environ",
        {
            "PATH": "owned-path",
            "HTTP_PROXY": "http://proxy.test:8080",
            "HTTPS_PROXY": "http://secure-proxy.test:8443",
            "NO_PROXY": "localhost,127.0.0.1",
            "ALL_PROXY": "socks5://forbidden.test:1080",
            "DEEPSEEK_API_KEY": "forbidden-secret",
        },
    )

    module._cli(["version"])

    assert fake.calls[-1][1] == {"PATH": "owned-path"}


def test_release_metadata_retries_transient_ssl_eof_and_records_attempts(monkeypatch):
    from benchmarks.evaluation import docker_environment

    clock = MetadataClock()
    calls = []

    def open_metadata(url, **kwargs):
        name = metadata_package(url)
        calls.append((name, kwargs["timeout"]))
        if name == "pytest" and len([call for call in calls if call[0] == name]) == 1:
            raise urllib.error.URLError(ssl.SSLEOFError(8, "owned transient EOF"))
        return metadata_response(name)

    monkeypatch.setattr(docker_environment.urllib.request, "urlopen", open_metadata)
    monkeypatch.setattr(docker_environment, "time", clock, raising=False)

    records = docker_environment._release_metadata()

    assert records["pytest"]["sha256"] == RELEASES["pytest"][1]
    assert records["pytest"]["attempts"] == 2
    assert records["pytest"]["transient_errors"] == ["SSLEOFError"]
    assert all(records[name]["attempts"] == 1 for name in RELEASES if name != "pytest")
    assert all(records[name]["transient_errors"] == [] for name in RELEASES if name != "pytest")
    assert clock.sleeps == [0.25]


def test_release_metadata_exhausts_three_transient_ssl_eof_attempts(monkeypatch):
    from benchmarks.evaluation import docker_environment

    clock = MetadataClock()
    calls = []

    def fail_metadata(url, **kwargs):
        calls.append((url, kwargs["timeout"]))
        raise urllib.error.URLError(ssl.SSLEOFError(8, "owned transient EOF"))

    monkeypatch.setattr(docker_environment.urllib.request, "urlopen", fail_metadata)
    monkeypatch.setattr(docker_environment, "time", clock, raising=False)

    with pytest.raises(
        OSError,
        match=(
            r"pytest .*https://pypi\.org/pypi/pytest/9\.1\.1/json.*"
            r"3 attempts.*SSLEOFError"
        ),
    ):
        docker_environment._release_metadata()

    assert len(calls) == 3
    assert [timeout for _url, timeout in calls] == [30.0, 29.75, 29.25]
    assert clock.sleeps == [0.25, 0.5]


@pytest.mark.parametrize(
    "problem,exception",
    [
        ("certificate", urllib.error.URLError),
        ("http_4xx", urllib.error.HTTPError),
        ("malformed_json", json.JSONDecodeError),
        ("hash_mismatch", ValueError),
    ],
)
def test_release_metadata_does_not_retry_nontransient_failures(monkeypatch, problem, exception):
    from benchmarks.evaluation import docker_environment

    clock = MetadataClock()
    calls = []

    def fail_metadata(url, **kwargs):
        name = metadata_package(url)
        calls.append((url, kwargs["timeout"]))
        if problem == "certificate":
            raise urllib.error.URLError(
                ssl.SSLCertVerificationError(1, "owned certificate rejection")
            )
        if problem == "http_4xx":
            raise urllib.error.HTTPError(url, 404, "owned not found", None, None)
        if problem == "malformed_json":
            return io.StringIO("{not-json")
        return metadata_response(name, digest="0" * 64)

    monkeypatch.setattr(docker_environment.urllib.request, "urlopen", fail_metadata)
    monkeypatch.setattr(docker_environment, "time", clock, raising=False)

    with pytest.raises(exception):
        docker_environment._release_metadata()

    assert len(calls) == 1
    assert clock.sleeps == []


def test_release_metadata_retry_deadline_is_not_reset(monkeypatch):
    from benchmarks.evaluation import docker_environment

    clock = MetadataClock()
    calls = []
    durations = iter((20.0, 9.75))

    def slow_failure(url, **kwargs):
        calls.append((url, kwargs["timeout"]))
        clock.now += next(durations)
        raise urllib.error.URLError(ssl.SSLEOFError(8, "owned transient EOF"))

    monkeypatch.setattr(docker_environment.urllib.request, "urlopen", slow_failure)
    monkeypatch.setattr(docker_environment, "time", clock, raising=False)

    with pytest.raises(OSError, match=r"after 2 attempts"):
        docker_environment._release_metadata()

    assert [timeout for _url, timeout in calls] == [30.0, 9.75]
    assert clock.sleeps == [0.25]
    assert clock.now == 30.0


def test_release_metadata_rejects_valid_response_that_finishes_after_deadline(monkeypatch):
    from benchmarks.evaluation import docker_environment

    clock = MetadataClock()
    calls = []

    class LateResponse(io.StringIO):
        def read(self, *args, **kwargs):
            value = super().read(*args, **kwargs)
            clock.now = 30.01
            return value

    def slow_valid_metadata(url, **kwargs):
        name = metadata_package(url)
        calls.append((url, kwargs["timeout"]))
        return LateResponse(metadata_response(name).getvalue())

    monkeypatch.setattr(docker_environment.urllib.request, "urlopen", slow_valid_metadata)
    monkeypatch.setattr(docker_environment, "time", clock)

    with pytest.raises(
        OSError,
        match=(
            r"pytest .*https://pypi\.org/pypi/pytest/9\.1\.1/json.*"
            r"1 attempts.*URLBudgetExpired"
        ),
    ):
        docker_environment._release_metadata()

    assert calls == [("https://pypi.org/pypi/pytest/9.1.1/json", 30.0)]
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "security_options",
    [
        None,
        [],
        ["name=seccomp,profile=unconfined"],
        ["name=apparmor"],
        ["name=seccomp,profile=builtin", "name=seccomp,profile=unconfined"],
    ],
)
def test_engine_without_builtin_seccomp_is_rejected_before_create(setup_backend, security_options):
    module, fake, lock, repo, output = setup_backend
    fake.security_options = security_options
    with pytest.raises(ValueError, match="seccomp"):
        module._engine()
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["status"] == "environment_error"
    assert not any(c[1] == "create" for c in fake.commands)


@pytest.mark.parametrize("status", ["Seccomp:\t0\n", "Seccomp:\t1\n", "Name:\tpython\n"])
def test_owned_seccomp_probe_rejects_inactive_filter(monkeypatch, status):
    from benchmarks.docker import environment_probe

    monkeypatch.setattr(
        environment_probe,
        "Path",
        lambda name: (
            SimpleNamespace(read_text=lambda **kwargs: status)
            if name == "/proc/self/status"
            else None
        ),
    )
    with pytest.raises(AssertionError):
        environment_probe.test_seccomp_active()


def test_owned_seccomp_probe_accepts_active_filter(monkeypatch):
    from benchmarks.docker import environment_probe

    monkeypatch.setattr(
        environment_probe,
        "Path",
        lambda name: (
            SimpleNamespace(read_text=lambda **kwargs: "Name:\tpython\nSeccomp:\t2\n")
            if name == "/proc/self/status"
            else None
        ),
    )
    environment_probe.test_seccomp_active()


def test_secure_stage_uses_dedicated_mounts_and_locked_image(setup_backend, monkeypatch):
    module, fake, lock, repo, output = setup_backend
    monkeypatch.setenv("DEEPSEEK_API_KEY", "worthless-owned-sentinel")
    result = module.DockerTestRunner(lock)(
        repo, ("test_owned.py",), output, 10, ("test_owned.py::test_owned",)
    )
    assert result["passed"] is True
    assert result["outcomes"] == {"test_owned.py::test_owned": "passed"}
    assert output.read_text("utf-8") == "owned pass\n"
    command = next(c for c in fake.commands if c[1] == "create")
    for argument in (
        "--pull=never",
        "--network=none",
        "--read-only",
        "--user=" + module._profile()["user"],
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--cpus=2",
        "--memory=2147483648",
        "--memory-swap=2147483648",
        "--pids-limit=128",
        "--restart=no",
        "--log-driver=none",
    ):
        assert argument in command
    assert "--tmpfs=/work:" + module._tmpfs({"profile": module._profile()})["/work"] in command
    assert "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=67108864,mode=1777" in command
    assert command[-1] == IMAGE
    assert not any(
        token in " ".join(command)
        for token in (
            "--privileged",
            "network=host",
            "pid=host",
            "docker.sock",
            "DEEPSEEK",
            "seccomp=unconfined",
        )
    )
    input_arg = next(a for a in command if "dst=/input" in a)
    assert input_arg.endswith(",readonly")
    assert fake.mounts["/input"] != repo
    assert (fake.mounts["/input"] / "repo/test_owned.py").read_bytes() == (
        repo / "test_owned.py"
    ).read_bytes()
    for action in ("start", "wait", "stop", "rm", "inspect"):
        assert any(c[1] == action and c[-1] == CID for c in fake.commands)
    assert result["container_id"] == CID
    assert result["cleanup_errors"] == []


@pytest.mark.parametrize("exit_code", [2, 125, 137, -1, 1])
def test_entry_exit_cannot_be_overruled_by_success_json(setup_backend, exit_code):
    module, fake, lock, repo, output = setup_backend
    fake.exit_code = exit_code
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["passed"] is False
    assert result["status"] in {"environment_error", "grader_error"}


@pytest.mark.parametrize("problem", ["start", "wait", "inspect", "oom", "stop", "rm"])
def test_daemon_failures_always_cleanup_exact_container(setup_backend, problem):
    module, fake, lock, repo, output = setup_backend
    fake.problem = problem
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["passed"] is False
    assert any(c[1] == "stop" and c[-1] == CID for c in fake.commands)
    assert any(c[1] == "rm" and c[-1] == CID for c in fake.commands)
    assert not any(c[1] in {"run", "prune", "build", "pull"} for c in fake.commands)
    if problem in {"stop", "rm"}:
        assert result["cleanup_errors"]


@pytest.mark.parametrize("interruption", ["timeout", "keyboard"])
def test_timeout_and_keyboard_interrupt_stop_recorded_container(
    setup_backend, monkeypatch, interruption
):
    module, fake, lock, repo, output = setup_backend
    original = fake.run
    tick = [0]

    def interrupt(command, **kwargs):
        if docker_action(command) == "wait":
            if interruption == "keyboard":
                raise KeyboardInterrupt
            tick[0] += 2
            raise subprocess.TimeoutExpired(command, 1)
        return original(command, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", interrupt)
    monkeypatch.setattr(module.time, "monotonic", lambda: tick[0])
    if interruption == "keyboard":
        with pytest.raises(KeyboardInterrupt):
            module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 1)
    else:
        result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 1)
        assert result["status"] == "timeout"
    assert any(c[1] == "stop" and c[-1] == CID for c in fake.commands)
    assert any(c[1] == "rm" and c[-1] == CID for c in fake.commands)


@pytest.mark.parametrize("problem", ["oversize", "extra", "stale", "missing", "symlink"])
def test_unsafe_or_incomplete_output_never_passes(setup_backend, problem, monkeypatch):
    module, fake, lock, repo, output = setup_backend

    def mutate(folder, result):
        if problem == "oversize":
            with (folder / "pytest.log").open("r+b") as stream:
                stream.truncate(16 * 1024 * 1024 + 1)
        elif problem == "extra":
            (folder / "untrusted.py").write_text("raise AssertionError", encoding="utf-8")
        elif problem == "stale":
            result["stage_id"] = "other-stage"
            write_json(folder / "result.json", result)
        elif problem == "missing":
            (folder / "probe.json").unlink()
        else:
            original = module.protocol.is_link
            monkeypatch.setattr(
                module.protocol, "is_link", lambda p: p.name == "result.json" or original(p)
            )

    fake.mutate_output = mutate
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["passed"] is False
    assert result["status"] == "grader_error"
    assert any(c[1] == "stop" and c[-1] == CID for c in fake.commands)


@pytest.mark.parametrize(
    "problem", ["lock_modified", "check_missing", "image_tag", "harness", "profile"]
)
def test_unverified_or_changed_environment_is_rejected_before_create(setup_backend, problem):
    module, fake, lock_path, _repo, _output = setup_backend
    lock = json.loads(lock_path.read_text("utf-8"))
    if problem == "check_missing":
        lock_path.with_name("environment-check.json").unlink()
    else:
        if problem == "image_tag":
            lock["image_id"] = "python:latest"
        elif problem == "harness":
            lock["harness_hashes"]["container_entry.py"] = "0" * 64
        elif problem == "profile":
            lock["profile"]["network"] = "host"
        else:
            lock["python"] = "3.12.0"
        write_json(lock_path, lock)
    with pytest.raises(ValueError):
        module.DockerTestRunner(lock_path).assert_environment_verified()
    assert not any(c[1] == "create" for c in fake.commands)


def test_existing_output_is_preserved_without_starting_container(setup_backend):
    module, fake, lock, repo, output = setup_backend
    output.write_text("old evidence", encoding="utf-8")
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["passed"] is False
    assert output.read_text("utf-8") == "old evidence"
    assert not any(c[1] == "create" for c in fake.commands)


def test_existing_artifact_directory_is_not_cleaned_up(setup_backend):
    module, fake, lock, repo, output = setup_backend
    artifacts = output.with_name(output.name + ".docker")
    artifacts.mkdir()
    (artifacts / "container.cid").write_text(CID, encoding="ascii")
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["passed"] is False
    assert not any(c[1] in {"stop", "rm"} for c in fake.commands)
    assert not (artifacts / "execution.json").exists()


def test_prepare_failure_writes_no_verified_lock(tmp_path, monkeypatch):
    module = backend()

    def missing(command, **kwargs):
        raise FileNotFoundError("owned Docker unavailable")

    monkeypatch.setattr(module.subprocess, "run", missing)
    result = module.prepare_environment(tmp_path / "preparation")
    assert result["status"] == "environment_error"
    assert not (tmp_path / "preparation/environment-lock.json").exists()
    assert not (tmp_path / "preparation/environment-check.json").exists()


def test_check_failure_cannot_write_environment_verified(setup_backend, monkeypatch):
    module, fake, lock, _repo, _output = setup_backend
    evidence = lock.with_name("environment-check.json")
    evidence.unlink()
    fake.problem = "start"
    result = module.check_environment(lock, evidence)
    assert result["status"] == "environment_error"
    assert json.loads(evidence.read_text("utf-8"))["status"] != "environment_verified"


def test_check_refuses_evidence_path_runner_would_not_consume(setup_backend):
    module, fake, lock, _repo, _output = setup_backend
    evidence = lock.parent / "other-check.json"
    result = module.check_environment(lock, evidence)
    assert result["status"] == "environment_error"
    assert not evidence.exists()
    assert not any(c[1] == "create" for c in fake.commands)


@pytest.mark.parametrize("where", ["create", "start"])
@pytest.mark.parametrize("interruption", [OSError, KeyboardInterrupt])
def test_client_failure_after_side_effect_still_cleans_recorded_id(
    setup_backend, monkeypatch, where, interruption
):
    module, fake, lock, repo, output = setup_backend
    original = fake.run

    def fail(command, **kwargs):
        completed = original(command, **kwargs)
        if docker_action(command) == where:
            raise interruption("owned interrupted client")
        return completed

    monkeypatch.setattr(module.subprocess, "run", fail)
    if interruption is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    else:
        assert not module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)["passed"]
    assert any(c[1] == "stop" and c[-1] == CID for c in fake.commands)
    assert any(c[1] == "rm" and c[-1] == CID for c in fake.commands)


@pytest.mark.parametrize("change", ["memory", "privileged", "mount_source", "extra_volume", "root"])
def test_actual_inspect_profile_mismatch_prevents_start(setup_backend, change):
    module, fake, lock, repo, output = setup_backend

    def mutate(value):
        if change == "memory":
            value["HostConfig"]["Memory"] = 0
        elif change == "privileged":
            value["HostConfig"]["Privileged"] = True
        elif change == "mount_source":
            value["Mounts"][0]["Source"] = "/entire-user-directory"
        elif change == "extra_volume":
            value["Mounts"].append(
                {"Type": "volume", "Source": "/secret", "Destination": "/secret", "RW": True}
            )
        else:
            value["Config"]["User"] = "0:0"

    fake.inspect_mutation = mutate
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert not result["passed"]
    assert not fake.started
    assert any(c[1] == "rm" for c in fake.commands)


def test_malformed_inspect_does_not_skip_remove(setup_backend, monkeypatch):
    module, fake, lock, repo, output = setup_backend
    original = fake.run

    def malformed(command, **kwargs):
        completed = original(command, **kwargs)
        if docker_action(command) == "inspect":
            completed.stdout = "null"
        return completed

    monkeypatch.setattr(module.subprocess, "run", malformed)
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert not result["passed"]
    assert any(c[1] == "rm" and c[-1] == CID for c in fake.commands)


@pytest.mark.parametrize(
    "host", ["tcp://remote.example:2375", "ssh://remote", "http://localhost:2375"]
)
def test_remote_context_never_creates_container(setup_backend, host):
    module, fake, lock, repo, output = setup_backend
    fake.host = host
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["status"] == "environment_error"
    assert not any(c[1] == "create" for c in fake.commands)


@pytest.mark.parametrize("value", ["not-a-dict", [], {"non_root": True}])
def test_malformed_checks_are_rejected_without_execution(setup_backend, value):
    module, fake, lock, repo, output = setup_backend
    evidence = lock.with_name("environment-check.json")
    data = json.loads(evidence.read_text("utf-8"))
    data["checks"] = value
    write_json(evidence, data)
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["status"] == "environment_error"
    assert not any(c[1] == "create" for c in fake.commands)


def test_check_flags_without_actual_stage_evidence_are_rejected(setup_backend):
    module, fake, lock, repo, output = setup_backend
    evidence = lock.with_name("environment-check.json")
    data = json.loads(evidence.read_text("utf-8"))
    del data["safety_stage"]
    write_json(evidence, data)
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["status"] == "environment_error"
    assert not any(c[1] == "create" for c in fake.commands)


def test_explicit_preparation_builds_only_whitelisted_context(setup_backend, monkeypatch):
    module, fake, lock, _repo, _output = setup_backend
    from benchmarks.evaluation import docker_environment

    monkeypatch.setattr(
        docker_environment, "_release_metadata", lambda: {"owned": "verified-metadata"}
    )
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    proxies = {
        "HTTP_PROXY": "http://proxy.test:8080",
        "HTTPS_PROXY": "http://secure-proxy.test:8443",
        "NO_PROXY": "localhost,127.0.0.1",
    }
    for name, value in {
        **proxies,
        "ALL_PROXY": "socks5://forbidden.test:1080",
        "DEEPSEEK_API_KEY": "forbidden-secret",
    }.items():
        monkeypatch.setenv(name, value)
    destination = lock.parent / "prepared"
    result = module.prepare_environment(destination)
    assert result["status"] == "environment_prepared", result
    assert result["environment_verified"] is False
    assert not (destination / "environment-check.json").exists()
    raw_manifest = next(c for c in fake.commands if c[1] == "buildx")
    assert raw_manifest == [
        "docker",
        "buildx",
        "imagetools",
        "inspect",
        "--raw",
        "docker.io/library/python:3.13.5-slim-bookworm",
    ]
    command = next(c for c in fake.commands if c[1] == "build")
    context = Path(command[-1])
    assert context != module.ROOT
    assert {p.name for p in context.iterdir()} == {
        "Dockerfile",
        "requirements.lock",
        "environment_probe.py",
        "container_entry.py",
        "container_protocol.py",
        "pytest_probe.py",
        "agent_container_protocol.py",
        "agent_pytest_capture.py",
    }
    assert "BASE_IMAGE=docker.io/library/python@sha256:" + "3" * 64 in command
    for invoked, environment in fake.calls:
        proxy_environment = {
            key: value
            for key, value in environment.items()
            if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"}
        }
        if invoked[1] in {"buildx", "build"}:
            assert proxy_environment == proxies
        else:
            assert proxy_environment == {}
        assert "DEEPSEEK_API_KEY" not in environment
    command_text = "\n".join(part for command in fake.commands for part in command)
    assert not any(value in command_text for value in proxies.values())
    prepared = json.loads((destination / "environment-lock.json").read_text("utf-8"))
    assert prepared["image_id"] == IMAGE
    assert "environment_probe.py" in prepared["harness_hashes"]


@pytest.mark.parametrize(
    "manifests",
    [
        [],
        [
            {
                "digest": "not-a-digest",
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ],
        [
            {
                "digest": "sha256:" + "3" * 64,
                "platform": {"os": "linux", "architecture": "amd64"},
            },
            {
                "digest": "sha256:" + "4" * 64,
                "platform": {"os": "linux", "architecture": "amd64"},
            },
        ],
    ],
)
def test_preparation_rejects_invalid_or_nonunique_linux_amd64_digest(
    setup_backend, monkeypatch, manifests
):
    module, fake, lock, _repo, _output = setup_backend
    from benchmarks.evaluation import docker_environment

    monkeypatch.setattr(
        docker_environment, "_release_metadata", lambda: {"owned": "verified-metadata"}
    )
    fake.manifest = {"manifests": manifests}

    result = module.prepare_environment(lock.parent / ("invalid-" + str(len(manifests))))

    assert result["status"] == "environment_error"
    assert result["error"] == "official Python manifest has no unique Linux/amd64 digest"
    assert not any(command[1] == "build" for command in fake.commands)


def test_check_requires_successful_security_and_timeout_stages(setup_backend, monkeypatch):
    module, fake, lock, _repo, _output = setup_backend
    evidence = lock.with_name("environment-check.json")
    evidence.unlink()
    for name, value in {
        "HTTP_PROXY": "http://proxy.test:8080",
        "HTTPS_PROXY": "http://secure-proxy.test:8443",
        "NO_PROXY": "localhost,127.0.0.1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(module.time, "monotonic", lambda: fake.tick)
    result = module.check_environment(lock, evidence)
    assert result["status"] == "environment_verified", result
    assert all(value is True for value in result["checks"].values())
    assert len([c for c in fake.commands if c[1] == "create"]) == 2
    assert not any(c[1] in {"pull", "build"} for c in fake.commands)
    assert all(
        not {key.upper() for key in environment}
        & {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"}
        for _command, environment in fake.calls
    )


def test_linux_host_identity_controls_user_and_work_permissions(tmp_path, monkeypatch):
    module = backend()
    monkeypatch.setattr(
        module, "os", SimpleNamespace(name="posix", getuid=lambda: 12345, getgid=lambda: 23456)
    )
    profile = module._profile()
    command = module._create_command({"image_id": IMAGE, "profile": profile}, tmp_path, "owned")
    assert profile["user"] == "12345:23456"
    assert "--user=12345:23456" in command
    assert "--tmpfs=/work:rw,nosuid,nodev,size=268435456,uid=12345,gid=23456,mode=0700" in command


@pytest.mark.parametrize("uid,gid", [(0, 12345), (12345, 0)])
def test_root_linux_host_identity_is_not_supported(monkeypatch, uid, gid):
    module = backend()
    monkeypatch.setattr(
        module, "os", SimpleNamespace(name="posix", getuid=lambda: uid, getgid=lambda: gid)
    )
    with pytest.raises(ValueError, match="root"):
        module._profile()


@pytest.mark.parametrize("suffix", [",injected", "\ninvalid"])
def test_mount_source_delimiters_never_reach_create(setup_backend, suffix):
    module, fake, lock, repo, output = setup_backend
    result = module.DockerTestRunner(lock)(
        repo, ("test_owned.py",), output.with_name("stage" + suffix), 10
    )
    assert result["passed"] is False
    assert not any(c[1] == "create" for c in fake.commands)


@pytest.mark.parametrize("which", ["environment-lock.json", "environment-check.json"])
def test_hard_linked_environment_evidence_is_rejected(setup_backend, which):
    module, fake, lock, repo, output = setup_backend
    os.link(lock.with_name(which), lock.with_name("duplicate-evidence.json"))
    result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert result["status"] == "environment_error"
    assert not any(c[1] == "create" for c in fake.commands)


def test_timeout_during_start_does_not_verify_environment(setup_backend, monkeypatch):
    module, fake, lock, _repo, _output = setup_backend
    evidence = lock.with_name("environment-check.json")
    evidence.unlink()
    original = fake.run

    def startup_timeout(command, **kwargs):
        if docker_action(command) == "start":
            request = json.loads((fake.mounts["/input"] / "request.json").read_text("utf-8"))
            if request["paths"] == ["test_timeout.py"]:
                raise subprocess.TimeoutExpired(command, 30)
        return original(command, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", startup_timeout)
    result = module.check_environment(lock, evidence)
    assert result["status"] == "environment_error"
    assert result["checks"].get("timeout_stopped") is not True


def test_interrupt_during_cleanup_still_attempts_remove(setup_backend, monkeypatch):
    module, fake, lock, repo, output = setup_backend
    original = fake.run

    def interrupt_stop(command, **kwargs):
        completed = original(command, **kwargs)
        if docker_action(command) == "stop":
            raise KeyboardInterrupt
        return completed

    monkeypatch.setattr(module.subprocess, "run", interrupt_stop)
    with pytest.raises(KeyboardInterrupt):
        module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    assert any(c[1] == "rm" and c[-1] == CID for c in fake.commands)


@pytest.mark.parametrize("interruption", [False, True])
def test_stop_exhausting_its_budget_still_attempts_exact_id_removal(
    setup_backend, monkeypatch, interruption
):
    module, fake, lock, repo, output = setup_backend
    original = fake.run

    def slow_stop(command, **kwargs):
        if docker_action(command) == "stop":
            fake.tick += kwargs["timeout"]
            if interruption:
                raise KeyboardInterrupt
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return original(command, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", slow_stop)
    monkeypatch.setattr(module.time, "monotonic", lambda: fake.tick)
    if interruption:
        with pytest.raises(KeyboardInterrupt):
            module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
    else:
        result = module.DockerTestRunner(lock)(repo, ("test_owned.py",), output, 10)
        assert result["passed"] is False
        assert result["cleanup_errors"]
    assert fake.tick <= 30
    assert any(c[1] == "rm" and c[-1] == CID for c in fake.commands)


def test_agent_stage_uses_v2_and_precise_public_node(setup_backend):
    module, fake, lock, repo, output = setup_backend
    target = "test_owned.py::test_owned"

    result = module.DockerTestRunner(lock).run_agent(
        repo, ("test_owned.py",), output, 10, target=target
    )

    assert result["passed"] is True, result
    assert result["identity"]["version"] == 2
    request = json.loads((Path(result["artifacts"]) / "input/request.json").read_text("utf-8"))
    assert request["mode"] == "agent"
    assert request["target"] == target
    assert result["probe"]["collected"] == [target]
    assert result["cleanup_errors"] == []
    assert any(c[1] == "rm" and c[-1] == CID for c in fake.commands)


def test_agent_collection_failure_preserves_pytest_two_without_transport_error(setup_backend):
    module, fake, lock, repo, output = setup_backend
    fake.exit_code = 1  # Valid failed stage, distinct from contained pytest's exit2.

    def collection_failure(output_dir, result):
        probe = result["probe"]
        probe.update(
            exit_code=2,
            collected=[],
            reports=[],
            collection_errors=[{"nodeid": "test_owned.py", "outcome": "failed"}],
            failures=[
                {
                    "node_id": "test_owned.py",
                    "phase": "collection",
                    "outcome": "failed",
                    "exception_type": "SyntaxError",
                    "summary": "invalid syntax",
                    "traceback": "/work/test_owned.py:1: SyntaxError",
                    "duration_ms": 0,
                }
            ],
        )
        result["pytest_returncode"] = 2
        write_json(output_dir / "probe.json", probe)
        write_json(output_dir / "result.json", result)

    fake.mutate_output = collection_failure
    result = module.DockerTestRunner(lock).run_agent(repo, ("test_owned.py",), output, 10)

    assert result["status"] == "failed", result
    assert result["returncode"] == 2
    assert result["failures"][0]["exception_type"] == "SyntaxError"
    assert result["cleanup_errors"] == []


@pytest.mark.parametrize("problem", ["create", "oom", "rm"])
def test_agent_stage_never_accepts_daemon_resource_or_cleanup_error(setup_backend, problem):
    module, fake, lock, repo, output = setup_backend
    fake.problem = problem

    result = module.DockerTestRunner(lock).run_agent(repo, ("test_owned.py",), output, 10)

    assert result["passed"] is False
    assert result["status"] in {"environment_error", "grader_error"}
