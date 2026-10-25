"""Disclosed edit scope must match the grader, not just a self-consistent hash."""

import json
import re
from dataclasses import replace

import pytest

from benchmarks.evaluation.agent_input import prepare_agent_input
from benchmarks.evaluation.cases import load_cases
from tests.evaluation_helpers import make_case, patch

PREFIX = (
    "## 公开评测约束（agent-public-r2）\n"
    "允许修改的现有源码文件（相对仓库根目录，精确文件路径；不是目录或通配符）：\n"
    '["src/app.py"]'
    "\n\n补丁只能修改以上文件，不得新增、删除或重命名文件。\n"
    "其他公开文件仅可通过原有工具权限读取，不得修改。\n"
    "不得修改测试、配置、依赖或环境。\n\n## 原始公开任务说明\n"
)


def scope_paths(text):
    match = re.search(r"^\[.*\]$", text, re.MULTILINE)
    assert match is not None, "model-visible edit scope is missing"
    return json.loads(match[0])


def test_public_task_discloses_exact_scope_without_rewriting_assets(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    original = case.description.read_bytes()
    source = (case.buggy / "src/app.py").read_bytes()
    repo = tmp_path / "public"
    spec = prepare_agent_input(case, repo)
    contract = (repo / "TASK.md").read_text("utf-8")
    assert contract == PREFIX + "Return the sum of two integers, including zero.\n"
    assert scope_paths(contract) == ["src/app.py"]
    assert case.description.read_bytes() == original
    assert (repo / "src/app.py").read_bytes() == source
    assert "hidden_tests" not in contract
    assert "gold.patch" not in contract
    assert spec.input_policy == "agent-public-r2"


def test_multi_file_scope_keeps_order_spaces_and_unicode(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    (case.buggy / "src/辅助 space.py").write_bytes(b"value = 1\r\n")
    case = replace(case, allowed_source_paths=("src/辅助 space.py", "src/app.py"))
    repo = tmp_path / "public"
    prepare_agent_input(case, repo)
    assert scope_paths((repo / "TASK.md").read_text("utf-8")) == ["src/辅助 space.py", "src/app.py"]
    assert (repo / "src/辅助 space.py").read_bytes() == b"value = 1\r\n"


@pytest.mark.parametrize(
    "paths",
    [
        (),
        ("src/app.py", "src/app.py"),
        ("src/app.py", "src/APP.py"),
        ("../app.py",),
        ("src/absent.py",),
        ("tests/test_app.py",),
        (".agents/notes.py",),
        ("pyproject.toml",),
    ],
)
def test_invalid_scope_is_rejected_before_any_public_copy(tmp_path, paths):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    filtered = case.buggy / ".agents/notes.py"
    filtered.parent.mkdir()
    filtered.write_text("owned fixture\n", encoding="utf-8")
    repo = tmp_path / "public"
    with pytest.raises(ValueError):
        prepare_agent_input(replace(case, allowed_source_paths=paths), repo)
    assert not repo.exists()


@pytest.mark.parametrize(
    "body",
    [b"", b" \r\n\t", b"\xff", b"x" * 4000],
    ids=["empty", "blank", "invalid-utf8", "header-over-limit"],
)
def test_bad_or_oversize_combined_contract_is_rejected_before_copy(tmp_path, body):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    case.description.write_bytes(body)
    repo = tmp_path / "public"
    with pytest.raises(ValueError):
        prepare_agent_input(case, repo)
    assert not repo.exists()


@pytest.mark.parametrize("extra,accepted", [(0, True), (1, False)])
def test_complete_contract_limit_includes_the_scope_header(tmp_path, extra, accepted):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    case.description.write_text("x" * (4000 - len(PREFIX) + extra), encoding="utf-8")
    repo = tmp_path / "public"
    if accepted:
        prepare_agent_input(case, repo)
        contract = (repo / "TASK.md").read_text("utf-8")
        assert len(contract) == 4000
        assert scope_paths(contract) == ["src/app.py"]
    else:
        with pytest.raises(ValueError, match="4000"):
            prepare_agent_input(case, repo)
        assert not repo.exists()


def test_display_only_normalizes_task_newlines(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    body = b"first\r\nsecond\rthird\n"
    case.description.write_bytes(body)
    repo = tmp_path / "public"
    prepare_agent_input(case, repo)
    assert (repo / "TASK.md").read_bytes() == (PREFIX + "first\nsecond\nthird\n").encode()
    assert case.description.read_bytes() == body


def test_r1_descriptor_cannot_be_reused_for_disclosed_scope():
    from benchmarks.evaluation.agent_input import PublicTaskSpec
    from tests.test_agent_input import public_payload

    with pytest.raises(ValueError, match="policy"):
        PublicTaskSpec.from_dict(public_payload() | {"input_policy": "agent-public-r1"})


@pytest.mark.parametrize("where", ["task", "review", "repair", "all"])
def test_rehashed_false_scope_cannot_be_frozen_as_the_grader_contract(tmp_path, monkeypatch, where):
    from benchmarks.evaluation import container_protocol as protocol
    from benchmarks.evaluation.experiment import digest
    from tests.test_comparison_pack import make_prepared

    pack, cases, output, _ = make_prepared(tmp_path, monkeypatch)
    public = output / "p/c00"
    spec = json.loads((public / "spec.json").read_text("utf-8"))
    evidence = json.loads((public / "evidence.json").read_text("utf-8"))
    identity = json.loads((output / "pack.json").read_text("utf-8"))["identity"]
    original = evidence["context"]["task_contract"]
    changed = original.replace('"src/app.py"', '"src/alt.py"')
    if changed == original:
        changed += "\nOnly allowed source file: src/alt.py.\n"
    if where in {"task", "all"}:
        (public / "r/TASK.md").write_bytes(changed.encode())
    if where in {"review", "all"}:
        evidence["context"]["task_contract"] = changed
    if where in {"repair", "all"}:
        context = evidence["context"]
        context["repo_overview"] = context["repo_overview"].replace(
            "Public task contract:\n" + original + "\n",
            "Public task contract:\n" + changed + "\n",
            1,
        )
        context["total_chars"] = len(context["repo_overview"]) + sum(
            len(s["content"]) for s in context["snippets"]
        )
    inventory = protocol.input_inventory(public / "r", tuple(spec["visible_tests"]))
    spec["public_input_hash"] = evidence["public_input_hash"] = protocol.inventory_hash(inventory)
    for name, value in [("spec.json", spec), ("evidence.json", evidence)]:
        (public / name).write_text(json.dumps(value), encoding="utf-8")
        identity["cases"][0][name.removesuffix(".json") + "_hash"] = pack.file_hash(public / name)
    (output / "pack.json").write_text(
        json.dumps({"identity": identity, "identity_hash": digest(identity)}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="contract|scope"):
        pack.verify_pack(output, cases)


def test_scope_survives_context_trimming_without_increasing_budget(tmp_path):
    from benchmarks.evaluation.agent_worker import PublicContractContext
    from pyrepair.context_builder import ContextBundle, ContextSnippet
    from pyrepair.models import FailureReport

    case = load_cases(make_case(tmp_path / "assets"))[0]
    repo = tmp_path / "public"
    prepare_agent_input(case, repo)
    snippets = tuple(
        ContextSnippet("src/app.py", 1, 1, None, "fixture", 1, "x" * 1900) for _ in range(8)
    )
    bundle = ContextBundle("v" * 700, snippets, ("src/app.py",), 15900, False)

    class Builder:
        def build(self, root, report):
            return bundle

    report = FailureReport(
        "tests/test_app.py::test_add", "AssertionError", "owned trace", "assert -1 == 5"
    )
    context = PublicContractContext(Builder()).build(repo, report)
    assert scope_paths(context.task_contract) == ["src/app.py"]
    assert context.task_contract == PREFIX + "Return the sum of two integers, including zero.\n"
    assert context.repo_overview.startswith(
        "Public task contract:\n" + context.task_contract + "\n"
    )
    assert context.total_chars <= 16000
    assert context.total_chars == len(context.repo_overview) + sum(
        len(s.content) for s in context.snippets
    )
    assert len(context.snippets) < 8
    assert context.truncated is True


def test_prepare_refuses_divergent_evidence_before_finalizing_pack(tmp_path, monkeypatch):
    from tests.test_comparison_pack import make_prepared

    def configure(pack, cases, lock):
        original_capture = pack.capture_evidence

        def divergent(*args):
            evidence = original_capture(*args)
            evidence["context"]["task_contract"] = "Only edit src/alt.py.\n"
            return evidence

        monkeypatch.setattr(pack, "capture_evidence", divergent)

    with pytest.raises(ValueError, match="contract|scope"):
        make_prepared(tmp_path, monkeypatch, configure)
    assert not (tmp_path / "pack/pack.json").exists()
    assert (tmp_path / "pack/preparation-error.json").is_file()


def test_disclosed_scope_does_not_relax_original_patch_rejection(tmp_path):
    from benchmarks.evaluation.cases import prepare_case
    from benchmarks.evaluation.patching import PatchRejected, apply_patch_checked

    case = load_cases(make_case(tmp_path / "assets"))[0]
    (case.buggy / "src/__init__.py").write_text("value = 0\n", encoding="utf-8")
    repo = prepare_case(case, tmp_path / "repo")
    with pytest.raises(PatchRejected, match="outside allowed_source_paths"):
        apply_patch_checked(case, repo, patch("value = 0\n", "value = 1\n", "src/__init__.py"))
    assert (repo / "src/__init__.py").read_text("utf-8") == "value = 0\n"
    valid = patch("def add(a, b):\n    return a - b\n", "def add(a, b):\n    return a + b\n")
    assert apply_patch_checked(case, repo, valid) == ("src/app.py",)
