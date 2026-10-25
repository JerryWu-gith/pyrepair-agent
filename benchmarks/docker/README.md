# Open-source pilot Docker backend

Current state (2026-10-22): backend, independent grader/CLI integration and the
Agent's own test adapter are implemented and independently reviewed. The local
Windows Docker Desktop 4.96.0 / Linux-amd64 environment passed all nine owned
safety/timeout checks, five explicitly selected Docker integration tests and
two-task independent grader recalibration. The final prepared environment is
`benchmarks/results/opensource/environment-agent-v2-fixed-20261022-9e13c980/`
(local, ignored), image
`sha256:5100ada08d532bb34b324a27f0981ba1572a83e5790490f36777139909829e21`.
Recalibration is under `benchmarks/results/opensource/av2-20261022-e57c894b/`:
more-itertools r1 and boltons r2 are both valid. Earlier environments, invalid
runs and adapter failures are retained, not overwritten or merged into scores.
No real model was called in this phase. See
[adapter evidence and limits](../../docs/agent-docker-adapter-offline.md) and
[historical pilot calibration](../../docs/opensource-pilot-offline.md).

## Interfaces and evidence

```python
from pathlib import Path
from benchmarks.evaluation.docker_runner import (
    DockerTestRunner, prepare_environment, check_environment,
)

# Explicit image/network authorization is required before calling this.
prepared = prepare_environment(Path("fresh-environment-directory"))

# Use an already prepared full image ID. No implicit build, pull, or install.
lock = Path("fresh-environment-directory/environment-lock.json")
checked = check_environment(lock, lock.with_name("environment-check.json"))
runner = DockerTestRunner(lock)
runner.assert_environment_verified()  # revalidates evidence, endpoint and image
result = runner(repo, ("test_owned.py",), Path("new-stage.log"), 120, required=())
```

`prepare_environment` requires a **new directory**. It checks official PyPI
metadata against the wheel lock; resolves the official Python 3.13.5
Linux/amd64 manifest digest; builds a newly created eight-file context; inspects
the resulting full image ID; and runs an owned exact-version probe. Preparation
is not safety verification. The build has a 600-second client deadline. Failed
preparation retains evidence and never writes a usable final lock. Official PyPI
metadata GETs alone may retry typed transient SSL EOF at most three times within
the original per-URL budget; late successful responses are rejected after reading,
not hard-cancelled. Certificate/HTTP/JSON/hash errors, builds and test stages are
not automatically retried.

`check_environment` requires a **new JSON file at exactly
`lock.parent/environment-check.json`**. Its exclusive sibling
`environment-check.json.docker-check/` retains safety and timeout stages. An
existing file/directory is never replaced. To recheck, copy the lock into a new
directory and check there. Verification requires actual owned tests for
non-root execution, read-only root/input, absence of a worthless sentinel and
API-key variables, external-network blocking with loopback availability,
an active seccomp filter (`Seccomp: 2` in `/proc/self/status`), exact runtime
versions, enforced inspect settings, and a *started* container
timing out and being stopped/removed. A startup timeout cannot satisfy this
last requirement. Mocked tests do not establish these real properties.

The offline `validate` and `grade` commands accept the explicit pair
`--backend docker --environment-lock PATH`. They require the runner's concrete
`assert_environment_verified()` check before creating output. It validates ordinary unlinked lock/check
files, hashes, versions, profile, harness source hashes, probe-stage evidence,
local Linux/amd64 engine, and exact locally present image. It does not trust an
`is_sandbox` flag. Lock or harness changes require new preparation/check evidence.
Every calibration and acceptance stage uses the same selected backend.
The evaluation-only DockerAgentTestRunner now converts separately validated
Agent-v2 diagnostic evidence into TestRun and is injected into the Agent's
baseline, target tool and Verifier. Each call uses a fresh filtered public
snapshot and container; the grader-v1 acceptance branch remains strict.
Live opensource repair remains disabled until the fair baseline/frozen run pack
and a separately approved new model budget are ready. Ordinary public CLI
execution still defaults to the original host TestRunner; no general Docker
CLI option or universal sandbox is claimed.
Host-supplied evidence is not a cryptographic attestation against a malicious
host administrator; the project does not claim adversarial-proof execution.

## Boundary and lifecycle

