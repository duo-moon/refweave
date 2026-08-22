from __future__ import annotations

from typing import Annotated

import typer

from refweave import __version__

app = typer.Typer(
    name="refweave",
    help="Graph-informed chunking for wiki-like sources.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def _main(
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """refweave CLI."""


if __name__ == "__main__":
    app()
