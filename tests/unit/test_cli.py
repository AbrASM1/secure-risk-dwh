import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from srdwh.cli import app, main


def manifests(data_dir: Path) -> list[dict[str, object]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(data_dir.glob("landing/*/*/manifest.json"))]


def test_generate_writes_landing_and_ground_truth(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "--profile", "ci", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert len(manifests(tmp_path)) == 6
    assert len(list(tmp_path.glob("ground_truth/*/*/expected.parquet"))) == 6


def test_generate_seed_overrides_profile(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "--profile", "ci", "--seed", "11", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert {m["seed"] for m in manifests(tmp_path)} == {11}


@pytest.mark.parametrize(
    "argv",
    [[], ["generate"], ["generate", "--profile", "prod"], ["generate", "--profile", "ci", "--seed", "-1"], ["bogus"]],
)
def test_errors_exit_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]) -> None:
    monkeypatch.setattr(
        "sys.argv", ["srdwh", *argv, *(["--data-dir", str(tmp_path)] if argv[:1] == ["generate"] else [])]
    )
    with pytest.raises(SystemExit) as stop:
        main()
    assert stop.value.code == 1
    assert not list(tmp_path.rglob("*.parquet"))
