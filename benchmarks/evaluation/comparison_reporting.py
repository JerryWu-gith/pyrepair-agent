"""Planned-denominator reporting; scripted simulation never yields a real score."""

from __future__ import annotations


def _accepted(record):
    return record is not None and record.get("core_passed", record.get("passed")) is True


def _extended_counts(slots, records, cases, simulation):
    result = {
        key: 0
        for key in (
            "planned_applicable",
            "passed",
            "failed",
            "timeout",
            "environment_error",
            "grader_error",
            "interrupted",
            "not_run",
            "not_applicable",
            "simulated",
        )
    }
    result["fully_verified"] = None if simulation else 0
    for slot in slots:
        if not cases[slot["case_id"]].get("regression_hash"):
            result["not_applicable"] += 1
            continue
        result["planned_applicable"] += 1
        record = records.get(slot["slot"])
        grade = record.get("grade") if record else None
        status = grade["extended"]["status"] if grade and grade.get("version") == 2 else "not_run"
        key = status if status in result else "not_run"
        result[key] += 1
        if not simulation and record and record.get("fully_verified") is True:
            result["fully_verified"] += 1
    return result


def summarize_comparison(pack, records, simulation=False, usage=None, *, execution_mode=None):
    if execution_mode not in {None, "smoke", "formal"}:
        raise ValueError("invalid reporting execution mode")
    layered = pack["identity"].get("version") == 2
    slots = pack["identity"]["slots"]
    by_id = {r["slot"]: r for r in records}
    if len(by_id) != len(records) or not set(by_id) <= {s["slot"] for s in slots}:
        raise ValueError("duplicate or unknown comparison record")
    if any(r["simulation"] is not simulation for r in records):
        raise ValueError("comparison simulation identity mismatch")
    sources = {c["id"]: c["source_kind"] for c in pack["identity"]["cases"]}
    groups, rows = [], []
    for method in ("single-shot", "full-agent"):
        for source in sorted(set(sources.values())):
            planned = [
                s for s in slots if s["method"] == method and sources[s["case_id"]] == source
            ]
            completed = [by_id[s["slot"]] for s in planned if s["slot"] in by_id]
            accepted = sum(_accepted(r) for r in completed)
            groups.append(
                {
                    "method": method,
                    "source_kind": source,
                    "planned": len(planned),
                    "finished": len(completed),
                    "accepted": None if simulation else accepted,
                    "technical_errors": sum(r["status"] == "technical_error" for r in completed),
                    "unrun": len(planned) - len(completed),
                    "success_rate": None if simulation or not planned else accepted / len(planned),
                    "internal_success_rejected": sum(
                        r["method"] == "full-agent"
                        and r["status"] == "failed"
                        and r["candidate"]["internal_success"] is True
                        for r in completed
                    ),
                }
            )
            if layered:
                row = groups[-1]
                row["core_accepted"] = row.pop("accepted")
                row["core_acceptance_rate"] = row.pop("success_rate")
                row["extended"] = _extended_counts(
                    planned, by_id, {c["id"]: c for c in pack["identity"]["cases"]}, simulation
                )
    for slot in slots:
        record = by_id.get(slot["slot"])
        rows.append(
            {
                **slot,
                "source_kind": sources[slot["case_id"]],
                "status": record["status"] if record else "unrun",
                "grade": record["grade"]["status"] if record and record["grade"] else None,
                "duration_seconds": record["candidate"]["duration_seconds"]
                if record and record["candidate"]
                else None,
                **(
                    {
                        "core_passed": record.get("core_passed") if record else None,
                        "extended": record["grade"]["extended"]["status"]
                        if record and record.get("grade")
                        else "not_run",
                        "fully_verified": record.get("fully_verified") if record else None,
                    }
                    if layered
                    else {}
                ),
            }
        )
    paired = []
    for case_id, source in sources.items():
        trial_ids = sorted({s["trial"] for s in slots if s["case_id"] == case_id})
        trials = []
        agent_accepted, single_accepted = 0, 0
        for trial in trial_ids:
            pair = {
                method: by_id.get(f"{case_id}--{trial}--{method}")
                for method in ("single-shot", "full-agent")
            }
            baseline, agent = pair["single-shot"], pair["full-agent"]
            a = _accepted(agent)
            b = _accepted(baseline)
            agent_accepted += a
            single_accepted += b
            comparable = (
                not simulation
                and baseline is not None
                and agent is not None
                and all(r["status"] != "technical_error" for r in pair.values())
            )
            trials.append(
                {
                    "trial": trial,
                    "single_shot": baseline["status"] if baseline else "unrun",
                    "full_agent": agent["status"] if agent else "unrun",
                    "delta": int(a) - int(b) if comparable else None,
                }
            )
        paired.append(
            {
                "case_id": case_id,
                "source_kind": source,
                "planned_trials": len(trial_ids),
                "comparable_trials": sum(t["delta"] is not None for t in trials),
                "agent_minus_single_accepted": None
                if simulation
                else agent_accepted - single_accepted,
                "trials": trials,
            }
        )
    if usage is None:
        usage = {
            "status": "simulation-no-model" if simulation else "not-collected",
            "reserved_calls": 0 if simulation else None,
            "responses": 0 if simulation else None,
            "roles": {
                role: {
                    "calls": 0 if simulation else None,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                }
                for role in ("single-shot", "repair", "review")
            },
            "usage_known": False,
            "transport_requests": None,
        }
    trial_counts = "/".join(str(n) for n in sorted({r["planned_trials"] for r in paired})) or "0"
    scope = f"{len(paired)} task(s); scheduled trials per task: {trial_counts}"
    limitations = f"dev tasks; whole-workflow comparison; {scope}; limited evidence"
    if execution_mode == "smoke":
        limitations += "; wiring smoke, not a formal repeated evaluation; do not extrapolate overall performance"
    return {
        "assessment_version": 2 if layered else 1,
        "kind": "SIMULATION - NOT real model performance"
        if simulation
        else "SMOKE - NOT formal repeated evaluation"
        if execution_mode == "smoke"
        else "planned paired workflow comparison",
        "pack_hash": pack["identity_hash"],
        "planned": len(slots),
        "finished": len(records),
        "unrun": len(slots) - len(records),
        "real_model_trials": 0 if simulation else None,
        "groups": groups,
        "rows": rows,
        "paired_cases": paired,
        "usage": usage,
        "cost_rmb": None,
        **(
            {
                "extended": _extended_counts(
                    slots, by_id, {c["id"]: c for c in pack["identity"]["cases"]}, simulation
                )
            }
            if layered
            else {}
        ),
        "limitations": limitations,
    }


