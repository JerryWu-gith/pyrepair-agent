import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from pyrepair.models import ModelTurn


class Reply:
    max_retries = 2

    def complete(self, messages, tools):
        assert self.max_retries == 0
        return ModelTurn("answer", None, (), 10, 2, "stop")


def test_quota_is_durable_and_exhaustion_prevents_another_response(tmp_path):
    from benchmarks.evaluation.comparison_budget import (
        CallBudget,
        GuardedClient,
        QuotaError,
        read_usage,
    )

    root = tmp_path / "quota"
    budget = CallBudget(root, 2)
    for slot in ("a", "b"):
        client = GuardedClient(Reply(), budget, slot, "single-shot", 1, tmp_path / slot)
        assert client.complete([], []).content == "answer"
    with pytest.raises(QuotaError):
        GuardedClient(Reply(), CallBudget(root, 2), "c", "single-shot", 1, tmp_path / "c").complete(
            [], []
        )
    usage = read_usage(root)
    assert usage["reserved_calls"] == 2
    assert usage["responses"] == 2
    assert usage["roles"]["single-shot"]["prompt_tokens"] == 20
    assert usage["usage_known"] is True
    assert usage["transport_requests"] is None


def test_response_is_saved_before_caller_crashes(tmp_path):
    from benchmarks.evaluation.comparison_budget import CallBudget, GuardedClient, read_usage

    output = tmp_path / "reply"
    client = GuardedClient(Reply(), CallBudget(tmp_path / "quota", 1), "a", "repair", 1, output)
    with pytest.raises(RuntimeError):
        client.complete([], [])
        raise RuntimeError("consumer tool crashed")
    value = json.loads(next(output.glob("response-*.json")).read_text("utf-8"))
    assert value["content"] == "answer"
    assert read_usage(tmp_path / "quota")["roles"]["repair"]["completion_tokens"] == 2


def test_interrupted_provider_consumes_slot_without_inventing_zero_usage(tmp_path):
    from benchmarks.evaluation.comparison_budget import (
        CallBudget,
        GuardedClient,
        QuotaError,
        read_usage,
    )

    class Interrupted:
        def complete(self, messages, tools):
            raise KeyboardInterrupt

    budget = CallBudget(tmp_path / "quota", 2)
    client = GuardedClient(Interrupted(), budget, "a", "repair", 1, tmp_path / "reply")
    with pytest.raises(KeyboardInterrupt):
        client.complete([], [])
    with pytest.raises(QuotaError):
        client.complete([], [])
    usage = read_usage(tmp_path / "quota")
    assert usage["reserved_calls"] == 1
    assert usage["usage_known"] is False
    assert usage["roles"]["repair"]["prompt_tokens"] is None


def test_competing_reservations_cannot_overspend(tmp_path):
    from benchmarks.evaluation.comparison_budget import CallBudget, QuotaError, read_usage

    budget = CallBudget(tmp_path / "quota", 2)

    def reserve(number):
        try:
            return budget.reserve(str(number), "repair", 1)
        except QuotaError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        successful = [v for v in pool.map(reserve, range(12)) if v is not None]
    assert 0 < len(successful) <= 2
    assert len(set(successful)) == len(successful)
    assert read_usage(tmp_path / "quota")["reserved_calls"] == len(successful)


@pytest.mark.parametrize("limit", [True, 0, -1, "2"])
def test_invalid_global_limits_are_rejected(tmp_path, limit):
    from benchmarks.evaluation.comparison_budget import CallBudget

    with pytest.raises(ValueError):
        CallBudget(tmp_path / "quota", limit)


def test_existing_quota_cannot_be_reopened_with_larger_limit(tmp_path):
    from benchmarks.evaluation.comparison_budget import CallBudget

    CallBudget(tmp_path / "quota", 1)
    with pytest.raises(ValueError, match="identity"):
        CallBudget(tmp_path / "quota", 2)


def test_stale_lock_is_not_automatically_removed(tmp_path):
    from benchmarks.evaluation.comparison_budget import CallBudget, QuotaError

    budget = CallBudget(tmp_path / "quota", 2)
    (budget.root / "writer.lock").write_text("stale or live", encoding="utf-8")
    with pytest.raises(QuotaError):
        budget.reserve("a", "repair", 1)
    assert (budget.root / "writer.lock").read_text() == "stale or live"


def test_zero_response_usage_is_unknown(tmp_path):
    from benchmarks.evaluation.comparison_budget import CallBudget, GuardedClient, read_usage

    class Unknown:
        def complete(self, messages, tools):
            return ModelTurn("ok", None, ())

    client = GuardedClient(
        Unknown(), CallBudget(tmp_path / "quota", 1), "a", "repair", 1, tmp_path / "r"
    )
    client.complete([], [])
    usage = read_usage(tmp_path / "quota")
    assert usage["usage_known"] is False
    assert usage["roles"]["repair"]["prompt_tokens"] is None
