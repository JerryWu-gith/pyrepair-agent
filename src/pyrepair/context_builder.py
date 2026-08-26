from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .models import FailureReport
from .repository_index import ModuleInfo, RepositoryIndex, SymbolInfo, build_repository_index

MAX_CONTEXT_CHARS = 16_000
MAX_SNIPPETS = 8
MAX_SNIPPET_CHARS = 2_500
MAX_OVERVIEW_CHARS = 2_000

SCORES = {
    "traceback_file": 100,
    "failed_test": 90,
    "exception_symbol": 70,
    "test_import": 60,
    "import_neighbor": 40,
    "summary_identifier": 30,
    "test_module_similarity": 20,
    "keyword": 10,
}

_PATH_LINE = re.compile(r"(?P<path>[A-Za-z0-9_./\\-]+\.py):(?P<line>\d+)")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


@dataclass(frozen=True)
class ContextSnippet:
    path: str
    start_line: int
    end_line: int
    symbol: str | None
    reason: str
    score: int
    content: str


@dataclass(frozen=True)
class ContextBundle:
    repo_overview: str
    snippets: tuple[ContextSnippet, ...]
    related_files: tuple[str, ...]
    total_chars: int
    truncated: bool


@dataclass
class _Candidate:
    module: ModuleInfo
    reasons: dict[str, int]
    trace_line: int | None = None
    symbol: SymbolInfo | None = None

    @property
    def score(self) -> int:
        return sum(self.reasons.values())


class ContextBuilder:
    def build(
        self,
        root: Path,
        report: FailureReport,
        index: RepositoryIndex | None = None,
    ) -> ContextBundle:
        try:
            repository_index = index or build_repository_index(root)
            return self._build(root.resolve(), report, repository_index)
        except Exception:  # noqa: BLE001 - context collection must degrade without aborting repair
            return empty_context_bundle()

    def _build(
        self,
        root: Path,
        report: FailureReport,
        index: RepositoryIndex,
    ) -> ContextBundle:
        overview, overview_truncated = _repository_overview(index)
        candidates: dict[str, _Candidate] = {}

        def add(path: str, reason: str, *, line: int | None = None) -> None:
            normalized = _normalize_path(path)
            module = index.module_for_path(normalized)
            if module is None or module.parse_error is not None:
                return
            candidate = candidates.setdefault(normalized, _Candidate(module, {}))
            candidate.reasons[reason] = SCORES[reason]
            if line is not None:
                candidate.trace_line = line

        failed_test = _failed_test_path(report.node_id)
        if failed_test:
            add(failed_test, "failed_test")

        trace_locations = _trace_locations(report.traceback)
        for path, line in trace_locations.items():
            add(path, "traceback_file", line=line)

        for path in report.related_files:
            if path == failed_test or path in trace_locations:
                continue
            add(path, "import_neighbor")

        if failed_test:
            for module in index.import_neighbors(failed_test):
                add(module.path, "test_import")

        for path in trace_locations:
            for module in index.import_neighbors(path):
                add(module.path, "import_neighbor")

        traceback_identifiers = _identifiers(report.traceback)
        summary_identifiers = _identifiers(report.summary)
        for identifier in sorted(traceback_identifiers):
            for symbol in index.symbols_named(identifier):
                add(symbol.path, "exception_symbol")
                candidate = candidates[symbol.path]
                candidate.symbol = _prefer_symbol(candidate.symbol, symbol)

        for identifier in sorted(summary_identifiers):
            for symbol in index.symbols_named(identifier):
                add(symbol.path, "summary_identifier")
                candidate = candidates[symbol.path]
                candidate.symbol = _prefer_symbol(candidate.symbol, symbol)

        if failed_test:
            stem = Path(failed_test).stem.removeprefix("test_")
            for module in index.modules:
                if stem and stem in Path(module.path).stem and module.path != failed_test:
                    add(module.path, "test_module_similarity")

        keywords = traceback_identifiers | summary_identifiers
        if keywords:
            for module in index.modules:
                if module.parse_error is not None:
                    continue
                source = _read_source(root, module.path)
                if source is not None and any(word in source for word in keywords):
                    add(module.path, "keyword")

        ranked = sorted(
            candidates.values(),
            key=lambda item: (
                -item.score,
                item.module.path,
                item.symbol.start_line if item.symbol else 0,
                item.symbol.name if item.symbol else "",
            ),
        )
        snippets: list[ContextSnippet] = []
        total_chars = len(overview)
        truncated = overview_truncated

        for candidate in ranked:
            if len(snippets) >= MAX_SNIPPETS:
                truncated = True
                break
            snippet, content_truncated = _candidate_snippet(root, candidate)
            if snippet is None:
                continue
            if total_chars + len(snippet.content) > MAX_CONTEXT_CHARS:
                truncated = True
                continue
            snippets.append(snippet)
            total_chars += len(snippet.content)
            truncated = truncated or content_truncated

        if len(snippets) < len(ranked):
            truncated = True

        return ContextBundle(
            repo_overview=overview,
            snippets=tuple(snippets),
            related_files=tuple(sorted(item.path for item in snippets)),
            total_chars=total_chars,
            truncated=truncated,
        )


