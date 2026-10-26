import copy
import json
from dataclasses import asdict, replace

import pytest

from benchmarks.evaluation.agent_input import prepare_agent_input
from benchmarks.evaluation.cases import load_cases
from pyrepair.models import PytestFailure
from pyrepair.models import TestRun as Run
from tests.evaluation_helpers import make_case


@pytest.fixture
def public(tmp_path):
    case = load_cases(make_case(tmp_path / "assets"))[0]
    repo = tmp_path / "public"
    spec = prepare_agent_input(case, repo)
    return repo, spec


def failed_run(summary="assert -1 == 5"):
    return Run(
        ("pytest",),
        1,
        "",
        "",
        3,
        failures=(
            PytestFailure(
                "tests/test_app.py::test_add",
                "call",
                "failed",
                "AssertionError",
                summary,
                "tests/test_app.py:4: AssertionError\nE   " + summary,
                2,
            ),
        ),
        capture_source="plugin",
    )


class OwnedRunner:
    def run(self, repo, target=None):
        return failed_run()


def test_capture_round_trip_contains_real_public_code_and_contract(public):
    from benchmarks.evaluation.comparison_evidence import capture_evidence, read_evidence

    repo, spec = public
    value = capture_evidence(repo, spec, OwnedRunner())
    report, context = read_evidence(value, spec)
    assert report.node_id == "tests/test_app.py::test_add"
    assert report.summary == "assert -1 == 5"
    from tests.test_public_edit_scope import PREFIX

    assert context.task_contract == PREFIX + "Return the sum of two integers, including zero.\n"
    assert any("return a - b" in item.content for item in context.snippets)
    assert "hidden_tests" not in str(value)
    assert "gold.patch" not in str(value)


@pytest.mark.parametrize(
    "place,field,value",
    [
        ("root", "private_path", "secret"),
        ("failure", "gold_patch", "secret"),
        ("context", "hidden_tests", ["hidden_tests/x.py"]),
        ("failure", "node_id", "hidden_tests/x.py::test_secret"),
        ("failure", "parseable", False),
        ("context", "total_chars", -1),
    ],
)
def test_rejects_unknown_or_invalid_evidence_fields(public, place, field, value):
    from benchmarks.evaluation.comparison_evidence import capture_evidence, read_evidence

    repo, spec = public
    payload = copy.deepcopy(capture_evidence(repo, spec, OwnedRunner()))
    destination = payload if place == "root" else payload[place]
    destination[field] = value
    with pytest.raises(ValueError):
        read_evidence(payload, spec)


def test_frozen_parser_rejects_changed_assertion_but_preserves_business_numbers(public):
    from benchmarks.evaluation.comparison_evidence import FrozenParser, capture_evidence

    repo, spec = public
    parser = FrozenParser(capture_evidence(repo, spec, OwnedRunner()), spec)
    assert parser.parse(failed_run()).summary == "assert -1 == 5"
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(failed_run("assert 100 == 5"))


