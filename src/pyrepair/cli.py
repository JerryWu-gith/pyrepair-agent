from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def fix(
    target: Annotated[str | None, typer.Argument()] = None,
    repo: Annotated[Path, typer.Option()] = Path("."),
    model: Annotated[str, typer.Option()] = "deepseek-v4-flash",
    max_attempts: Annotated[int, typer.Option(min=1, max=3)] = 3,
    dry_run: Annotated[bool, typer.Option()] = False,
    verbose: Annotated[bool, typer.Option()] = False,
) -> None:
    """Diagnose pytest failures and generate a safe candidate patch."""
    typer.echo(
        f"repo={repo.resolve()} target={target or 'full-suite'} "
        f"model={model} attempts={max_attempts} dry_run={dry_run} verbose={verbose}"
    )
