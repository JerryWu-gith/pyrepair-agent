from typer.testing import CliRunner

from pyrepair.cli import app
from pyrepair.config import AppConfig, ConfigError
from pyrepair.models import RunResult

runner = CliRunner()


def test_fix_help_shows_safe_controls():
    result = runner.invoke(app, ["fix", "--help"])

    assert result.exit_code == 0
    assert "--model" in result.stdout
    assert "--max-attempts" in result.stdout
    assert "--dry-run" in result.stdout


def test_root_help_lists_fix_as_real_subcommand():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Commands" in result.stdout
    assert "fix" in result.stdout


class FakeCoordinator:
    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


def test_fix_success_prints_artifacts_and_returns_zero(monkeypatch, tmp_path):
    coordinator = FakeCoordinator(RunResult("success", 1, tmp_path / "artifacts"))
    monkeypatch.setattr(
        "pyrepair.cli.load_config",
        lambda **kwargs: AppConfig("test-key", kwargs["model_override"]),
    )
    monkeypatch.setattr("pyrepair.cli.build_coordinator", lambda config, model_enabled: coordinator)

    result = runner.invoke(app, ["fix", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    assert "success" in result.stdout
    assert str(tmp_path / "artifacts") in result.stdout
    assert coordinator.requests[0].repo == tmp_path.resolve()


def test_fix_business_failure_returns_one(monkeypatch, tmp_path):
    coordinator = FakeCoordinator(
        RunResult("failed", 3, tmp_path / "artifacts", "max_attempts_exceeded")
    )
    monkeypatch.setattr(
        "pyrepair.cli.load_config",
        lambda **kwargs: AppConfig("test-key", kwargs["model_override"]),
    )
    monkeypatch.setattr("pyrepair.cli.build_coordinator", lambda config, model_enabled: coordinator)

    result = runner.invoke(app, ["fix", "--repo", str(tmp_path)])

    assert result.exit_code == 1
    assert "max_attempts_exceeded" in result.stdout


def test_fix_config_error_returns_two_without_traceback(monkeypatch, tmp_path):
    def fail_config(**kwargs):
        raise ConfigError("缺少 DEEPSEEK_API_KEY")

    monkeypatch.setattr("pyrepair.cli.load_config", fail_config)

    result = runner.invoke(app, ["fix", "--repo", str(tmp_path)])

    assert result.exit_code == 2
    assert "DEEPSEEK_API_KEY" in result.stdout
    assert "Traceback" not in result.stdout


def test_fix_dry_run_does_not_require_api_key(monkeypatch, tmp_path):
    captured = {}
    coordinator = FakeCoordinator(RunResult("dry_run", 0, tmp_path / "artifacts"))

    def load(**kwargs):
        captured.update(kwargs)
        return AppConfig("", kwargs["model_override"])

    monkeypatch.setattr("pyrepair.cli.load_config", load)
    monkeypatch.setattr("pyrepair.cli.build_coordinator", lambda config, model_enabled: coordinator)

    result = runner.invoke(app, ["fix", "--repo", str(tmp_path), "--dry-run"])

    assert result.exit_code == 0
    assert captured["require_api_key"] is False