def empty_context_bundle() -> ContextBundle:
    return ContextBundle("", (), (), 0, False)


def _repository_overview(index: RepositoryIndex) -> tuple[str, bool]:
    lines = ["Python repository modules:"]
    for module in index.modules:
        symbols = ", ".join(item.name for item in module.symbols[:8]) or "no symbols"
        suffix = " [SyntaxError]" if module.parse_error else ""
        lines.append(f"- {module.path}: {symbols}{suffix}")
    overview = "\n".join(lines)
    if len(overview) <= MAX_OVERVIEW_CHARS:
        return overview, False
    marker = "\n[TRUNCATED]"
    return overview[: MAX_OVERVIEW_CHARS - len(marker)] + marker, True


def _candidate_snippet(root: Path, candidate: _Candidate) -> tuple[ContextSnippet | None, bool]:
    source = _read_source(root, candidate.module.path)
    if source is None:
        return None, False
    lines = source.splitlines()
    trace_symbol = _symbol_at_line(candidate.module, candidate.trace_line)
    symbol = trace_symbol or candidate.symbol
    if symbol is not None:
        start_line = symbol.start_line
        end_line = min(symbol.end_line, len(lines))
    elif candidate.trace_line is not None:
        start_line = max(1, candidate.trace_line - 20)
        end_line = min(len(lines), candidate.trace_line + 20)
    else:
        start_line = 1
        end_line = len(lines)

    original_range = (start_line, end_line)
    center_line = candidate.trace_line
    if center_line is not None and not start_line <= center_line <= end_line:
        center_line = None
    start_line, end_line = _bounded_line_range(
        candidate.module.path,
        lines,
        start_line,
        end_line,
        center_line,
    )
    raw = "\n".join(lines[start_line - 1 : end_line])
    content, content_truncated = _wrap_untrusted(candidate.module.path, raw)
    return (
        ContextSnippet(
            path=candidate.module.path,
            start_line=start_line,
            end_line=end_line,
            symbol=symbol.name if symbol else None,
            reason="+".join(sorted(candidate.reasons)),
            score=candidate.score,
            content=content,
        ),
        content_truncated or (start_line, end_line) != original_range,
    )


def _bounded_line_range(
    path: str,
    lines: list[str],
    start_line: int,
    end_line: int,
    center_line: int | None,
) -> tuple[int, int]:
    raw = "\n".join(lines[start_line - 1 : end_line])
    if not _wrap_untrusted(path, raw)[1]:
        return start_line, end_line

    if center_line is None:
        selected_start = selected_end = start_line
    else:
        selected_start = selected_end = center_line

    while True:
        choices: list[tuple[int, int]] = []
        if selected_start > start_line and selected_end < end_line:
            choices.append((selected_start - 1, selected_end + 1))
        if selected_end < end_line:
            choices.append((selected_start, selected_end + 1))
        if selected_start > start_line:
            choices.append((selected_start - 1, selected_end))

        expanded = next(
            (
                choice
                for choice in choices
                if not _wrap_untrusted(
                    path,
                    "\n".join(lines[choice[0] - 1 : choice[1]]),
                )[1]
            ),
            None,
        )
        if expanded is None:
            return selected_start, selected_end
        selected_start, selected_end = expanded


def _wrap_untrusted(path: str, raw: str) -> tuple[str, bool]:
    header = f'<repository_data path="{escape(path, quote=True)}" trusted="false">\n'
    footer = "\n</repository_data>"
    safe_raw = escape(raw, quote=False)
    available = MAX_SNIPPET_CHARS - len(header) - len(footer)
    marker = "\n[TRUNCATED]"
    truncated = len(safe_raw) > available
    if truncated:
        safe_raw = safe_raw[: available - len(marker)] + marker
    return header + safe_raw + footer, truncated


def _read_source(root: Path, path: str) -> str | None:
    try:
        return (root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _trace_locations(traceback: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for match in _PATH_LINE.finditer(traceback):
        result[_normalize_path(match.group("path"))] = int(match.group("line"))
    return result


def _failed_test_path(node_id: str | None) -> str | None:
    if not node_id:
        return None
    path = node_id.split("::", 1)[0]
    return _normalize_path(path) if path.endswith(".py") else None


def _identifiers(text: str) -> set[str]:
    ignored = {"assert", "error", "failed", "failure", "line", "pytest", "traceback"}
    return {item for item in _IDENTIFIER.findall(text) if item.lower() not in ignored}


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _prefer_symbol(current: SymbolInfo | None, new: SymbolInfo) -> SymbolInfo:
    if current is None:
        return new
    return min((current, new), key=lambda item: (item.start_line, item.name))


def _symbol_at_line(module: ModuleInfo, line: int | None) -> SymbolInfo | None:
    if line is None:
        return None
    matches = [item for item in module.symbols if item.start_line <= line <= item.end_line]
    if not matches:
        return None
    return min(matches, key=lambda item: (item.end_line - item.start_line, item.start_line))
