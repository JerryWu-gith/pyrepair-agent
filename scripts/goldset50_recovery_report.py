"""Saved-results-only STAGED reports; no generation or grading entry point."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.evaluation import goldset_live, goldset_pack, live_comparison
from benchmarks.evaluation.comparison_budget import _calls, read_usage, write_new
from benchmarks.evaluation.comparison_continuation import _add_usage
from benchmarks.evaluation.comparison_journal import _events
from benchmarks.evaluation.comparison_pack import file_hash
from benchmarks.evaluation.comparison_reporting import render_comparison, summarize_comparison
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.experiment import digest
from benchmarks.evaluation.goldset_dataset import verify_dataset
from benchmarks.evaluation.goldset_reporting import summarize_goldset
from benchmarks.evaluation.live_plan import _overlaps, absolute_path
from scripts.goldset50_recovery import (
    PATH_FIELDS,
    _copy_new,
    _no_locks,
    _old_records,
    _protected,
    tree_identity,
    validate_descriptor,
)


def _goldset_markdown(result):
    lines = [
        "# STAGED — goldset50 repeated workflow comparison",
        "",
        f"Finished {result['finished']}/{result['planned']}; complete: {result['complete']}.",
        "",
        "Three equally weighted repeats. Incomplete/technical groups have no full success rate.",
        "",
        "| Group | Method | Accepted/planned | Finished | Technical | 3/3 tasks | Rate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["groups"]:
        rate = "unknown/incomplete" if row["success_rate"] is None else f"{row['success_rate']:.1%}"
        lines.append(
            f"| {row['group']} | {row['method']} | {row['accepted']}/{row['planned']} | {row['finished']} | {row['technical_errors']} | {row['three_of_three_tasks']} | {rate} |"
        )
    lines.extend(
        [
            "",
            "## Every task, not best-of-three",
            "",
            "| Task | Source/use | Method | Accepted | Finished |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in result["tasks"]:
        lines.append(
            f"| {row['case_id']} | {row['source_kind']}/{row['split']} | {row['method']} | {row['accepted_repeats']}/3 | {row['finished_repeats']}/3 |"
        )
    return "\n".join(lines) + "\n"


def report_recovery(descriptor, output):
    """Validate and combine the original129 plus saved stage171, never run slots."""
    validate_descriptor(descriptor)
    destination = absolute_path(output)
    sources = [absolute_path(descriptor[n]) for n in PATH_FIELDS]
    sources.extend(Path(p) for p in descriptor["checkpoint"]["critical_hashes"])
    sources.append(Path(__file__).resolve().parents[1] / "scripts")
    if any(_overlaps(destination, p) for p in sources):
        raise ValueError("combined report overlaps recovery evidence or sources")
    if destination.exists():
        raise FileExistsError("combined report output already exists")
    stage, original = Path(descriptor["output"]), Path(descriptor["original_output"])
    _no_locks(stage)
    live_comparison._check_supervision(stage)
    execution = read_json(stage / "execution.json")
    if (
        set(execution) != {"version", "plan_hash", "authorization_hash", "offline_owned_executor"}
        or execution["version"] != 1
        or execution["plan_hash"] != digest(descriptor["plan"])
        or execution["offline_owned_executor"] is not False
        or not isinstance(execution["authorization_hash"], str)
        or len(execution["authorization_hash"]) != 64
    ):
        raise ValueError("stage execution identity changed")
    cases = verify_dataset(Path(descriptor["dataset"]))
    _protected(
        {**{n: absolute_path(descriptor[n]) for n in PATH_FIELDS}, "output": destination},
        cases,
        descriptor["plan"],
    )
    pack = goldset_pack.verify_goldset_pack(Path(descriptor["pack"]), cases)
    old_plan = goldset_live.describe_plan(descriptor["pack"], pack, original, "formal", 5550)
    old_records = _old_records(original, live_comparison._selected_pack(pack, old_plan))
    selected = live_comparison._selected_pack(pack, descriptor["plan"])
    if read_json(stage / "run.json") != {"pack": selected["identity_hash"], "simulation": False}:
        raise ValueError("stage run identity changed")
    states = _events(stage, selected, False)
    records = [
        history[-1]["data"]
        for history in states.values()
        if history and history[-1]["event"] == "terminal"
    ]
    config, calls = _calls(stage / "q")
    started = {slot for slot, history in states.items() if history}
    allowed = {s["slot"]: s for s in descriptor["plan"]["slots"][1:]}
    if config != {"version": 1, "limit": 3145} or any(
        c["slot"] not in started
        or c["slot"] not in allowed
        or c["slot_limit"] != descriptor["plan"]["slot_limits"][allowed[c["slot"]]["method"]]
        for c in calls.values()
    ):
        raise ValueError("stage usage is not bound to recovery generation slots")
    usage = _add_usage(read_usage(original / "q"), read_usage(stage / "q"))
    if usage["reserved_calls"] > 5550:
        raise ValueError("cumulative original budget exceeded")
    combined = old_records[:129] + records
    summary = summarize_comparison(pack, combined, usage=usage, execution_mode="formal")
    summary.update(
        kind="STAGED — controlled goldset50 recovery",
        performance_measured=True,
        frozen_pack_hash=pack["identity_hash"],
        execution_plan_hash=digest(descriptor["plan"]),
    )
    for group in summary["groups"]:
        if group["unrun"] or group["technical_errors"]:
            group["core_acceptance_rate"] = None
    # All sources were qualified before output creation. Only real timing bytes are copied.
    destination.mkdir(parents=True, exist_ok=False)
    timing_sources = {}
    for index, _record in enumerate(combined):
        source_index = index if index < 129 else index - 129
        root = original if index < 129 else stage
        source = root / f"s{source_index:04d}/g/grading-time.json"
        if source.is_file():
            rel = f"s{index:04d}/g/grading-time.json"
            _copy_new(source, destination / rel)
            timing_sources[rel] = {"path": str(source), "sha256": file_hash(source)}
    goldset = summarize_goldset(cases, summary, destination)
    goldset["kind"] = "STAGED — goldset50 repeated workflow comparison"
    summary.update(
        goldset=goldset,
        timing_sources=timing_sources,
        original_technical_error=old_records[-1],
        checkpoint_hash=descriptor["plan"]["checkpoint_hash"],
        original_output=str(original),
        stage_output=str(stage),
        original_tree=descriptor["checkpoint"]["original_tree"],
        regrade_tree=descriptor["checkpoint"]["regrade_tree"],
        stage_tree=tree_identity(stage),
        quotas={
            "original": read_json(original / "q/budget.json"),
            "stage": config,
            "original_usage": read_usage(original / "q"),
            "stage_usage": read_usage(stage / "q"),
        },
        bootstrap=read_json(stage / "bootstrap.json"),
        technical_overhead={
            "original_error_grade": str(original / "s0129/g"),
            "original_error_timing": read_json(original / "s0129/g/grading-time.json")
            if (original / "s0129/g/grading-time.json").is_file()
            else None,
            "regrade_diagnostic": read_json(Path(descriptor["regrade"]) / "diagnostic.json")
            if (Path(descriptor["regrade"]) / "diagnostic.json").is_file()
            else None,
            "note": "Original error retained separately; reused candidate method time counted once. Missing grading timing is unknown, never inferred from wall-clock gaps.",
        },
    )
    if (
        tree_identity(original) != descriptor["checkpoint"]["original_tree"]
        or tree_identity(Path(descriptor["regrade"])) != descriptor["checkpoint"]["regrade_tree"]
    ):
        raise ValueError("frozen source tree changed during reporting")
    write_new(destination / "summary.json", summary)
    write_new(destination / "goldset-summary.json", goldset)
    provenance = (
        "\n## STAGED provenance\n\nThe original environment_error is preserved, not erased. Original129 normal terminal records + recovery171 planned slots. The first recovery slot reuses the original candidate and separately validated grade, with zero new generation.\n\n"
        + "```json\n"
        + json.dumps(
            {
                k: summary[k]
                for k in (
                    "original_output",
                    "stage_output",
                    "checkpoint_hash",
                    "quotas",
                    "bootstrap",
                    "technical_overhead",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n```\n\nFull tree identities and timing-source hashes are saved in summary.json.\n"
    )
    for name, text in (
        ("report.md", render_comparison(summary) + provenance),
        ("goldset-report.md", _goldset_markdown(goldset) + provenance),
    ):
        with (destination / name).open("x", encoding="utf-8") as stream:
            stream.write(text)
    return summary
