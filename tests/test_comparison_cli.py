import json

import pytest

from tests.test_comparison_pack import make_prepared


def test_cli_verifies_and_simulates_without_credentials_or_model(tmp_path, monkeypatch, capsys):
    from benchmarks.run_comparison import main

    _, cases, output, _ = make_prepared(tmp_path, monkeypatch)
    manifest = cases[0].root / "manifest_v2.json"

    def forbidden(*args, **kwargs):
        pytest.fail("offline CLI must not construct a provider or load credentials")

    monkeypatch.setattr("pyrepair.config.load_config", forbidden)
    monkeypatch.setattr("pyrepair.deepseek.DeepSeekClient", forbidden)
    assert main(["verify", "--pack", str(output), "--manifest", str(manifest)]) == 0
    run = tmp_path / "simulation"
    arguments = [
        "simulate",
        "--pack",
        str(output),
        "--output",
        str(run),
        "--manifest",
        str(manifest),
    ]
    assert main(arguments) == 0
    summary = json.loads((run / "summary.json").read_text("utf-8"))
    assert summary["planned"] == summary["finished"] == 6
    assert summary["real_model_trials"] == 0
    assert "SIMULATION" in (run / "report.md").read_text("utf-8")
    journal = (run / "journal.jsonl").read_bytes()
    assert main(arguments) == 0
    assert (run / "journal.jsonl").read_bytes() == journal
    assert "NOT real model performance" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["run", "live", "repair"])
def test_cli_has_no_paid_execution_route(command):
    from benchmarks.run_comparison import main

    with pytest.raises(SystemExit) as caught:
        main([command])
    assert caught.value.code == 2


def test_cli_rejects_changed_evidence_before_creating_simulation(tmp_path, monkeypatch):
    from benchmarks.run_comparison import main

    _, cases, output, _ = make_prepared(tmp_path, monkeypatch)
    (output / "p/c00/r/src/app.py").write_text("changed", encoding="utf-8")
    run = tmp_path / "simulation"
    assert (
        main(
            [
                "simulate",
                "--pack",
                str(output),
                "--output",
                str(run),
                "--manifest",
                str(cases[0].root / "manifest_v2.json"),
            ]
        )
        == 2
    )
    assert not run.exists()
