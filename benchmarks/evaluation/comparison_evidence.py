"""Public initial facts shared by both methods; no answers or private task metadata."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, fields, replace

from pyrepair.context_builder import ContextBundle, ContextSnippet, validate_task_contract
from pyrepair.models import FailureReport
from pyrepair.pytest_parser import PytestParser
from pyrepair.repair_agent import _initial_messages

from .agent_input import PublicTaskSpec, validate_public_input
from .agent_worker import PublicContractContext
from .cases import safe_relative


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("invalid public evidence fields")


def _text(value, limit=16000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("invalid public evidence text")


def _paths(value):
    if not isinstance(value, list) or len(value) > 10000:
        raise ValueError("invalid public evidence paths")
    for name in value:
        safe_relative(name)
        if "hidden_tests" in name.casefold().split("/"):
            raise ValueError("private path in public evidence")
    if len(value) != len(set(value)):
        raise ValueError("duplicate public evidence path")
    return tuple(value)


def _repository_report(report):
    # Library stack frames remain verbatim diagnostic text, not file-tool targets.
    paths = []
    for name in report.related_files:
        try:
            _paths([name])
        except ValueError:
            continue
        paths.append(name)
    return replace(report, related_files=tuple(paths))


def read_evidence(value: dict, spec: PublicTaskSpec) -> tuple[FailureReport, ContextBundle]:
    _keys(value, ("version", "public_input_hash", "failure", "context"))
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("invalid public evidence version")
    if value["public_input_hash"] != spec.public_input_hash:
        raise ValueError("public evidence input digest mismatch")
    failure, context = value["failure"], value["context"]
    _keys(failure, (f.name for f in fields(FailureReport)))
    _keys(context, (f.name for f in fields(ContextBundle)))
    node = failure["node_id"]
    if (
        not isinstance(node, str)
        or "::" not in node
        or node.partition("::")[0] not in spec.visible_tests
    ):
        raise ValueError("baseline target is not a public test node")
    if failure["parseable"] is not True:
        raise ValueError("baseline report is not parseable")
    if failure["exception_type"] is not None:
        _text(failure["exception_type"], 200)
    _text(failure["summary"], 2000)
    _text(failure["traceback"])
    report = FailureReport(**{**failure, "related_files": _paths(failure["related_files"])})
    _text(context["repo_overview"])
    _text(context["task_contract"], 4000)
    validate_task_contract(context["task_contract"], required=True)
    if type(context["truncated"]) is not bool or not isinstance(context["snippets"], list):
        raise ValueError("invalid public context metadata")
    if len(context["snippets"]) > 8:
        raise ValueError("too many public context snippets")
    snippets = []
    for item in context["snippets"]:
        _keys(item, (f.name for f in fields(ContextSnippet)))
        _paths([item["path"]])
        for name in ("start_line", "end_line", "score"):
            if type(item[name]) is not int or item[name] < (0 if name == "score" else 1):
                raise ValueError("invalid snippet position/score")
        if item["end_line"] < item["start_line"]:
            raise ValueError("invalid snippet range")
        for name in ("reason", "content"):
            _text(item[name])
        if item["symbol"] is not None:
            _text(item["symbol"])
        snippets.append(ContextSnippet(**item))
    total = len(context["repo_overview"]) + sum(len(s.content) for s in snippets)
    if type(context["total_chars"]) is not int or context["total_chars"] != total or total > 16000:
        raise ValueError("invalid public context character count")
    bundle = ContextBundle(
        **{
            **context,
            "snippets": tuple(snippets),
            "related_files": _paths(context["related_files"]),
        }
    )
    return report, bundle


def capture_evidence(repo, spec, runner) -> dict:
    """Caller owns runner; the pack builder requires the concrete Docker adapter."""
    from pyrepair.context_builder import ContextBuilder

    validate_public_input(repo, spec)
    run = runner.run(repo)
    report = _repository_report(PytestParser().parse(run))
    if (
        run.exit_code != 1
        or run.timed_out
        or run.launch_error
        or not report.parseable
        or not any(f.node_id == report.node_id and f.phase != "collection" for f in run.failures)
    ):
        raise ValueError("public baseline must have an executable failure")
    bundle = PublicContractContext(ContextBuilder()).build(repo, report)
    # JSON round-trip is canonical public serialization; timings are not FailureReport fields.
    value = json.loads(
        json.dumps(
            {
                "version": 1,
                "public_input_hash": spec.public_input_hash,
                "failure": asdict(report),
                "context": asdict(bundle),
            },
            ensure_ascii=False,
        )
    )
    read_evidence(value, spec)
    return value


def initial_facts(value, spec) -> dict:
    report, context = read_evidence(value, spec)
    return json.loads(_initial_messages(report, (), context)[1]["content"])


_HASH_EXPANSION = re.compile(
    r"(?m)^(?:E[ \t]+)?(?:AssertionError: )?assert (?P<left>-?(?:0|[1-9][0-9]{0,18})) == "
    r"(?P<right>-?(?:0|[1-9][0-9]{0,18}))\n"
    r"(?:E[ \t]+)?[ \t]*\+  where (?P<where>-?(?:0|[1-9][0-9]{0,18})) = "
    r"(?P<left_expr>hash\([^\n]+\))\n"
    r"(?:E[ \t]+)?[ \t]*\+  and   (?P<and>-?(?:0|[1-9][0-9]{0,18})) = "
    r"(?P<right_expr>hash\([^\n]+\))$"
)


def _hash_signature(value):
    """Mask only corroborated pytest hash outputs in the comparison copy."""
    if value["exception_type"] != "AssertionError":
        return
    matches = [list(_HASH_EXPANSION.finditer(value[name])) for name in ("summary", "traceback")]
    if any(len(items) != 1 for items in matches):
        return
    summary, trace = (items[0] for items in matches)
    if summary.groupdict() != trace.groupdict():
        return
    numbers = [int(summary[name]) for name in ("left", "right", "where", "and")]
    if (
        numbers[0] == numbers[1]
        or summary["left"] != summary["where"]
        or summary["right"] != summary["and"]
        or any(summary[name] != str(number) for name, number in zip(("left", "right"), numbers))
        or any(not -(2**63) <= number < 2**63 for number in numbers)
    ):
        return
    sources = list(re.finditer(r"(?m)^(?:>[ \t]+|[ \t]{4,})(assert [^\n]+)$", value["traceback"]))
    if len(sources) != 1 or value["traceback"][sources[0].end() : trace.start()] != "\n":
        return
    try:
        statement = ast.parse(sources[0][1]).body[0]
        comparison = statement.test if isinstance(statement, ast.Assert) else None
        if (
            not isinstance(comparison, ast.Compare)
            or len(comparison.ops) != 1
            or not isinstance(comparison.ops[0], ast.Eq)
        ):
            return
        # Expanded arguments may be opaque reprs, e.g. hash(<Requirement(...)>).
        # Keep those literal in both signatures; only source is Python syntax.
        for source in (comparison.left, comparison.comparators[0]):
            if (
                not isinstance(source, ast.Call)
                or not isinstance(source.func, ast.Name)
                or source.func.id != "hash"
                or len(source.args) != 1
                or source.keywords
            ):
                return
    except (SyntaxError, ValueError, RecursionError):
        return
    value["hash_expansion_validated"] = True
    for name, match in zip(("summary", "traceback"), (summary, trace)):
        text = value[name]
        for group in ("and", "where", "right", "left"):
            start, end = match.span(group)
            text = (
                text[:start]
                + ("<HASH_LEFT>" if group in ("left", "where") else "<HASH_RIGHT>")
                + text[end:]
            )
        value[name] = text


def _truncated_object_signature(value):
    """Corroborate pytest abbreviations before masking either address span."""
    if value["exception_type"] != "AssertionError":
        return
    complete = re.compile(
        r"<(?P<type>[A-Za-z_]\w*(?:\.(?:[A-Za-z_]\w*|<locals>))*) object at "
        r"0x(?P<address>[0-9a-fA-F]{1,16})>"
    )
    abbreviated = re.compile(
        r"<(?P<prefix>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\.?)"
        r"\.\.\.(?P<address>[0-9a-fA-F]{1,16})>"
    )
    pairs = []
    for name in ("summary", "traceback"):
        full = list(complete.finditer(value[name]))
        short = list(abbreviated.finditer(value[name]))
        if len(full) != 1 or len(short) != 1:
            return
        full, short = full[0], short[0]
        if (
            full["address"] != short["address"]
            or not full["type"].startswith(short["prefix"])
            or len(short["prefix"]) >= len(full["type"])
        ):
            return
        pairs.append((full, short))
    if any(pairs[0][i].groupdict() != pairs[1][i].groupdict() for i in (0, 1)):
        return
    value["truncated_object_validated"] = True
    for name, pair in zip(("summary", "traceback"), pairs):
        text = value[name]
        for start, end in sorted((match.span("address") for match in pair), reverse=True):
            text = text[:start] + "<ADDRESS>" + text[end:]
        value[name] = text


def _baseline_signature(report):
    """Ignore validated runtime outputs only for comparison, never model input."""
    value = asdict(report)
    _truncated_object_signature(value)
    for name in ("summary", "traceback"):
        value[name] = re.sub(
            r"(<[A-Za-z_][\w.]* object at )0x[0-9a-fA-F]+(>)",
            r"\1<ADDRESS>\2",
            value[name],
        )
    _hash_signature(value)
    return value


class FrozenParser:
    def __init__(self, evidence, spec):
        self.report, self.context = read_evidence(evidence, spec)

    def parse(self, run, preferred_node_id=None):
        actual = _repository_report(PytestParser().parse(run, preferred_node_id))
        if run.exit_code != 1 or _baseline_signature(actual) != _baseline_signature(self.report):
            raise ValueError("current public baseline differs from frozen evidence")
        return self.report


class FrozenContext:
    def __init__(self, evidence, spec):
        self.report, self.context = read_evidence(evidence, spec)
        self.spec = spec

    def build(self, root, report):
        validate_public_input(root, self.spec)
        if report != self.report:
            raise ValueError("baseline report differs from frozen evidence")
        return self.context