Only local named-pipe/Unix-socket contexts are supported. Remote endpoints,
Windows containers, endpoint/context/config environment overrides, unavailable
images, and unsupported security settings fail closed. No fallback to host,
engine switching, automatic external-test retry, global cleanup, or prune.

Each call creates `<log.name>.docker/` with a new random run/stage identity,
`input/` staging and an empty `output/`. Only those two directories are mounted;
input is read-only. Commas/control characters in mount-source paths are
rejected; Chinese and spaces are supported. All staged files are inventoried,
copied, and checked again before creation. Upstream Python is never imported
or executed by host-side staging.

The security profile is 2 CPU, 2 GiB RAM and total RAM+swap, 128 processes,
read-only root, dropped capabilities, no-new-privileges, daemon-reported builtin
seccomp plus an owned active-filter probe,
private IPC, network=none, no restart, `/work` 256 MiB and `/tmp` 64 MiB tmpfs.
Windows Desktop uses UID:GID 65532:65532. Linux hosts use their current non-root
UID:GID, bound in the lock and inspect checks, so new output directories need
no permission/ACL changes. Root UID or GID is unsupported. Actual Desktop or
Linux mount writability still requires the real probe; no cross-platform
verification is claimed.

A full container ID is recovered from a unique cidfile, recorded before start,
and reused for inspect/start/wait/stop/remove. Any started-stage error or
interruption triggers bounded cleanup of that ID only. An interruption during
cleanup is deferred until removal has been attempted. Stop and inspect reserve
time within the same 30-second cleanup deadline for final force-removal of
the exact recorded ID. Cleanup errors are
retained and prohibit a pass. Old logs/artifact directories are never cleaned.
Startup and cleanup each have a shared 30-second deadline; tests use at most
120 seconds. The supervisor checks outputs at least once per second while
waiting: at most 8 ordinary whitelist files, 16 MiB per file, 64 MiB total.
This is a polling guard, not a hard disk quota. Docker's container log driver
is disabled and it is never attached; pytest's combined stdout/stderr is the
bounded `pytest.log`. Docker client responses are bounded before acceptance.

Outputs are parsed only after stopped-container inspection and removal.
Task 4 validates independent probe/integrity/result agreement, IDs, hashes,
required nodes, and unchanged inputs. OOM/runtime failures, unknown entry
codes, exit-code contradictions, missing evidence and collection errors never
become a passing result. The returned dictionary preserves
`passed/status/returncode/outcomes/required` plus Docker identity and artifacts.
The ordinary log is copied only from a validated stopped stage.

## Dependencies and reproducibility

The lock pins pytest 9.1.1 and its Python 3.13/Linux runtime dependencies:
iniconfig 2.1.0, packaging 25.0, pluggy 1.6.0, Pygments 2.19.2. Exact universal
wheel SHA-256 values were read from the official release JSON endpoints linked
in `requirements.lock`; no packages were installed on the host. Docker installs
only hash-checked binary wheels, never either upstream project's setup/build.

The Dockerfile copies only the trusted entry, common protocol, Agent protocol,
pytest probe, Agent diagnostic capture, environment probe and lock. The build
context additionally contains that Dockerfile: eight files total, not the
project/user directory, upstream trees, `.env`, or keys.
The actual base digest, final image ID and versions must come from a separately
authorized preparation; none is invented or provided as a runnable lock here.

## Tests

Owned tests, no Docker or upstream execution:

```text
python -m pytest tests/test_docker_runner.py -q -m "not live and not docker"
```

Real integration, only after a separately authorized image preparation:

```text
PYREPAIR_DOCKER_ENVIRONMENT_LOCK=<prepared environment-lock.json>
python -m pytest tests/test_agent_docker_integration.py tests/test_docker_integration.py -m docker -q
```

These tests never build/pull, do not skip unavailable prerequisites, and fail
if no prepared lock/daemon exists. The existing safety test copies the lock to
a fresh directory and rechecks it. The four new tests cover owned syntax-error
feedback, a FakeLLM complete repair and two upstream public baseline/reference
executions. Ordinary pytest excludes `docker` by default; deselection is **not**
a successful integration run. The final explicit run was 5 passed in 59.69
seconds, with 14 distinct Agent-stage containers. Independent two-task
baseline/gold/wrong recalibration used the same new environment and separately
passed; neither result is real-model repair performance. Initial collection-only
projects without an executable failed node are not supported repair starts.
