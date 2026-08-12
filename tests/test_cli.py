from typer.testing import CliRunner

from pyrepair.cli import app

runner = CliRunner()


def test_fix_help_shows_safe_controls():
    result = runner.invoke(app, ["fix", "--help"])

    assert result.exit_code == 0
    assert "--model" in result.stdout
    assert "--max-attempts" in result.stdout
    assert "--dry-run" in result.stdout
