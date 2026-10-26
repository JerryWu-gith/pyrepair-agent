"""Saved-results-only adapter-fixed STAGED comparison; no generation or grading."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.evaluation import goldset_pack, live_comparison
from benchmarks.evaluation.comparison_budget import _calls, read_usage, write_new
from benchmarks.evaluation.comparison_continuation import _add_usage
from benchmarks.evaluation.comparison_journal import _events
from benchmarks.evaluation.comparison_pack import file_hash
from benchmarks.evaluation.comparison_reporting import render_comparison, summarize_comparison
from benchmarks.evaluation.container_protocol import read_json
from benchmarks.evaluation.experiment import digest
from benchmarks.evaluation.goldset_dataset import verify_dataset
from benchmarks.evaluation.goldset_reporting import summarize_goldset
from benchmarks.evaluation.live_plan import SLOT_LIMITS, _overlaps, absolute_path
from scripts import goldset50_adapter_resume as adapter
from scripts import goldset50_recovery as recovery
from scripts.goldset50_recovery_report import _goldset_markdown


def _combine(pack, previous, records, usage):
    summary = summarize_comparison(pack, previous + records, usage=usage, execution_mode="formal")
    summary.update(
        kind="STAGED — adapter-only hash-baseline fix",
        performance_measured=True,
        frozen_pack_hash=pack["identity_hash"],
    )
    for group in summary["groups"]:
        if group["unrun"] or group["technical_errors"]:
            group["core_acceptance_rate"] = None
    return summary


def _save_tree(tree, destination, label):
    """Keep the existing 4 MiB artifact guard, including after long Agent runs."""
    items = sorted(tree["files"].items())
    chunks = []
    for offset in range(0, len(items), 1000):
        relative = f"provenance/{label}-{offset // 1000:04d}.json"
        path = destination / relative
        write_new(
            path,
            {
                "path": tree["path"],
                "tree_hash": tree["hash"],
                "files": dict(items[offset : offset + 1000]),
            },
        )
        chunks.append({"path": relative, "sha256": file_hash(path)})
    return {"path": tree["path"], "hash": tree["hash"], "file_count": len(items), "chunks": chunks}


def report_resume(descriptor, output):
    """Combine old129 + recovery4 + saved third stage against the original 300 slots."""
    adapter.validate_descriptor(descriptor)
    destination = absolute_path(output)
    paths = {n: absolute_path(descriptor[n]) for n in adapter.PATH_FIELDS}
    stage = paths["output"]
    cases = verify_dataset(paths["dataset"])
    adapter._protected({**paths, "output": destination}, cases, descriptor["plan"])
    protected = [
        stage,
        *(Path(t["path"]) for t in descriptor["evidence"]["trees"].values()),
        *(Path(n) for n in descriptor["evidence"]["critical_hashes"]),
    ]
    if any(_overlaps(destination, p) for p in protected):
        raise ValueError("adapter report overlaps saved stages or authority")
    if destination.exists():
        raise FileExistsError("adapter report output already exists")
    recovery._no_locks(stage)
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
        raise ValueError("adapter stage execution identity changed")
    pack = goldset_pack.verify_goldset_pack(paths["new_pack"], cases)
    old = read_json(paths["original_pack"] / "pack.json")
    _evidence, previous = adapter._historical(paths, old, read_json(paths["checkpoint"]))
    selected = live_comparison._selected_pack(pack, descriptor["plan"])
    if read_json(stage / "run.json") != {"pack": selected["identity_hash"], "simulation": False}:
        raise ValueError("adapter stage run identity changed")
    states = _events(stage, selected, False)
    records = [h[-1]["data"] for h in states.values() if h and h[-1]["event"] == "terminal"]
    config, calls = _calls(stage / "q")
    allowed = {s["slot"]: s for s in descriptor["plan"]["slots"]}
    started = {slot for slot, history in states.items() if history}
    if config != {"version": 1, "limit": 3107} or any(
        c["slot"] not in started
        or c["slot"] not in allowed
        or c["slot_limit"] != SLOT_LIMITS[allowed[c["slot"]]["method"]]
        or (c["role"] == "single-shot") != (allowed[c["slot"]]["method"] == "single-shot")
        for c in calls.values()
    ):
        raise ValueError("adapter stage usage is not bound to fresh generation slots")
    usages = {
        name: read_usage(root / "q")
        for name, root in (
            ("original", paths["original_output"]),
            ("recovery", paths["recovery_output"]),
            ("adapter", stage),
        )
    }
    usage = _add_usage(_add_usage(usages["original"], usages["recovery"]), usages["adapter"])
    if usage["reserved_calls"] > 3613 or usage["reserved_calls"] > 5550:
        raise ValueError("adapter cumulative budget exceeded")
    stage_tree = recovery.tree_identity(stage)
    summary = _combine(pack, previous, records, usage)
    summary.update(
        execution_plan_hash=digest(descriptor["plan"]),
        checkpoint_hash=descriptor["plan"]["checkpoint_hash"],
        technical_events=descriptor["evidence"]["technical_events"],
        adapter_change=descriptor["evidence"]["source_change"],
        original_runtime=descriptor["evidence"]["original_runtime"],
        new_runtime=descriptor["evidence"]["new_runtime"],
        original_pack_hash=descriptor["evidence"]["original_pack_hash"],
        new_pack_hash=pack["identity_hash"],
        stage_sources={n: descriptor[n] for n in ("original_output", "recovery_output", "output")},
        preflight=descriptor["evidence"]["preflight"],
        quotas={
            "limits": {"original": 5550, "recovery": 3145, "adapter": 3107},
            "usage": usages,
            "cumulative_original_limit": 5550,
            "cumulative_maximum": 3613,
        },
        retained_normal_slots=133,
        new_generation_slots=167,
        timing_note="Only genuine saved timings copied. Missing timings remain unknown; old technical events retained separately.",
    )
    destination.mkdir(parents=True, exist_ok=False)
    summary["source_trees"] = {
        name: _save_tree(tree, destination, name)
        for name, tree in descriptor["evidence"]["trees"].items()
    }
    summary["stage_tree"] = _save_tree(stage_tree, destination, "adapter")
    timing_sources = {}
    roots = [
        (paths["original_output"], range(129)),
        (paths["recovery_output"], range(4)),
        (stage, range(len(records))),
    ]
    combined_index = 0
    for root, indices in roots:
        for source_index in indices:
            source = root / f"s{source_index:04d}/g/grading-time.json"
            if source.is_file():
                rel = f"s{combined_index:04d}/g/grading-time.json"
                recovery._copy_new(source, destination / rel)
                timing_sources[rel] = {"path": str(source), "sha256": file_hash(source)}
            combined_index += 1
    summary["timing_sources"] = timing_sources
    goldset = summarize_goldset(cases, summary, destination)
    goldset["kind"] = "STAGED — adapter-only hash-baseline fix"
    summary["goldset"] = goldset
    adapter._check_critical(descriptor)
    if (
        any(
            recovery.tree_identity(Path(t["path"])) != t
            for t in descriptor["evidence"]["trees"].values()
        )
        or recovery.tree_identity(stage) != stage_tree
    ):
        raise ValueError("saved stage source changed during reporting")
    write_new(destination / "summary.json", summary)
    write_new(destination / "goldset-summary.json", goldset)
    provenance = (
        "\n## STAGED adapter-only provenance\n\n"
        + (
            "Original129 + recovery4 ordinary records retained; only the 167 previously uncalled slots use the adapter-fixed runtime. "
            "Both historical technical events remain in the audit record. No old generation or grading was replayed.\n\n"
        )
        + "```json\n"
        + json.dumps(
            {
                k: summary[k]
                for k in (
                    "stage_sources",
                    "adapter_change",
                    "original_runtime",
                    "new_runtime",
                    "technical_events",
                    "quotas",
                    "timing_note",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n```\n"
    )
    for name, text in (
        ("report.md", render_comparison(summary)),
        ("goldset-report.md", _goldset_markdown(goldset)),
    ):
        with (destination / name).open("x", encoding="utf-8") as stream:
            stream.write(text + provenance)
    return summary
