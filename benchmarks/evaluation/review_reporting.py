"""Offline Review metrics with explicit denominators and paired comparisons."""

from __future__ import annotations

import json
from pathlib import Path

from pyrepair.recorder import _atomic_write

from .experiment import digest
from .review_assets import validate_dataset
from .review_evaluation import schedule
from .review_fixtures import PROTOCOL, save_json


def _rate(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator}


def summarize_review(manifest: dict, results: dict[str, dict], started: set[str]) -> dict:
    rows, labels = manifest["schedule"], manifest["labels"]
    summary = {
        "planned_requests": len(rows),
        "started_requests": len(started),
        "arms": {},
        "paired": dict.fromkeys(
            ("b_fixes_a", "b_breaks_a", "both_correct", "both_wrong", "missing"), 0
        ),
    }
    for arm in "AB":
        selected = [r for r in rows if r["arm"] == arm]
        valid = [r for r in selected if results.get(r["id"], {}).get("status") == "valid"]
        positives = [r for r in valid if labels[r["candidate"]]]
        negatives = [r for r in valid if not labels[r["candidate"]]]
        approved = lambda r: results[r["id"]]["parsed"]["approved"]
        finished = [results[r["id"]] for r in selected if r["id"] in results]
        known = [r for r in finished if r["usage_known"]]
        unknown = sum(
            r["id"] in started and (r["id"] not in results or not results[r["id"]]["usage_known"])
            for r in selected
        )
        arm_data = {
            "false_reject": _rate(sum(not approved(r) for r in positives), len(positives)),
            "false_accept": _rate(sum(approved(r) for r in negatives), len(negatives)),
            "correct": _rate(
                sum(approved(r) == labels[r["candidate"]] for r in valid), len(selected)
            ),
            "valid": _rate(len(valid), len(selected)),
            "api_errors": sum(r["status"] == "api_error" for r in finished),
            "parse_errors": sum(r["status"] == "parse_error" for r in finished),
            "pending_started": sum(r["id"] in started and r["id"] not in results for r in selected),
            "not_started": sum(r["id"] not in started for r in selected),
            "started_requests": sum(r["id"] in started for r in selected),
            "unknown_usage_requests": unknown,
            "cost_complete": unknown == 0,
            "known_prompt_tokens": sum(r["prompt_tokens"] for r in known),
            "known_completion_tokens": sum(r["completion_tokens"] for r in known),
            "recorded_seconds": sum(r["seconds"] for r in finished),
            "flips": _rate(0, 0),
            "incomplete_groups": 0,
        }
        for candidate in labels:
            group = [r for r in valid if r["candidate"] == candidate]
            if len(group) == manifest["repeats"]:
                arm_data["flips"]["denominator"] += 1
                arm_data["flips"]["numerator"] += len({approved(r) for r in group}) > 1
            else:
                arm_data["incomplete_groups"] += 1
        summary["arms"][arm] = arm_data
    for candidate, label in labels.items():
        for repeat in range(1, manifest["repeats"] + 1):
            pair = {
                r["arm"]: results.get(r["id"], {})
                for r in rows
                if r["candidate"] == candidate and r["repeat"] == repeat
            }
            if any(pair.get(arm, {}).get("status") != "valid" for arm in "AB"):
                key = "missing"
            else:
                a, b = (pair[arm]["parsed"]["approved"] == label for arm in "AB")
                key = (
                    "both_correct"
                    if a and b
                    else "b_fixes_a"
                    if b
                    else "b_breaks_a"
                    if a
                    else "both_wrong"
                )
            summary["paired"][key] += 1
    return summary


