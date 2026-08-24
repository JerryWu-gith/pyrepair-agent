import re

from .models import FailureReport, TestRun

FAILED_RE = re.compile(
    r"^FAILED\s+(?P<node>\S+)\s+-\s+"
    r"(?:(?P<exc>[\w.]+):\s*)?(?P<summary>.*)$",
    re.MULTILINE,
)
PATH_RE = re.compile(r"(?m)^([\w./\\-]+\.py):\d+")


class PytestParser:
    def parse(self, run: TestRun) -> FailureReport:
        raw = "\n".join(part for part in (run.stdout, run.stderr) if part)
        match = FAILED_RE.search(raw)
        related = tuple(
            dict.fromkeys(path.replace("\\", "/") for path in PATH_RE.findall(raw))  # fromkeys 把值都设成 None不在乎值，只借用键集合来实现去重+保序
        )
        if not match:
            return FailureReport(
                node_id=None,
                exception_type=None,
                traceback=raw[-6000:],
                summary=raw[-500:],
                related_files=related,
                parseable=False,
            )
        return FailureReport(
            node_id=match.group("node"),
            exception_type=match.group("exc"),
            traceback=raw[-6000:],
            summary=match.group("summary").strip(),
            related_files=related,
            parseable=True,
        )


def extract_failed_node_ids(text: str) -> set[str]:
    return {match.group("node") for match in FAILED_RE.finditer(text)}
