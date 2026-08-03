from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from srdwh.config import load_settings
from srdwh.generate.landing import write_landing
from srdwh.log import Event, emit, run_end
from srdwh.pipeline.run import run as run_pipeline

EXIT_OK = 0
EXIT_FAILURE = 1
SETTINGS = Path("srdwh.toml")
REF_DIR = Path("db/ref")

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def root() -> None:
    pass


@app.command(help="Write simulated feeds, manifests and ground truth for every as_of of a profile.")
def generate(
    profile: Annotated[str, typer.Option(help="Profile of srdwh.toml.")],
    seed: Annotated[int | None, typer.Option(min=0, help="Seed overriding the profile seed.")] = None,
    data_dir: Annotated[Path, typer.Option(help="Root of landing/ and ground_truth/.")] = Path("data"),
) -> None:
    try:
        chosen = load_settings(SETTINGS).profile(profile)
        chosen = chosen if seed is None else replace(chosen, seed=seed)
        write_landing(chosen, REF_DIR, data_dir)
    except (ValueError, OSError) as error:
        typer.echo(f"generate: {error}", err=True)
        raise typer.Exit(EXIT_FAILURE) from None


@app.command(help="Ingest the landing into bronze under the run lock.")
def run(
    profile: Annotated[str, typer.Option(help="Profile of srdwh.toml.")],
    data_dir: Annotated[Path, typer.Option(help="Root of landing/.")] = Path("data"),
) -> None:
    try:
        settings = load_settings(SETTINGS)
        settings.profile(profile)
    except ValueError as error:
        emit(Event("error", "config", level="ERROR", message=str(error)))
        run_end(None, EXIT_FAILURE, 0)
        raise typer.Exit(EXIT_FAILURE) from None
    raise typer.Exit(run_pipeline(settings, data_dir))


def main() -> None:
    try:
        code = app(standalone_mode=False)
    except (typer.TyperException, typer.Abort) as error:
        if str(error):
            typer.echo(f"srdwh: {error}", err=True)
        code = EXIT_FAILURE
    raise SystemExit(code or EXIT_OK)
