# Conservative Project Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove local cache and temporary artifacts without changing any tracked PyRepair Agent project content.

**Architecture:** Keep the standard Python repository layout unchanged. Resolve every deletion target to an absolute path beneath `D:\Project\PyRepair Agent`, delete only the approved ignored artifacts, and use Git status plus required-path checks to verify that tracked content remains intact.

**Tech Stack:** PowerShell, Git

## Global Constraints

- Do not modify or move source code, tests, documentation, benchmarks, examples, scripts, PDFs, or repository configuration.
- Preserve `.venv/` if it exists.
- Never recursively delete the repository root or a path that has not been verified as its descendant.
- Remove only `.pytest_cache/`, `.ruff_cache/`, `.superpowers/`, `.worktrees/`, `tmp/`, `.coverage`, and `__pycache__/` directories outside `.venv/` and `.git/`.

---

### Task 1: Remove approved local artifacts and verify the repository

**Files:**
- Delete if present: `.pytest_cache/`
- Delete if present: `.ruff_cache/`
- Delete if present: `.superpowers/`
- Delete if present: `.worktrees/`
- Delete if present: `tmp/`
- Delete if present: `.coverage`
- Delete if present: repository `__pycache__/` directories, excluding `.venv/` and `.git/`
- Preserve: `.git/`, `.github/`, `benchmarks/`, `docs/`, `examples/`, `output/`, `scripts/`, `src/`, `tests/`

**Interfaces:**
- Consumes: the cleanup scope approved in `docs/superpowers/specs/2026-08-13-conservative-project-cleanup-design.md`
- Produces: a clean local working directory with no tracked-file changes

- [ ] **Step 1: Resolve and validate deletion targets**

Use PowerShell to convert each existing target to an absolute path. Reject any target equal to the repository root, outside the repository, or beneath `.git/` or `.venv/`.

- [ ] **Step 2: Delete only the validated targets**

Use PowerShell `Remove-Item -LiteralPath` on each validated explicit target. Locate `__pycache__` directories with `Get-ChildItem`, exclude `.git/` and `.venv/`, sort deepest paths first, validate them, and delete them with `Remove-Item -LiteralPath -Recurse -Force`.

- [ ] **Step 3: Verify required project paths remain**

Run checks for `.git`, `.github`, `benchmarks`, `docs`, `examples`, `output`, `scripts`, `src`, and `tests`. Expected: every path exists.

- [ ] **Step 4: Verify cleanup results and Git state**

Run `git status --short` and list any remaining approved artifact paths. Expected: Git reports no deletion or modification of tracked project files, and none of the approved cleanup targets remain.