def test_frozen_context_rejects_changed_public_input(public):
    from benchmarks.evaluation.comparison_evidence import (
        FrozenContext,
        capture_evidence,
        read_evidence,
    )

    repo, spec = public
    evidence = capture_evidence(repo, spec, OwnedRunner())
    report, _ = read_evidence(evidence, spec)
    frozen = FrozenContext(evidence, spec)
    assert frozen.build(repo, report).task_contract.endswith(
        "Return the sum of two integers, including zero.\n"
    )
    (repo / "src/app.py").write_text("def add(a,b): return 5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        frozen.build(repo, report)


@pytest.mark.parametrize("code,phase", [(0, "call"), (2, "collection")])
def test_capture_requires_an_executable_public_baseline_failure(public, code, phase):
    from dataclasses import replace

    from benchmarks.evaluation.comparison_evidence import capture_evidence

    repo, spec = public
    run = failed_run()

    class Runner:
        def run(self, repo, target=None):
            return replace(run, exit_code=code, failures=(replace(run.failures[0], phase=phase),))

    with pytest.raises(ValueError, match="baseline"):
        capture_evidence(repo, spec, Runner())


def test_standard_library_stack_path_is_diagnostic_not_a_repository_file(public):
    from dataclasses import replace

    from benchmarks.evaluation.comparison_evidence import (
        FrozenParser,
        capture_evidence,
        read_evidence,
    )

    repo, spec = public
    run = failed_run()
    trace = (
        run.failures[0].traceback
        + "\n/usr/local/lib/python3.13/_strptime.py:452: ValueError\nE   value 31-08-2026"
    )
    run = replace(run, failures=(replace(run.failures[0], traceback=trace),))

    class Replay:
        def run(self, repo, target=None):
            return run

    evidence = capture_evidence(repo, spec, Replay())
    report, _context = read_evidence(evidence, spec)
    assert report.related_files == ("tests/test_app.py",)
    assert "/usr/local/lib/python3.13/_strptime.py:452" in report.traceback
    assert "31-08-2026" in report.traceback
    assert FrozenParser(evidence, spec).parse(run) == report


def test_default_object_address_can_change_without_changing_model_visible_facts(public):
    import json

    from benchmarks.evaluation.comparison_evidence import (
        FrozenParser,
        capture_evidence,
        initial_facts,
    )

    old = "assert 1 == 3\n +  where 1 = <cart.Cart object at 0x70d4a4a751d0>.item_count"
    new = "assert 1 == 3\n +  where 1 = <cart.Cart object at 0x72b3cf0ad1d0>.item_count"

    class Replay:
        def run(self, repo, target=None):
            return failed_run(old)

    repo, spec = public
    evidence = capture_evidence(repo, spec, Replay())
    before = json.dumps(initial_facts(evidence, spec), sort_keys=True)
    parser = FrozenParser(evidence, spec)
    assert parser.parse(failed_run(new)) is parser.report
    assert parser.report.summary == old
    assert json.dumps(initial_facts(evidence, spec), sort_keys=True) == before


@pytest.mark.parametrize(
    "before,after",
    [
        ("assert 0x123 == 0x456", "assert 0x789 == 0x456"),
        ("assert 1 == 3", "assert 2 == 3"),
        ("<cart.Cart object at 0x123>.item_count", "<cart.Other object at 0x456>.item_count"),
        ("<Cart value=0x123>", "<Cart value=0x456>"),
        ("object at 0x123", "object at 0x456"),
    ],
)
def test_address_comparison_does_not_hide_business_hex_types_or_nondefault_repr(
    public, before, after
):
    from benchmarks.evaluation.comparison_evidence import FrozenParser, capture_evidence

    class Replay:
        def run(self, repo, target=None):
            return failed_run(before)

    repo, spec = public
    parser = FrozenParser(capture_evidence(repo, spec, Replay()), spec)
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(failed_run(after))


OLD_HASHES = ("575258657340867558", "5828956449428120566")
NEW_HASHES = ("5558181234910447655", "6198252884123138357")


def hash_run(values=OLD_HASHES, source="assert hash(first) == hash(second)"):
    left, right = values
    summary = (
        f"assert {left} == {right}\n"
        f" +  where {left} = hash(first)\n"
        f" +  and   {right} = hash(second)"
    )
    trace = (
        "________________ test_add ________________\n"
        "    def test_add():\n"
        "        first, second = 'first', 'second'\n"
        f">       {source}\n"
        + "\n".join("E       " + line for line in summary.splitlines())
        + "\n\ntests/test_app.py:4: AssertionError\nDiagnostic count: 17"
    )
    run = failed_run()
    return replace(run, failures=(replace(run.failures[0], summary=summary, traceback=trace),))


def hash_parser(public, run):
    from benchmarks.evaluation.comparison_evidence import FrozenParser, capture_evidence

    class Replay:
        def run(self, repo, target=None):
            return run

    repo, spec = public
    evidence = capture_evidence(repo, spec, Replay())
    return FrozenParser(evidence, spec), evidence


@pytest.mark.parametrize("values", [NEW_HASHES, ("-575258657340867558", "0")])
def test_dynamic_hash_outputs_preserve_frozen_report_and_model_facts(public, values):
    from benchmarks.evaluation.comparison_evidence import initial_facts

    parser, evidence = hash_parser(public, hash_run())
    _, spec = public
    before = json.dumps(initial_facts(evidence, spec), sort_keys=True)
    serialized = json.dumps(evidence, sort_keys=True)
    assert parser.parse(hash_run(values)) is parser.report
    assert parser.report.summary.startswith("assert 575258657340867558 == 5828956449428120566")
    assert json.dumps(initial_facts(evidence, spec), sort_keys=True) == before
    assert json.dumps(evidence, sort_keys=True) == serialized


@pytest.mark.parametrize(
    "before,after",
    [
        ("hash(second)", "hash(third)"),
        ("hash(second)", "6198252884123138357"),
        ("hash(first)", "len(first)"),
        (" +  and   6198252884123138357 = hash(second)", ""),
        ("where 5558181234910447655", "where 7"),
        ("Diagnostic count: 17", "Diagnostic count: 18"),
        ("test_app.py:4", "test_app.py:5"),
    ],
)
def test_hash_comparison_rejects_changed_nonoutput_text(public, before, after):
    parser, _ = hash_parser(public, hash_run())
    run = hash_run(NEW_HASHES)
    failure = run.failures[0]
    changed = replace(
        failure,
        summary=failure.summary.replace(before, after),
        traceback=failure.traceback.replace(before, after),
    )
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(replace(run, failures=(changed,)))


@pytest.mark.parametrize(
    "values",
    [
        ("7", "7"),
        ("+7", "8"),
        ("07", "8"),
        ("-0", "8"),
        ("7.0", "8"),
        ("9" * 100, "8"),
        ("9223372036854775808", "8"),
        ("-9223372036854775809", "8"),
    ],
)
def test_hash_comparison_rejects_equal_malformed_or_oversized_outputs(public, values):
    parser, _ = hash_parser(public, hash_run())
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(hash_run(values))


@pytest.mark.parametrize("source", ["assert first == second", "assert hash(first) == 5", ""])
def test_hash_comparison_requires_hash_vs_hash_source_on_both_reports(public, source):
    parser, _ = hash_parser(public, hash_run(source=source))
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(hash_run(NEW_HASHES, source=source))


@pytest.mark.parametrize("field", ["summary", "traceback", "exception_type", "node_id"])
def test_hash_comparison_requires_matching_summary_traceback_and_metadata(public, field):
    parser, _ = hash_parser(public, hash_run())
    run = hash_run(NEW_HASHES)
    changes = {
        "summary": hash_run().failures[0].summary,
        "traceback": hash_run().failures[0].traceback,
        "exception_type": "TypeError",
        "node_id": "tests/test_app.py::test_other",
    }
    changed = replace(run.failures[0], **{field: changes[field]})
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(replace(run, failures=(changed,)))


@pytest.mark.parametrize(
    "before,after",
    [
        ("= hash(first)", "= hash(first + 1)"),
        ("where 575258657340867558", "where 7"),
        (" +  and   5828956449428120566 = hash(second)", ""),
        ("575258657340867558", "<HASH_LEFT>"),
    ],
)
def test_hash_comparison_does_not_normalize_invalid_frozen_expansions(public, before, after):
    frozen = hash_run()
    failure = frozen.failures[0]
    changed = replace(
        failure,
        summary=failure.summary.replace(before, after),
        traceback=failure.traceback.replace(before, after),
    )
    parser, _ = hash_parser(public, replace(frozen, failures=(changed,)))
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(hash_run(NEW_HASHES))


def test_hash_comparison_does_not_confuse_literal_markers_with_validated_outputs(public):
    parser, _ = hash_parser(public, hash_run(("<HASH_LEFT>", "<HASH_RIGHT>")))
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(hash_run(NEW_HASHES))


def saved_short_hash_run(values=OLD_HASHES):
    # Literal summary/traceback shape from saved p/c22/evidence.json, not a
    # reconstructed long traceback. Only the two runtime hash outputs vary.
    summary = (
        "AssertionError: assert 575258657340867558 == 5828956449428120566\n"
        " +  where 575258657340867558 = hash(<Requirement('sample==2.0.0')>)\n"
        " +  and   5828956449428120566 = hash(<Requirement('sample==2.0.0.0')>)"
    )
    traceback = (
        "pyrepair_public_tests/test_repro.py:8: in test_equivalent_release_requirements_are_one_key\n"
        "    assert hash(first) == hash(second)\n"
        "E   AssertionError: assert 575258657340867558 == 5828956449428120566\n"
        "E    +  where 575258657340867558 = hash(<Requirement('sample==2.0.0')>)\n"
        "E    +  and   5828956449428120566 = hash(<Requirement('sample==2.0.0.0')>)"
    )
    for old, new in zip(OLD_HASHES, values):
        summary = summary.replace(old, new)
        traceback = traceback.replace(old, new)
    run = failed_run()
    return replace(run, failures=(replace(run.failures[0], summary=summary, traceback=traceback),))


def test_saved_short_hash_trace_with_opaque_pytest_reprs_preserves_frozen_facts(public):
    from benchmarks.evaluation.comparison_evidence import initial_facts

    parser, evidence = hash_parser(public, saved_short_hash_run())
    _, spec = public
    before = json.dumps(initial_facts(evidence, spec), sort_keys=True)
    serialized = json.dumps(evidence, sort_keys=True)
    assert parser.parse(saved_short_hash_run(NEW_HASHES)) is parser.report
    assert "sample==2.0.0.0" in parser.report.summary
    assert json.dumps(initial_facts(evidence, spec), sort_keys=True) == before
    assert json.dumps(evidence, sort_keys=True) == serialized


@pytest.mark.parametrize(
    "before,after",
    [
        ("Requirement('sample==2.0.0')", "Other('sample==2.0.0')"),
        ("sample==2.0.0.0", "sample==2.0.0.1"),
        ("assert hash(first) == hash(second)", "assert hash(first) == 5"),
        ("where 5558181234910447655", "where 7"),
        ("test_repro.py:8:", "test_repro.py:9:"),
    ],
)
def test_saved_short_hash_trace_preserves_reprs_source_and_other_numbers(public, before, after):
    parser, _ = hash_parser(public, saved_short_hash_run())
    run = saved_short_hash_run(NEW_HASHES)
    failure = run.failures[0]
    changed = replace(
        failure,
        summary=failure.summary.replace(before, after),
        traceback=failure.traceback.replace(before, after),
    )
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(replace(run, failures=(changed,)))


def saved_truncated_object_run(address="7a7f8c9752b0"):
    # Literal saved public summary/traceback; no external fixture dependency.
    summary = (
        "AssertionError: assert [<test_repro....7a7f8c9752b0>] == [<class 'test...s>.Strategy'>]\n"
        "  \n"
        "  At index 0 diff: <test_repro.test_default_true_preserves_class_flag_value_identity."
        "<locals>.Strategy object at 0x7a7f8c9752b0> != <class 'test_repro."
        "test_default_true_preserves_class_flag_value_identity.<locals>.Strategy'>\n"
        "  Use -v to get more diff"
    )
    traceback = (
        "pyrepair_public_tests/test_repro.py:20: in "
        "test_default_true_preserves_class_flag_value_identity\n"
        "    assert observed == [Strategy]\n"
        "E   AssertionError: assert [<test_repro....7a7f8c9752b0>] == [<class 'test...s>.Strategy'>]\n"
        "E     \n"
        "E     At index 0 diff: <test_repro."
        "test_default_true_preserves_class_flag_value_identity.<locals>.Strategy object at "
        "0x7a7f8c9752b0> != <class 'test_repro."
        "test_default_true_preserves_class_flag_value_identity.<locals>.Strategy'>\n"
        "E     Use -v to get more diff"
    )
    failure = PytestFailure(
        "pyrepair_public_tests/test_repro.py::test_default_true_preserves_class_flag_value_identity",
        "call",
        "failed",
        "AssertionError",
        summary.replace("7a7f8c9752b0", address),
        traceback.replace("7a7f8c9752b0", address),
        0,
    )
    return replace(failed_run(), failures=(failure,))


def truncated_object_parser(public, run):
    from benchmarks.evaluation.comparison_evidence import FrozenParser, capture_evidence
    from pyrepair.pytest_parser import PytestParser

    repo, spec = public
    evidence = capture_evidence(repo, spec, OwnedRunner())
    evidence["failure"] = json.loads(json.dumps(asdict(PytestParser().parse(run))))
    spec = replace(spec, visible_tests=("pyrepair_public_tests/test_repro.py",))
    return FrozenParser(evidence, spec), evidence, spec


def test_saved_truncated_object_addresses_preserve_frozen_report_and_model_facts(public):
    from benchmarks.evaluation.comparison_evidence import initial_facts

    parser, evidence, spec = truncated_object_parser(public, saved_truncated_object_run())
    before = json.dumps(initial_facts(evidence, spec), sort_keys=True)
    serialized = json.dumps(evidence, sort_keys=True)
    assert parser.parse(saved_truncated_object_run("7857eaf792b0")) is parser.report
    assert "[<test_repro....7a7f8c9752b0>]" in parser.report.summary
    assert "0x7a7f8c9752b0" in parser.report.traceback
    assert json.dumps(initial_facts(evidence, spec), sort_keys=True) == before
    assert json.dumps(evidence, sort_keys=True) == serialized


@pytest.mark.parametrize("field", ["summary", "traceback", "both"])
@pytest.mark.parametrize(
    "before,after",
    [
        (" object at 0x", " value at 0x"),  # Missing complete default-repr witness.
        ("[<test_repro....", "[<other...."),
        ("[<test_repro....", "[<test_repro.other...."),
        ("object at 0x7", "object at 0x6"),
        ("object at 0x7", "object at 0xz7"),
        ("[<test_repro....7", "[<test_repro....z7"),
        ("7a7f8c9752b0", "123456789abcdef0123456789"),
        ("7857eaf792b0", "fedcba9876543210987654321"),
        ("diff: <test_repro.", "diff: <other_repro."),
        ("Use -v", "<test_repro.Extra object at 0x123> Use -v"),
        ("Use -v", "<test_repro....123> Use -v"),
    ],
)
def test_truncated_object_comparison_requires_unique_consistent_witnesses(
    public, field, before, after
):
    def changed(run):
        failure = run.failures[0]
        names = ("summary", "traceback") if field == "both" else (field,)
        updates = {name: getattr(failure, name).replace(before, after) for name in names}
        return replace(run, failures=(replace(failure, **updates),))

    # Invalid frozen reports must also remain fail-closed; never just validate
    # the newly observed report and assume the frozen one was well-formed.
    parser, _, _ = truncated_object_parser(public, changed(saved_truncated_object_run()))
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(changed(saved_truncated_object_run("7857eaf792b0")))


@pytest.mark.parametrize(
    "field,before,after",
    [
        ("summary", "7857eaf792b0", "7a7f8c9752b0"),
        ("traceback", "7857eaf792b0", "7a7f8c9752b0"),
        ("summary", "Strategy", "Other"),
        ("traceback", "assert observed == [Strategy]", "assert observed == [Other]"),
        ("traceback", "test_repro.py:20:", "test_repro.py:21:"),
        ("exception_type", "AssertionError", "TypeError"),
        ("node_id", "flag_value_identity", "flag_value_other"),
    ],
)
def test_truncated_object_comparison_preserves_metadata_source_and_types(
    public, field, before, after
):
    parser, _, _ = truncated_object_parser(public, saved_truncated_object_run())
    run = saved_truncated_object_run("7857eaf792b0")
    failure = run.failures[0]
    failure = replace(failure, **{field: getattr(failure, field).replace(before, after)})
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(replace(run, failures=(failure,)))


@pytest.mark.parametrize(
    "old,new",
    [
        ("\nDiagnostic: 17", "\nDiagnostic: 18"),
        ("\nDiagnostic: 0x7a7f8c9752b0", "\nDiagnostic: 0x7857eaf792b0"),
        ("\nDiagnostic: 7a7f8c9752b0", "\nDiagnostic: 7857eaf792b0"),
    ],
)
def test_truncated_object_comparison_never_masks_other_numeric_diagnostics(public, old, new):
    def diagnostic(run, text):
        failure = run.failures[0]
        return replace(
            run,
            failures=(
                replace(
                    failure, summary=failure.summary + text, traceback=failure.traceback + text
                ),
            ),
        )

    parser, _, _ = truncated_object_parser(public, diagnostic(saved_truncated_object_run(), old))
    with pytest.raises(ValueError, match="baseline"):
        parser.parse(diagnostic(saved_truncated_object_run("7857eaf792b0"), new))
