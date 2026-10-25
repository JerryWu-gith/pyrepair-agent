"""Stratified repeated-evaluation reporting; no best-of-three substitution."""

from __future__ import annotations

import math
from pathlib import Path

from .catalog_source_cache import write_new_json
from .comparison_budget import checked_path
from .container_protocol import read_json

METHODS = ("single-shot", "full-agent")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _timings(rows):
    method = [r["duration_seconds"] for r in rows if _number(r.get("duration_seconds"))]
    grading = [r["grading_seconds"] for r in rows if _number(r.get("grading_seconds"))]
    return {
        "method_seconds_known": len(method),
        "method_seconds_total": sum(method),
        "method_seconds_mean": sum(method) / len(method) if method else None,
        "grading_seconds_known": len(grading),
        "grading_seconds_total": sum(grading),
        "grading_seconds_mean": sum(grading) / len(grading) if grading else None,
    }


def summarize_goldset(cases, summary, output: Path):
    by_id = {c.id: c for c in cases}
    rows = [dict(r) for r in summary["rows"]]
    expected = {(c.id, method, trial) for c in cases for method in METHODS for trial in (1, 2, 3)}
    if (
        len(rows) != len(expected)
        or {(r["case_id"], r["method"], r["trial"]) for r in rows} != expected
    ):
        raise ValueError("goldset report rows differ from the three-repeat schedule")
    measured = summary.get("performance_measured") is True
    output = checked_path(output).resolve()
    for index, row in enumerate(rows):
        row["grading_seconds"] = None
        timing = checked_path(output / f"s{index:04d}/g/grading-time.json")
        if timing.is_file():
            value = read_json(timing)
            if set(value) != {"duration_seconds"} or not _number(value["duration_seconds"]):
                raise ValueError("invalid independent grading timing")
            row["grading_seconds"] = value["duration_seconds"]
    finished = sum(r["status"] != "unrun" for r in rows)
    if summary["planned"] != len(rows) or summary["finished"] != finished:
        raise ValueError("reported finish counts differ from saved rows")
    tasks = []
    for case in cases:
        for method in METHODS:
            selected = [r for r in rows if (r["case_id"], r["method"]) == (case.id, method)]
            completed = sum(r["status"] != "unrun" for r in selected)
            technical = sum(r["status"] == "technical_error" for r in selected)
            accepted = sum(r.get("core_passed") is True for r in selected) if measured else None
            tasks.append(
                {
                    "case_id": case.id,
                    "source_kind": case.source_kind,
                    "split": case.split,
                    "repository": case.origin.get("repository"),
                    "method": method,
                    "planned_repeats": 3,
                    "finished_repeats": completed,
                    "technical_errors": technical,
                    "accepted_repeats": accepted,
                    "repeat_average_rate": accepted / 3
                    if measured and completed == 3 and not technical
                    else None,
                    "three_of_three": measured
                    and completed == 3
                    and not technical
                    and accepted == 3,
                    **_timings(selected),
                }
            )
    selections = {
        "all": set(by_id),
        "synthetic-dev": {c.id for c in cases if c.source_kind == "synthetic"},
        "opensource-all": {c.id for c in cases if c.source_kind == "opensource"},
        "opensource-known-dev": {
            c.id for c in cases if c.source_kind == "opensource" and c.split == "dev"
        },
        "opensource-holdout": {
            c.id for c in cases if c.source_kind == "opensource" and c.split == "holdout"
        },
    }
    for repo in sorted({c.origin["repository"] for c in cases if c.origin.get("repository")}):
        selections["repository:" + repo] = {
            c.id for c in cases if c.origin.get("repository") == repo
        }
    groups = []
    for group, ids in selections.items():
        if not ids:
            continue
        for method in METHODS:
            selected = [r for r in rows if r["case_id"] in ids and r["method"] == method]
            done = sum(r["status"] != "unrun" for r in selected)
            errors = sum(r["status"] == "technical_error" for r in selected)
            accepted = sum(r.get("core_passed") is True for r in selected) if measured else None
            groups.append(
                {
                    "group": group,
                    "method": method,
                    "tasks": len(ids),
                    "planned": len(selected),
                    "finished": done,
                    "unrun": len(selected) - done,
                    "technical_errors": errors,
                    "accepted": accepted,
                    "success_rate": accepted / len(selected)
                    if measured and done == len(selected) and not errors
                    else None,
                    "three_of_three_tasks": sum(
                        t["three_of_three"]
                        for t in tasks
                        if t["case_id"] in ids and t["method"] == method
                    )
                    if measured
                    else None,
                    **_timings(selected),
                }
            )
    return {
        "version": 1,
        "kind": "goldset50 repeated workflow comparison"
        if measured
        else "OFFLINE - NOT model performance",
        "model": "deepseek-flash",
        "case_count": len(cases),
        "planned": len(rows),
        "finished": finished,
        "complete": measured
        and finished == len(rows)
        and all(r["status"] != "technical_error" for r in rows),
        "performance_measured": measured,
        "groups": groups,
        "tasks": tasks,
        "usage": summary["usage"],
        "cost_rmb": None,
        "frozen_pack_hash": summary.get("frozen_pack_hash"),
        "execution_plan_hash": summary.get("execution_plan_hash"),
        "limitations": "Three fresh repeats, equally weighted; not best-of-three or equal-compute. Holdout means no project-specific Agent tuning, not proof of unseen pretraining. Selected core contract tests, not all upstream tests. Partial groups have no full success-rate estimate.",
    }


def save_goldset_report(cases, summary, output: Path):
    output = checked_path(output).resolve()
    result = summarize_goldset(cases, summary, output)
    write_new_json(output / "goldset-summary.json", result)
    lines = [
        "# PyRepair 五十题评测",
        "",
        f"完成 {result['finished']}/{result['planned']} 次方法运行；完整完成：{result['complete']}。",
        "",
        "三次重复等权统计，不取最好一次；未完成或技术异常分组不报告完整成功率。",
        "",
        "| 分组 | 方法 | 通过/计划 | 已完成 | 技术错误 | 三次全过题数 | 成功率 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["groups"]:
        rate = "未完成/不适用" if row["success_rate"] is None else f"{row['success_rate']:.1%}"
        lines.append(
            f"| {row['group']} | {row['method']} | {row['accepted']}/{row['planned']} | {row['finished']} | {row['technical_errors']} | {row['three_of_three_tasks']} | {rate} |"
        )
    lines.extend(
        [
            "",
            "## 每题三次结果",
            "",
            "| 题目 | 来源/用途 | 方法 | 通过重复 | 已完成 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in result["tasks"]:
        lines.append(
            f"| {row['case_id']} | {row['source_kind']}/{row['split']} | {row['method']} | {row['accepted_repeats']}/3 | {row['finished_repeats']}/3 |"
        )
    lines.extend(
        [
            "",
            "## 用量与边界",
            "",
            "调用和 token 记录见 goldset-summary.json 的 usage；方法耗时与独立评分耗时分别统计，缺失计时保持未知。未推断人民币费用。",
            "",
            result["limitations"],
            "",
        ]
    )
    with (output / "goldset-report.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return result
