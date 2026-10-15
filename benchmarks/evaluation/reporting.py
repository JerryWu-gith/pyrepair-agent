"""Pure statistics. Pending trials and unknown costs remain explicitly unknown."""

from __future__ import annotations

from collections import Counter
from statistics import median

DECIDABLE_FAILURES = {"no_patch", "patch_rejected", "visible_failed", "hidden_failed", "timeout"}


def summarize(experiment: dict, records: list[dict]) -> dict:
    all_records = records
    records = [r for r in all_records if not r.get("pending")]
    identity = experiment["identity"]
    planned = len(identity["cases"]) * identity["trials"]
    completed = len(records)
    successes = sum(r["passed"] for r in records)
    known = {role: {"prompt_tokens": 0, "completion_tokens": 0} for role in ("repair", "review")}
    complete_cost = completed == planned and all(r.get("cost_complete", False) for r in all_records)
    for record in all_records:
        for execution in [record["agent"], *record.get("interrupted_usage", [])]:
            for role, counters in known.items():
                for field in counters:
                    value = execution.get("usage", {}).get(role, {}).get(field)
                    if type(value) is int and value >= 0:
                        counters[field] += value
                    else:
                        complete_cost = False
    stable = 0
    solved = 0
    for case in identity["cases"]:
        rows = [r for r in records if r["case_id"] == case["id"]]
        solved += any(r["passed"] for r in rows)
        stable += len(rows) == identity["trials"] and all(r["passed"] for r in rows)
    accepted = [
        r
        for r in records
        if r["agent"]["status"] == "success"
        and r["grade"]["status"] in {"passed", *DECIDABLE_FAILURES}
    ]
    durations = [r["agent"].get("duration_seconds") for r in records]
    durations = [x for x in durations if isinstance(x, (int, float))]
    return {
        "planned": planned,
        "completed": completed,
        "successes": successes,
        "current_pass_rate": successes / completed if completed else None,
        "final_pass_rate": successes / planned if completed == planned else None,
        "first_attempt_pass_rate": sum(
            r["passed"] and r["agent"].get("attempts") == 1 for r in records
        )
        / completed
        if completed
        else None,
        "stable_cases": stable if identity["trials"] > 1 else None,
        "solved_at_least_once": solved,
        "false_positives": sum(r["grade"]["status"] != "passed" for r in accepted),
        "false_positive_denominator": len(accepted),
        "ungraded": sum(
            r["grade"]["status"] in {"grader_error", "environment_error", "not_run"}
            for r in records
        ),
        "grade_statuses": dict(Counter(r["grade"]["status"] for r in records)),
        "agent_statuses": dict(Counter(r["agent"]["status"] for r in records)),
        "interrupted_executions": sum(r.get("interrupted_executions", 0) for r in all_records),
        "unfinished_executions": sum(bool(r.get("pending")) for r in all_records),
        "known_tokens": known,
        "tokens": {
            role: {field: value if complete_cost else None for field, value in counts.items()}
            for role, counts in known.items()
        },
        "median_agent_seconds": median(durations) if durations else None,
        "grader_seconds": sum(r.get("grader_seconds", 0) for r in records),
        "tool_calls_known": sum(r["agent"].get("tool_calls") or 0 for r in records),
        "model_calls_known": {
            role: sum(r["agent"].get("model_calls", {}).get(role, 0) for r in records)
            for role in ("repair", "review")
        },
        "cost_complete": complete_cost,
    }


def render_report(experiment: dict, records: list[dict]) -> str:
    data = summarize(experiment, records)
    identity = experiment["identity"]

    def percent(value):
        return "N/A" if value is None else f"{value:.1%}"

    lines = [
        "# PyRepair Evaluation v2",
        "",
        f"实验：`{experiment['experiment_id']}` · 模型：`{identity['model']}`",
        "",
        f"完成度：{data['completed']}/{data['planned']}。"
        + (
            "全部完成。"
            if data["completed"] == data["planned"]
            else "未完成实验；不能称为最终成绩。"
        ),
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 当前完成部分通过率 | {percent(data['current_pass_rate'])} |",
        f"| 最终通过率 | {percent(data['final_pass_rate'])} |",
        f"| 首 attempt 独立通过率 | {percent(data['first_attempt_pass_rate'])} |",
        f"| 全部 trial 成功的题数 | {data['stable_cases'] if data['stable_cases'] is not None else 'N/A（单次运行）'} |",
        f"| 至少成功一次的题数（不是主要成功率） | {data['solved_at_least_once']} |",
        f"| Agent 误报 / 可判定的 Agent 成功 | {data['false_positives']}/{data['false_positive_denominator']} |",
        f"| 未能验收 | {data['ungraded']} |",
        f"| 中断重启次数 | {data['interrupted_executions']} |",
        f"| 尚未写入 trial 终态的执行 | {data['unfinished_executions']} |",
        f"| Agent 耗时中位数（秒） | {data['median_agent_seconds']} |",
        f"| Grader 总耗时（秒） | {data['grader_seconds']:.2f} |",
        f"| 已知执行工具调用 | {data['tool_calls_known']} |",
        f"| 已知模型调用（Repair / Review） | {data['model_calls_known']['repair']} / {data['model_calls_known']['review']} |",
        "",
        "## Token 覆盖",
        "",
        "未知不等于 0；已知数是日志下界，不含服务端未返回的消耗。",
        "",
        "| 角色 | 输入 Token | 输出 Token | 已知输入 / 输出 |",
        "| --- | --- | --- | --- |",
    ]
    for role in ("repair", "review"):
        t, k = data["tokens"][role], data["known_tokens"][role]
        lines.append(
            f"| {role} | {t['prompt_tokens'] if t['prompt_tokens'] is not None else '未知'} | "
            f"{t['completion_tokens'] if t['completion_tokens'] is not None else '未知'} | "
            f"{k['prompt_tokens']} / {k['completion_tokens']} |"
        )
    lines += ["", "## 分组结果", "", "| 集合 | 已完成 / 计划 | 成功 |", "| --- | --- | --- |"]
    groups = sorted({(c["suite"], c["split"]) for c in identity["cases"]})
    for suite, split in groups:
        ids = {c["id"] for c in identity["cases"] if (c["suite"], c["split"]) == (suite, split)}
        rows = [r for r in records if r["case_id"] in ids and not r.get("pending")]
        lines.append(
            f"| {suite}/{split} | {len(rows)} / {len(ids) * identity['trials']} | {sum(r['passed'] for r in rows)} |"
        )
    lines += [
        "",
        "## 每次试验（失败和错误均保留）",
        "",
        "| 题目 | Trial | Agent | Grader | 总体通过 | 证据目录 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        lines.append(
            f"| {r['case_id']} | {r['trial_index']} | {r['agent']['status']} | "
            f"{r['grade']['status']} | {r['passed']} | `{r.get('execution_dir', '-')}` |"
        )
    lines += [
        "",
        (
            "所有入选任务必须预检通过。新实验任一题预检不通过则整体停止，validation/ 保留原因，"
            "不会静默排除难题。本协议不产生 SWE-bench 官方分数；开发集成绩不能用于声称真实项目泛化。"
        ),
        "",
    ]
    return "\n".join(lines)
