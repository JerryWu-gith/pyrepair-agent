"""Versioned data-only selection of existing upstream tests; never import them."""

from __future__ import annotations

import shutil
from pathlib import Path

from .cases import contained, load_cases, public_files, safe_relative
from .comparison_budget import write_new
from .container_protocol import read_json

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = "regression_opensource_v3.json"
BRIDGE = "tests/test_pyrepair_seekable_regression.py"
UPSTREAM = {
    "SeekableTest": (
        "test_exhaustion_reset",
        "test_partial_reset",
        "test_forward",
        "test_past_end",
        "test_elements",
        "test_maxlen",
        "test_maxlen_zero",
        "test_relative_seek",
        "test_getitem",
        "test_getitem_maxlen",
        "test_passthrough",
        "test_peek_default",
        "test_truthiness",
        "test_simple_peeking",
    ),
    "SequenceViewTests": (
        "test_init",
        "test_update",
        "test_indexing",
        "test_slicing",
        "test_abc_methods",
    ),
}


def _copy_tree(source, destination):
    if source.resolve() == destination.resolve():
        return
    destination.mkdir(parents=True, exist_ok=False)
    for original in public_files(source):
        target = contained(destination, original.relative_to(source).as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)


def build_more_revision(destination: Path) -> Path:
    """Materialize a fresh v3 manifest; old paths in the actual root are reused read-only."""
    destination = Path(destination).absolute()
    manifest = destination / "manifest_opensource_v3.json"
    if manifest.exists() or (destination / DESCRIPTOR).exists():
        raise FileExistsError("layered assets already exist")
    old = load_cases(ROOT / "manifest_opensource_v2.json")
    rows = []
    for case in old:
        row = case.metadata()
        _copy_tree(case.private, destination / case.private_path)
        if case.id == "os_more_seekable_1269":
            row.update(
                revision=2,
                buggy_path="eval_cases/opensource_v2/os_more_seekable_1269/buggy",
                public_description_path="eval_cases/opensource_v2/os_more_seekable_1269/TASK.md",
                visible_tests=["tests/test_pyrepair_repro.py", BRIDGE],
                pass_to_pass=[
                    *case.pass_to_pass,
                    *(
                        f"{BRIDGE}::{cls}::{name}"
                        for cls, names in UPSTREAM.items()
                        for name in names
                    ),
                ],
                origin={
                    **case.origin,
                    "scope": "r2 core: original SeekableTest and SequenceViewTests plus repro; r1 selected files retained in separately reported extended regression. Not all upstream test entry points.",
                },
            )
            _copy_tree(case.buggy, destination / row["buggy_path"])
            bridge = destination / row["buggy_path"] / BRIDGE
            with bridge.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    '"""Project-authored selection bridge; original unittest methods are unchanged."""\n\nfrom .test_more import SeekableTest, SequenceViewTests  # noqa: F401\n'
                )
            task = destination / row["public_description_path"]
            shutil.copyfile(case.description, task)
        else:
            _copy_tree(case.buggy, destination / case.buggy_path)
            task = destination / case.public_description_path
            if task.resolve() != case.description.resolve():
                task.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(case.description, task)
        rows.append(row)
    more = old[0]
    required = [
        n for n in (*more.fail_to_pass, *more.pass_to_pass) if not n.startswith("hidden_tests/")
    ]
    required.extend(
        f"tests/test_more.py::{cls}::{name}" for cls, names in UPSTREAM.items() for name in names
    )
    write_new(
        destination / DESCRIPTOR,
        {
            "version": 1,
            "cases": [
                {
                    "id": more.id,
                    "revision": 2,
                    "paths": list(more.visible_tests),
                    "required": required,
                    "timeout_seconds": 120,
                    "core_repeats": 3,
                    "reason": "Defect-related core selected before new model results; original r1 pytest file scope retained. unittest load_tests doctests are excluded.",
                }
            ],
        },
    )
    write_new(manifest, {"version": 2, "cases": rows})
    load_cases(manifest)
    return manifest


def load_regression(case):
    path = case.root / DESCRIPTOR
    if not path.exists():
        if case.id == "os_more_seekable_1269" and case.revision == 2:
            raise ValueError("more r2 requires its controller regression descriptor")
        return None
    value = read_json(path)
    if (
        set(value) != {"version", "cases"}
        or value["version"] != 1
        or not isinstance(value["cases"], list)
    ):
        raise ValueError("invalid regression descriptor")
    matches = [
        row
        for row in value["cases"]
        if isinstance(row, dict)
        and (row.get("id"), row.get("revision")) == (case.id, case.revision)
    ]
    if not matches:
        if case.id == "os_more_seekable_1269" and case.revision == 2:
            raise ValueError("more r2 regression descriptor missing")
        return None
    if len(matches) != 1:
        raise ValueError("duplicate regression identity")
    row = matches[0]
    if (
        set(row)
        != {"id", "revision", "paths", "required", "timeout_seconds", "core_repeats", "reason"}
        or type(row["timeout_seconds"]) is not int
        or not 0 < row["timeout_seconds"] <= 120
        or type(row["core_repeats"]) is not int
        or row["core_repeats"] != 3
        or not isinstance(row["reason"], str)
        or not row["reason"]
    ):
        raise ValueError("invalid regression policy")
    for key in ("paths", "required"):
        if not isinstance(row[key], list) or not row[key] or len(set(row[key])) != len(row[key]):
            raise ValueError("invalid regression selection")
    for name in row["paths"]:
        safe_relative(name)
        if (
            not name.startswith("tests/")
            or not name.endswith(".py")
            or not contained(case.buggy, name).is_file()
        ):
            raise ValueError("invalid public regression file")
    for node in row["required"]:
        filename, separator, function = node.partition("::")
        if (
            not separator
            or not function
            or filename not in row["paths"]
            or any(ord(c) < 32 for c in function)
        ):
            raise ValueError("invalid regression node")
    return row
