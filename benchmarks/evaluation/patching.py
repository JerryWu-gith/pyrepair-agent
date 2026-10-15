"""Deliberately narrow patch format: existing, allowlisted UTF-8 source only."""

from __future__ import annotations

import difflib
import os
import re
import subprocess
from pathlib import Path

from pyrepair.models import FileChange, PatchSnapshot
from pyrepair.policy import PatchPolicyGate

from .cases import CaseError, EvaluationCase, contained, safe_relative


class PatchRejected(ValueError):
    pass


def patch_paths(text: str) -> tuple[str, ...]:
    lines = text.splitlines(keepends=True)
    paths = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- a/") or i + 1 >= len(lines):
            raise PatchRejected("only plain unified diffs are supported")
        path = lines[i][6:].rstrip("\r\n")
        try:
            safe_relative(path)
        except CaseError as exc:
            raise PatchRejected(str(exc)) from exc
        if lines[i + 1].rstrip("\r\n") != "+++ b/" + path or path in paths:
            raise PatchRejected("renamed, duplicate or non-source patch header")
        paths.append(path)
        i += 2
        hunks = 0
        while i < len(lines) and lines[i].startswith("@@ "):
            match = re.fullmatch(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@[^\r\n]*\r?\n", lines[i])
            if not match:
                raise PatchRejected("invalid hunk")
            old, new = (int(n) if n is not None else 1 for n in match.groups())
            i += 1
            while old or new:
                if i >= len(lines) or not lines[i].startswith((" ", "+", "-")):
                    raise PatchRejected("incomplete hunk")
                prefix = lines[i][0]
                old -= prefix in " -"
                new -= prefix in " +"
                if min(old, new) < 0:
                    raise PatchRejected("invalid hunk counts")
                i += 1
                if i < len(lines) and lines[i].startswith("\\ No newline at end of file"):
                    i += 1
            hunks += 1
        if not hunks:
            raise PatchRejected("missing hunks")
    if not paths:
        raise PatchRejected("empty patch")
    return tuple(paths)


def apply_patch_checked(case: EvaluationCase, repo: Path, text: str) -> tuple[str, ...]:
    paths = patch_paths(text)
    if not set(paths) <= set(case.allowed_source_paths):
        raise PatchRejected("patch touches a path outside allowed_source_paths")
    before = {p: contained(repo, p).read_text(encoding="utf-8") for p in paths}
    # read_text and the Agent's editor use universal newlines. Normalize ONLY
    # the disposable source copy; never change the original task assets.
    for p, old in before.items():
        contained(repo, p).write_text(old, encoding="utf-8", newline="\n")
    # An empty local Git repository prevents discovery of a parent checkout.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    commands = (
        ["init", "--quiet"],
        ["apply", "--check", "--whitespace=nowarn", "-"],
        ["apply", "--whitespace=nowarn", "-"],
    )
    for args in commands:
        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", *args],
            cwd=repo,
            env=env,
            input=text.encode("utf-8") if args[0] == "apply" else None,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode:
            raise PatchRejected(result.stderr.decode("utf-8", errors="replace").strip())
    changes = []
    for p, old in before.items():
        new = contained(repo, p).read_text(encoding="utf-8")
        diff = list(
            difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), fromfile="a/" + p, tofile="b/" + p
            )
        )
        if old != new:
            changes.append(
                FileChange(
                    p,
                    old,
                    new,
                    "".join(diff),
                    sum(x.startswith("+") and not x.startswith("+++") for x in diff),
                    sum(x.startswith("-") and not x.startswith("---") for x in diff),
                )
            )
    check = PatchPolicyGate().check(PatchSnapshot(tuple(changes)))
    if not changes or not check.allowed:
        raise PatchRejected("; ".join(check.violations) or "no effective source changes")
    return tuple(c.path for c in changes)