def load_run(experiment: Path) -> tuple[dict, dict, set[str]]:
    document = json.loads((experiment / "manifest.json").read_text(encoding="utf-8"))
    manifest = document["payload"]
    if document.get("digest") != digest(manifest) or manifest.get("protocol") != PROTOCOL:
        raise ValueError("invalid manifest digest/protocol")
    expected = schedule(list(manifest["inputs"]), manifest["repeats"])
    if manifest["schedule"] != expected or set(manifest["labels"]) != set(manifest["inputs"]):
        raise ValueError("invalid schedule/labels")
    if "dataset" in manifest:
        validate_dataset(manifest["dataset"], list(manifest["inputs"]))
    ids = {row["id"] for row in expected}
    if set(manifest["request_hashes"]) != ids:
        raise ValueError("invalid request identity")
    results, started = {}, set()
    requests = experiment / "requests"
    if requests.exists():
        for directory in requests.iterdir():
            if directory.name not in ids or not directory.is_dir():
                raise ValueError("unknown request directory")
            key = directory.name
            request_path = directory / "request.json"
            start_path = directory / "started.json"
            result_path = directory / "result.json"
            if request_path.exists():
                request = json.loads(request_path.read_text(encoding="utf-8"))
                if digest(request) != manifest["request_hashes"][key]:
                    raise ValueError("request digest mismatch")
            if start_path.exists():
                event = json.loads(start_path.read_text(encoding="utf-8"))
                if (
                    not request_path.exists()
                    or event.get("id") != key
                    or event.get("request_hash") != manifest["request_hashes"][key]
                ):
                    raise ValueError("invalid started evidence")
                started.add(key)
            if result_path.exists():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                claimed = result.pop("record_digest", None)
                if claimed != digest(result):
                    raise ValueError("result digest mismatch")
                if (
                    key not in started
                    or result.get("id") != key
                    or result.get("request_hash") != manifest["request_hashes"][key]
                    or result.get("status") not in {"valid", "parse_error", "api_error"}
                    or type(result.get("usage_known")) is not bool
                    or not isinstance(result.get("seconds"), (float, int))
                    or result["seconds"] < 0
                ):
                    raise ValueError("invalid result evidence")
                if (
                    result["status"] == "valid"
                    and type(result.get("parsed", {}).get("approved")) is not bool
                ):
                    raise ValueError("invalid decision")
                if result["usage_known"] and any(
                    type(result.get(n)) is not int or result[n] < 0
                    for n in ("prompt_tokens", "completion_tokens")
                ):
                    raise ValueError("invalid usage")
                results[key] = result
    return manifest, results, started


def write_report(experiment: Path) -> dict:
    manifest, results, started = load_run(experiment)
    summary = summarize_review(manifest, results, started)
    save_json(experiment / "summary.json", summary)

    def rate(value):
        n, d = value["numerator"], value["denominator"]
        return f"{n}/{d} ({n / d:.1%})" if d else "0/0 (N/A)"

    if "dataset" in manifest:
        dataset = manifest["dataset"]
        mapping = dataset["candidate_cases"]
        boundaries = [
            (
                f"- 集合 {dataset['id']}：{len(set(mapping.values()))} 题、{len(mapping)} 候选；"
                "synthetic/dev 定向开发挑战集，不是真实缺陷集或 holdout。"
            ),
            (
                "- 参考与反例包含人工校准、人工变异及历史候选；来源逐项见 provenance。"
                "参考校准不算新增模型修复成绩，重复调用不等于新增独立任务。"
            ),
        ]
    else:
        boundaries = [
            "- 三题是已知问题定向开发样本，不是随机抽样、真实缺陷集或 holdout。",
            "- case_15 正例是人工校准候选，不是模型新增修复成绩。历史精度反例不进入这六候选。",
        ]
    lines = [
        "# Review 公开说明 A/B 对照",
        "",
        f"模型：{manifest['model']}；计划 {len(manifest['schedule'])} 次，started 记录 {len(started)} 次。",
        "",
        "A 为新共同提示词下的无说明控制组；B 只增加公开任务说明。",
        "",
        "| 指标 | A | B |",
        "| --- | --- | --- |",
    ]
    for key, title in [
        ("false_reject", "正例误拒 / 有效正例"),
        ("false_accept", "反例误放 / 有效反例"),
        ("correct", "判断正确 / 全部计划"),
        ("valid", "有效回复覆盖"),
        ("flips", "波动 / 完整候选组"),
    ]:
        lines.append(
            f"| {title} | {rate(summary['arms']['A'][key])} | {rate(summary['arms']['B'][key])} |"
        )
    for key in (
        "api_errors",
        "parse_errors",
        "pending_started",
        "not_started",
        "incomplete_groups",
        "unknown_usage_requests",
        "known_prompt_tokens",
        "known_completion_tokens",
        "recorded_seconds",
    ):
        lines.append(f"| {key} | {summary['arms']['A'][key]} | {summary['arms']['B'][key]} |")
    lines += [
        "",
        "## 双有效配对",
        "",
        json.dumps(summary["paired"], ensure_ascii=False),
        "",
        "## 解释边界",
        "",
        *boundaries,
        "- 解析失败不是有效语义拒绝；所有计划请求保留在端到端分母。批准率提高不等于更准确。",
        "- Token 只汇总已知用量；unknown_usage_requests 非零时成本只是已知下界。",
        "- started 表示已持久化调用意图；中断可能发生在发出前或返回后，实际完成/费用未知，不自动重试。",
        "- recorded_seconds 仅含已落盘响应的耗时；不完整组不参与波动统计。",
        "- 该对照不能代替新版本端到端修复评测，不能据此声称普遍提升。",
        "",
    ]
    if summary["paired"]["missing"]:
        lines += [
            "## 证据不足",
            "",
            "存在缺失或无效 A/B 配对，当前记录不足以完成预定的完整对照。不得据此自动推广；先逐项解释错误与缺失，另行确认是否开展新实验。",
            "",
        ]
    _atomic_write(experiment / "report.md", "\n".join(lines))
    return summary
