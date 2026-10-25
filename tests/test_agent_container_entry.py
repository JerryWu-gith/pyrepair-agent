"""Only self-authored Python is run on the host by these internal entry tests."""

import pytest

from tests.test_container_entry import staged


def test_agent_entry_runs_exact_selected_node_instead_of_entire_file(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import read_stage_output

    staging, request, work, output = staged(
        tmp_path,
        "def test_selected():\n    assert True\n"
        "def test_must_not_run():\n    raise AssertionError('selection leaked')\n",
    )
    node = "test_owned.py::test_selected"
    request.update(version=2, mode="agent", target=node, required=[node])

    assert run_stage(request, staging, work, output) == 0
    checked = read_stage_output(output, request)
    assert checked["probe"]["collected"] == [node]
    assert checked["passed"] is True
    assert checked["failures"] == []


@pytest.mark.parametrize(
    "body,phase,exception_type,code",
    [
        ("def test_owned():\n    assert 1 == 2\n", "call", "AssertionError", 1),
        (
            (
                "import pytest\n@pytest.fixture(autouse=True)\ndef fixture():\n    raise RuntimeError('setup')\n"
                "def test_owned():\n    pass\n"
            ),
            "setup",
            "RuntimeError",
            1,
        ),
        (
            (
                "import pytest\n@pytest.fixture(autouse=True)\ndef fixture():\n    yield\n"
                "    raise RuntimeError('teardown')\ndef test_owned():\n    pass\n"
            ),
            "teardown",
            "RuntimeError",
            1,
        ),
        ("def test_owned(:\n    pass\n", "collection", "SyntaxError", 2),
        (
            (
                "def test_owned(subtests):\n    for i in (0, 1):\n"
                "        with subtests.test(i=i):\n            assert i == 0\n"
            ),
            "call",
            "AssertionError",
            1,
        ),
    ],
)
def test_agent_entry_preserves_structured_failure_diagnostics(
    tmp_path, body, phase, exception_type, code
):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import read_stage_output

    staging, request, work, output = staged(tmp_path, body)
    request.update(version=2, mode="agent", target=None, required=[])

    assert run_stage(request, staging, work, output) == 1
    checked = read_stage_output(output, request)
    assert checked["status"] == "failed"
    assert checked["returncode"] == code
    failure = checked["failures"][0]
    assert failure["phase"] == phase
    assert failure["exception_type"] == exception_type
    assert failure["traceback"]
    assert failure["summary"]
    assert type(failure["duration_ms"]) is int
    assert checked["integrity"]["unchanged"] is True


def test_agent_collection_abort_preserves_other_collected_but_unrun_nodes(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import (
        input_inventory,
        inventory_hash,
        read_stage_output,
    )
    from tests.test_docker_runner import write_json

    staging, request, work, output = staged(tmp_path, "def test_owned():\n    assert True\n")
    (staging / "repo/test_broken.py").write_text("def test_broken(:\n    pass\n", encoding="utf-8")
    request.update(
        version=2, mode="agent", target=None, required=[], paths=["test_owned.py", "test_broken.py"]
    )
    inventory = input_inventory(staging / "repo", tuple(request["paths"]))
    request["input_hash"] = inventory_hash(inventory)
    write_json(staging / "inventory.json", inventory)

    assert run_stage(request, staging, work, output) == 1
    checked = read_stage_output(output, request)
    assert checked["status"] == "failed"
    assert checked["returncode"] == 2
    assert checked["probe"]["collected"] == ["test_owned.py::test_owned"]
    assert checked["probe"]["reports"] == []
    assert checked["failures"][0]["node_id"] == "test_broken.py"


def test_precise_target_import_syntax_failure_preserves_pytest_exit_four(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage
    from benchmarks.evaluation.container_protocol import (
        input_inventory,
        inventory_hash,
        read_stage_output,
    )
    from tests.test_docker_runner import write_json

    staging, request, work, output = staged(
        tmp_path, "from app import value\ndef test_owned():\n    assert value == 1\n"
    )
    (staging / "repo/app.py").write_text("def broken(:\n", encoding="utf-8")
    node = "test_owned.py::test_owned"
    request.update(version=2, mode="agent", target=node, required=[node])
    inventory = input_inventory(staging / "repo", tuple(request["paths"]))
    request["input_hash"] = inventory_hash(inventory)
    write_json(staging / "inventory.json", inventory)

    assert run_stage(request, staging, work, output) == 1
    checked = read_stage_output(output, request)
    assert checked["returncode"] == 4
    assert checked["failures"][0]["exception_type"] == "SyntaxError"


def test_precise_missing_node_usage_error_without_collection_failure_stays_fatal(tmp_path):
    from benchmarks.evaluation.container_entry import run_stage

    staging, request, work, output = staged(tmp_path, "def test_owned():\n    assert True\n")
    node = "test_owned.py::test_absent"
    request.update(version=2, mode="agent", target=node, required=[node])

    assert run_stage(request, staging, work, output) == 2