def render_comparison(summary):
    layered = summary.get("assessment_version") == 2
    lines = [
        "# " + summary["kind"],
        "",
        f"Planned {summary['planned']}; finished {summary['finished']}; unrun {summary['unrun']}.",
        "",
        "| Method | Source | Planned | Finished | Accepted | Technical errors | Unrun | Rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary["groups"]:
        measured = row["core_acceptance_rate"] if layered else row["success_rate"]
        rate = "not measured" if measured is None else f"{measured:.1%}"
        accepted = row["core_accepted"] if layered else row["accepted"]
        lines.append(
            f"| {row['method']} | {row['source_kind']} | {row['planned']} | {row['finished']} | {accepted} | {row['technical_errors']} | {row['unrun']} | {rate} |"
        )
    if layered:
        lines[4] = (
            "| Method | Source | Planned | Finished | Core accepted | Technical errors | Unrun | Core acceptance rate |"
        )
        lines.extend(
            [
                "",
                "## Core acceptance and Extended regression",
                "",
                "Core acceptance does not imply extended regression passed. A timeout is unverified, not success. Selected upstream files are not all upstream test entry points.",
                "",
                "| Method | Source | Applicable planned | Passed | Failed | Timeout | Error | Interrupted | Not run | Fully verified |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in summary["groups"]:
            ext = row["extended"]
            verified = "not measured" if ext["fully_verified"] is None else ext["fully_verified"]
            lines.append(
                f"| {row['method']} | {row['source_kind']} | {ext['planned_applicable']} | {ext['passed']} | {ext['failed']} | {ext['timeout']} | {ext['environment_error'] + ext['grader_error']} | {ext['interrupted']} | {ext['not_run']} | {verified} |"
            )
        lines.extend(
            [
                "",
                "Not-applicable planned slots: "
                + str(summary["extended"]["not_applicable"])
                + ". Not-applicable is not passed.",
            ]
        )
    lines.extend(
        [
            "",
            "## Paired cases (Agent minus single-shot)",
            "",
            "| Case | Source | Comparable trials | Observed accepted difference |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in summary["paired_cases"]:
        difference = (
            "not measured"
            if row["agent_minus_single_accepted"] is None
            else row["agent_minus_single_accepted"]
        )
        lines.append(
            f"| {row['case_id']} | {row['source_kind']} | {row['comparable_trials']}/{row['planned_trials']} | {difference} |"
        )
    usage = summary["usage"]
    lines.extend(
        [
            "",
            "## Model-call reservations and usage",
            "",
            f"Reserved calls: {usage['reserved_calls']}; responses: {usage['responses']}; transport requests: {usage['transport_requests']}.",
            "",
            "| Role | Calls | Prompt tokens | Completion tokens |",
            "| --- | --- | --- | --- |",
        ]
    )
    for role, values in usage["roles"].items():
        rendered = [
            "unknown" if values.get(key) is None else values[key]
            for key in ("calls", "prompt_tokens", "completion_tokens")
        ]
        lines.append(f"| {role} | {rendered[0]} | {rendered[1]} | {rendered[2]} |")
    lines.extend(
        [
            "",
            summary["limitations"],
            "",
            "No currency cost or provider HTTP retry count is inferred.",
        ]
    )
    return "\n".join(lines) + "\n"
