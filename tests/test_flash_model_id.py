import json

import pytest

from benchmarks import run_evaluation
from pyrepair.config import load_config
from tests.evaluation_helpers import make_case
from tests.test_deepseek import FakeOpenAI, make_client, text_response


@pytest.mark.parametrize("source", ["environment", "override"])
def test_config_accepts_current_flash_model_id(monkeypatch, source):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    monkeypatch.setenv("PYREPAIR_MODEL", "deepseek-v4-pro")
    if source == "environment":
        monkeypatch.setenv("PYREPAIR_MODEL", "deepseek-flash")
        config = load_config()
    else:
        config = load_config(model_override="deepseek-flash")

    assert config.model == "deepseek-flash"


def test_client_sends_current_flash_id_without_rewriting_it(monkeypatch):
    fake = FakeOpenAI()
    fake.completions.queue(text_response("done"))
    client, _ = make_client(monkeypatch, fake, model="deepseek-flash")

    result = client.complete([{"role": "user", "content": "fix"}], [])

    assert result.content == "done"
    assert fake.completions.requests[0]["model"] == "deepseek-flash"


@pytest.mark.parametrize("model_args", [[], ["--model", "deepseek-flash"]])
def test_evaluation_records_current_flash_id(tmp_path, monkeypatch, model_args):
    manifest = make_case(tmp_path / "bank")
    output = tmp_path / "experiment"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    # Only the paid execution boundary is replaced; task validation, experiment
    # persistence and report generation remain real.
    monkeypatch.setattr(run_evaluation, "run_experiment", lambda *args: [])

    result = run_evaluation.main(
        ["run", "--manifest", str(manifest), "--output", str(output), *model_args]
    )

    assert result == 0
    config = json.loads((output / "experiment.json").read_text(encoding="utf-8"))
    assert config["identity"]["model"] == "deepseek-flash"
