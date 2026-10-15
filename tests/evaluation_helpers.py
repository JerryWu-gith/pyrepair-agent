"""Hand-checked evaluation fixtures; never used by production code."""

import difflib
import json
from pathlib import Path


def patch(old: str, new: str, path: str = "src/app.py") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def make_case(root: Path) -> Path:
    files = {
        "cases/demo/src/app.py": "def add(a, b):\n    return a - b\n",
        "cases/demo/tests/test_app.py": (
            "from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
        ),
        "cases/demo/pyproject.toml": '[tool.pytest.ini_options]\npythonpath = ["src"]\n',
        "private/demo/hidden_tests/test_hidden.py": (
            "from app import add\n\ndef test_other():\n    assert add(3, 4) == 7\n"
            "\ndef test_zero():\n    assert add(0, 0) == 0\n"
        ),
        "descriptions/demo.md": "Return the sum of two integers, including zero.\n",
    }
    old = files["cases/demo/src/app.py"]
    files["private/demo/gold.patch"] = patch(old, old.replace("a - b", "a + b"))
    files["private/demo/wrong.patch"] = patch(old, old.replace("a - b", "5"))
    for name, text in files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8", newline="\n")
    item = {
        "id": "demo",
        "revision": 1,
        "suite": "regression",
        "split": "dev",
        "source_kind": "synthetic",
        "origin": {"description": "Hand-written fixture"},
        "buggy_path": "cases/demo",
        "public_description_path": "descriptions/demo.md",
        "private_path": "private/demo",
        "visible_tests": ["tests/test_app.py"],
        "hidden_tests": ["hidden_tests/test_hidden.py"],
        "fail_to_pass": ["tests/test_app.py::test_add", "hidden_tests/test_hidden.py::test_other"],
        "pass_to_pass": ["hidden_tests/test_hidden.py::test_zero"],
        "allowed_source_paths": ["src/app.py"],
        "timeout_seconds": 15,
    }
    manifest = root / "manifest_v2.json"
    manifest.write_text(json.dumps({"version": 2, "cases": [item]}), encoding="utf-8")
    return manifest


def change_manifest(path: Path, **changes) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0].update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
