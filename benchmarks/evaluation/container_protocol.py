"""Data-only container protocol. No Docker, model, or production-Agent imports.

Inventories cover every staged file, including explicit tests in directories
normally excluded by the host grader. The container gets a prefiltered staging
tree; this module must not silently filter it again.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path, PureWindowsPath

MAX_INPUT_FILE = 8 * 1024 * 1024
MAX_INPUT_TOTAL = 20 * 1024 * 1024
MAX_INPUT_FILES = 2000
MAX_OUTPUT_FILE = 16 * 1024 * 1024
MAX_OUTPUT_TOTAL = 64 * 1024 * 1024
OUTPUT_NAMES = frozenset(
    {"result.json", "probe.json", "integrity.json", "pytest.log", "error.json"}
)
IDENTITY = ("version", "run_id", "stage_id", "input_hash", "environment_hash")
REQUEST_FIELDS = frozenset((*IDENTITY, "paths", "required", "timeout"))
DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"{p}{n}" for p in ("COM", "LPT") for n in "123456789¹²³"),
}


class ProtocolError(ValueError):
    """Missing, unsafe or contradictory stage evidence."""


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def safe_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or value.startswith(("/", "-"))
        or PureWindowsPath(value).drive
        or any(c in value for c in '\\:*?"<>|')
        or any(ord(c) < 32 for c in value)
        or any(
            p in {"", ".", ".."}
            or p.endswith((" ", "."))
            or p.split(".")[0].upper() in DEVICE_NAMES
            for p in value.split("/")
        )
    ):
        raise ProtocolError("unsafe relative stage path")
    return value


def checked_root(root: Path) -> None:
    if any(is_link(p) for p in (root, *root.parents)):
        raise ProtocolError("linked stage root")
    if not root.is_dir():
        raise ProtocolError("stage root is missing")


def _digest(value) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ProtocolError("invalid SHA-256 digest")


def validate_inventory(value: dict) -> dict:
    if not isinstance(value, dict) or not 0 < len(value) <= MAX_INPUT_FILES:
        raise ProtocolError("invalid inventory")
    seen = set()
    for name, digest in value.items():
        safe_path(name)
        _digest(digest)
        if name.casefold() in seen:
            raise ProtocolError("inventory path collision")
        seen.add(name.casefold())
    return value


def inventory_hash(inventory: dict) -> str:
    validate_inventory(inventory)
    data = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def input_inventory(root: Path, explicit_paths: tuple[str, ...]) -> dict[str, str]:
    checked_root(root)
    for name in explicit_paths:
        safe_path(name)
    inventory = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if is_link(path):
            raise ProtocolError("linked input file or directory")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ProtocolError("non-regular or hard-linked input")
        name = safe_path(path.relative_to(root).as_posix())
        limit = min(MAX_INPUT_FILE, MAX_INPUT_TOTAL - total)
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ProtocolError("input size limit exceeded")
        total += len(data)
        inventory[name] = hashlib.sha256(data).hexdigest()
        if len(inventory) > MAX_INPUT_FILES:
            raise ProtocolError("input file count exceeded")
    validate_inventory(inventory)
    if not set(explicit_paths) <= inventory.keys():
        raise ProtocolError("explicit test file is missing")
    return inventory


def validate_request(request: dict) -> dict:
    if isinstance(request, dict) and request.get("version") == 2:
        from .agent_container_protocol import validate_agent_request

        return validate_agent_request(request)
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ProtocolError("invalid request fields")
    if type(request["version"]) is not int or request["version"] != 1:
        raise ProtocolError("invalid request version")
    for key in ("run_id", "stage_id"):
        if not isinstance(request[key], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", request[key]
        ):
            raise ProtocolError("invalid stage identity")
    for key in ("input_hash", "environment_hash"):
        _digest(request[key])
    if type(request["timeout"]) is not int or not 0 < request["timeout"] <= 120:
        raise ProtocolError("invalid stage timeout")
    for key in ("paths", "required"):
        items = request[key]
        if (
            not isinstance(items, list)
            or len(items) > 10000
            or any(
                not isinstance(v, str) or len(v) > 4096 or any(ord(c) < 32 for c in v)
                for v in items
            )
            or len(set(items)) != len(items)
        ):
            raise ProtocolError("invalid or duplicate stage selection")
    if not request["paths"]:
        raise ProtocolError("empty stage selection")
    for name in request["paths"]:
        safe_path(name)
    for node in request["required"]:
        file, separator, suffix = node.partition("::")
        if not separator or not suffix or file not in request["paths"]:
            raise ProtocolError("required node is outside selected paths")
    return request


def _probe_outcomes(probe: dict, request: dict) -> dict:
    if (
        not isinstance(probe, dict)
        or type(probe.get("version")) is not int
        or probe["version"] != 1
        or probe.get("finished") is not True
        or type(probe.get("exit_code")) is not int
        or not isinstance(probe.get("collected"), list)
        or not isinstance(probe.get("reports"), list)
        or not isinstance(probe.get("collection_errors"), list)
    ):
        raise ProtocolError("invalid or unfinished probe")
    nodes = probe["collected"]
    if any(
        not isinstance(n, str) or len(n) > 4096 or n.partition("::")[0] not in request["paths"]
        for n in nodes
    ):
        raise ProtocolError("probe node is outside requested paths")
    if len(set(nodes)) != len(nodes):
        raise ProtocolError("duplicate probe node")
    phases = {n: {} for n in nodes}
    for row in probe["reports"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("nodeid"), str)
            or row["nodeid"] not in phases
            or row.get("when") not in ("setup", "call", "teardown")
            or row.get("outcome") not in ("passed", "failed", "skipped")
            or type(row.get("wasxfail")) is not bool
            or (
                "exception_type" in row
                and (
                    not isinstance(row["exception_type"], str)
                    or not 0 < len(row["exception_type"]) <= 200
                )
            )
        ):
            raise ProtocolError("invalid probe report")
        if row["when"] in phases[row["nodeid"]]:
            raise ProtocolError("duplicate probe phase")
        phases[row["nodeid"]][row["when"]] = row
    outcomes = {}
    for node, rows in phases.items():
        if any(r["wasxfail"] or r["outcome"] == "skipped" for r in rows.values()):
            outcomes[node] = "skipped"
        elif (
            set(rows) != {"setup", "call", "teardown"}
            or rows["setup"]["outcome"] != "passed"
            or rows["teardown"]["outcome"] != "passed"
        ):
            outcomes[node] = "error"
        else:
            outcomes[node] = rows["call"]["outcome"]
    return outcomes


def validate_stage_result(result: dict, expected: dict) -> dict:
    validate_request(expected)
    if expected["version"] == 2:
        from .agent_container_protocol import validate_agent_result

        return validate_agent_result(result, expected)
    if not isinstance(result, dict) or set(result) != {
        *IDENTITY,
        "pytest_returncode",
        "probe",
        "integrity",
    }:
        raise ProtocolError("invalid stage result fields")
    if type(result["version"]) is not int or any(result[k] != expected[k] for k in IDENTITY):
        raise ProtocolError("stage identity mismatch")
    code = result["pytest_returncode"]
    if type(code) is not int or code not in range(6):
        raise ProtocolError("invalid pytest returncode")
    integrity = result["integrity"]
    if not isinstance(integrity, dict) or set(integrity) != {"before", "after", "unchanged"}:
        raise ProtocolError("invalid integrity fields")
    before, after = integrity["before"], integrity["after"]
    validate_inventory(before)
    # Empty after inventory legitimately means all files were deleted.
    if after != {}:
        validate_inventory(after)
    if inventory_hash(before) != expected["input_hash"]:
        raise ProtocolError("input inventory mismatch")
    if type(integrity["unchanged"]) is not bool or integrity["unchanged"] != (before == after):
        raise ProtocolError("contradictory integrity claim")
    probe = result["probe"]
    outcomes = _probe_outcomes(probe, expected)
    if probe["exit_code"] != code:
        raise ProtocolError("pytest exit code mismatch")
    status = "failed"
    if not integrity["unchanged"]:
        status = "patch_rejected"
    elif (
        not outcomes
        or probe["collection_errors"]
        or code not in (0, 1)
        or not set(expected["required"]) <= outcomes.keys()
        or "error" in outcomes.values()
        or (code == 0 and "failed" in outcomes.values())
        or (code == 1 and "failed" not in outcomes.values())
    ):
        status = "grader_error"
    elif code == 0 and all(v == "passed" for v in outcomes.values()):
        status = "passed"
    return {
        "passed": status == "passed",
        "status": status,
        "returncode": code,
        "outcomes": outcomes,
        "required": list(expected["required"]),
        "probe": probe,
        "integrity": integrity,
        "assertion_failures": sorted(
            row["nodeid"]
            for row in probe["reports"]
            if row["when"] == "call"
            and row["outcome"] == "failed"
            and row.get("exception_type") == "AssertionError"
            and outcomes.get(row["nodeid"]) == "failed"
        ),
        "identity": {k: result[k] for k in IDENTITY},
    }


def output_files(root: Path) -> dict[str, Path]:
    checked_root(root)
    result = {}
    total = 0
    for path in root.iterdir():
        if path.name not in OUTPUT_NAMES or is_link(path):
            raise ProtocolError("unexpected or linked output")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ProtocolError("output must be a regular unlinked file")
        total += info.st_size
        if info.st_size > MAX_OUTPUT_FILE or total > MAX_OUTPUT_TOTAL:
            raise ProtocolError("output size limit exceeded")
        result[path.name] = path
    if len(result) > 8:
        raise ProtocolError("output count exceeded")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    if is_link(path) or not stat.S_ISREG(path.lstat().st_mode):
        raise ProtocolError("JSON evidence must be a regular file")
    with path.open("rb") as stream:
        data = stream.read(MAX_OUTPUT_FILE + 1)
    if len(data) > MAX_OUTPUT_FILE:
        raise ProtocolError("JSON evidence exceeds size limit")
    try:
        value = json.loads(data, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON evidence") from exc
    if not isinstance(value, dict):
        raise ProtocolError("JSON evidence must be an object")
    return value


def read_stage_output(root: Path, expected: dict) -> dict:
    files = output_files(root)
    if set(files) != {"result.json", "probe.json", "integrity.json", "pytest.log"}:
        raise ProtocolError("incomplete stage evidence")
    result = read_json(files["result.json"])
    if result.get("probe") != read_json(files["probe.json"]) or result.get(
        "integrity"
    ) != read_json(files["integrity.json"]):
        raise ProtocolError("separate evidence disagrees with stage result")
    return validate_stage_result(result, expected)
