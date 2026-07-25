from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from srdwh.config import load_settings
from srdwh.generate.landing import write_partition
from srdwh.generate.simulate import simulate

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
        for partition in simulate(chosen, REF_DIR):
            write_partition(partition, data_dir, chosen)
    except (ValueError, OSError) as error:
        typer.echo(f"generate: {error}", err=True)
        raise typer.Exit(EXIT_FAILURE) from None


def main() -> None:
    try:
        code = app(standalone_mode=False)
    except (typer.TyperException, typer.Abort) as error:
        if str(error):
            typer.echo(f"srdwh: {error}", err=True)
        code = EXIT_FAILURE
    raise SystemExit(code or EXIT_OK)
