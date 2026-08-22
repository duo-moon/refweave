from typer.testing import CliRunner

from refweave import __version__
from refweave.cli import app


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
