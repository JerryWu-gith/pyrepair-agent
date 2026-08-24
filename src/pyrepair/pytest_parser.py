from __future__ import annotations

import re
from collections.abc import Iterable

from .models import FailureReport, PytestFailure, TestRun

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
NODE_ID_PATTERN = r"(?P<node>[\w./\\-]+\.py(?:::\S+)?)"
SUMMARY_PATTERNS = (
    re.compile(rf"^FAILED\s+{NODE_ID_PATTERN}(?:\s+-\s+(?P<detail>.*))?$"),
    re.compile(rf"^ERROR\s+{NODE_ID_PATTERN}(?:\s+-\s+(?P<detail>.*))?$"),
    re.compile(rf"^{NODE_ID_PATTERN}\s+(?P<kind>FAILED|ERROR)$"),
    re.compile(rf"^ERROR\s+collecting\s+{NODE_ID_PATTERN}(?:\s+-\s+(?P<detail>.*))?$"),
)
PHASE_PRIORITY = {"call": 0, "setup": 1, "teardown": 2, "collection": 3}
PATH_RE = re.compile(r"(?m)^([\w./\\-]+\.py):\d+")
EXCEPTION_RE = re.compile(
    r"^E\s+(?P<exception>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?::\s*(?P<summary>.*))?$"
)
DETAIL_EXCEPTION_RE = re.compile(
    r"^(?P<exception>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?::\s*(?P<summary>.*))?$"
)
SECTION_RE = re.compile(r"^_{3,}.*_{3,}\s*$")


class PytestParser:
    def parse(
        self, run: TestRun, preferred_node_id: str | None = None
    ) -> FailureReport:
        raw = "\n".join(part for part in (run.stdout, run.stderr) if part)
        failure = select_primary_failure(run.failures, preferred_node_id)
        if failure is None:
            return FailureReport(None, None, raw[-6000:], raw[-500:], (), False)
        return FailureReport(
            failure.node_id,
            failure.exception_type,
            failure.traceback,
            failure.summary,
            _related_paths(failure.traceback),
            True,
        )


def parse_text_failures(text: str) -> tuple[PytestFailure, ...]:
    lines = ANSI_RE.sub("", text).splitlines()
    failures: list[PytestFailure] = []
    for summary_index, line in enumerate(lines):
        match = _summary_match(line)
        if match:
            failures.append(_parse_summary(lines, summary_index, match))
    return tuple(failures)


def select_primary_failure(
    failures: Iterable[PytestFailure], preferred_node_id: str | None = None
) -> PytestFailure | None:
    items = tuple(failures)
    preferred = tuple(item for item in items if item.node_id == preferred_node_id)
    candidates = preferred or items
    return min(
        candidates,
        key=lambda item: (PHASE_PRIORITY[item.phase], item.node_id),
        default=None,
    )


def extract_failed_node_ids(text: str) -> set[str]:
    return {failure.node_id for failure in parse_text_failures(text)}


def _parse_summary(
    lines: list[str],
    summary_index: int,
    match: re.Match[str],
) -> PytestFailure:
    node_id = re.sub(r"/+", "/", match.group("node").replace("\\", "/"))
    traceback = _adjacent_traceback(lines, summary_index, node_id)
    exception_type, summary = _failure_detail(traceback, match.groupdict().get("detail"))
    return PytestFailure(
        node_id=node_id,
        phase=_failure_phase(traceback, match),
        outcome="failed",
        exception_type=exception_type,
        summary=summary,
        traceback=traceback,
        duration_ms=0,
    )


def _adjacent_traceback(
    lines: list[str], summary_index: int, node_id: str
) -> str:
    candidates = lines[:summary_index]
    leaf = node_id.rsplit("::", 1)[-1]
    section_start = next(
        (
            index
            for index in range(len(candidates) - 1, -1, -1)
            if SECTION_RE.fullmatch(candidates[index].strip()) and leaf in candidates[index]
        ),
        None,
    )
    if section_start is not None:
        candidates = candidates[section_start:]
        next_section = next(
            (
                index
                for index, line in enumerate(candidates[1:], 1)
                if SECTION_RE.fullmatch(line.strip())
            ),
            None,
        )
        next_summary = next(
            (index for index, line in enumerate(candidates) if _summary_match(line)),
            None,
        )
        boundaries = (boundary for boundary in (next_section, next_summary) if boundary is not None)
        boundary = min(boundaries, default=None)
        if boundary is not None:
            candidates = candidates[:boundary]
    traceback = "\n".join(candidates).strip().replace("\\", "/")
    return re.sub(r"/+", "/", traceback)


def _failure_detail(traceback: str, detail: str | None) -> tuple[str | None, str]:
    for line in reversed(traceback.splitlines()):
        match = EXCEPTION_RE.fullmatch(line.strip())
        if match:
            return match.group("exception"), (match.group("summary") or "").strip()
    if detail:
        match = DETAIL_EXCEPTION_RE.fullmatch(detail.strip())
        if match:
            return match.group("exception"), (match.group("summary") or "").strip()
        return None, detail.strip()
    return None, ""


def _failure_phase(
    traceback: str,
    match: re.Match[str],
) -> str:
    context = traceback.lower()
    if "error at setup" in context:
        return "setup"
    if "error at teardown" in context:
        return "teardown"
    if "error collecting" in context or "collecting" in match.group(0).lower():
        return "collection"
    return "call"


def _related_paths(traceback: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(path.replace("\\", "/") for path in PATH_RE.findall(traceback)))


def _summary_match(line: str) -> re.Match[str] | None:
    return next(
        (match for pattern in SUMMARY_PATTERNS if (match := pattern.fullmatch(line.strip()))),
        None,
    )
