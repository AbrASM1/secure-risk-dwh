import json
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import oracledb
import pytest

from srdwh.config import Profile
from tests.integration.db import Connect, rows
from tests.integration.pipeline import landing

pytestmark = pytest.mark.db
SRDWH = Path(sys.executable).parent / "srdwh"
COUNTS = (
    "SELECT (SELECT COUNT(*) FROM srdwh_owner.ops_load_registry), (SELECT COUNT(*) FROM srdwh_owner.ops_run_log), "
    "(SELECT COUNT(*) FROM srdwh_owner.ops_err_log) FROM dual"
)


@pytest.fixture
def data_dir(tmp_path: Path, pipeline_profile: Callable[[int], Profile]) -> Path:
    return landing(tmp_path, pipeline_profile(3))


def srdwh_run(data_dir: Path) -> subprocess.Popen[str]:
    command = [str(SRDWH), "run", "--profile", "ci", "--data-dir", str(data_dir)]
    return subprocess.Popen(command, stdout=subprocess.PIPE, text=True)


def events(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines()]


def statuses(connection: oracledb.Connection, data_dir: Path) -> dict[str, list[object]]:
    found: dict[str, list[object]] = {}
    for manifest in sorted(data_dir.glob("landing/*/*/manifest.json")):
        sha = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
        query = "SELECT status FROM srdwh_owner.ops_load_registry WHERE sha256 = :sha ORDER BY load_id"
        found[manifest.parent.name + "/" + manifest.parent.parent.name] = [
            s for (s,) in rows(connection, query, sha=sha)
        ]
    return found


def test_concurrent_run_exit_1(data_dir: Path, connect: Connect, system_connection: oracledb.Connection) -> None:
    holder = connect("SRDWH_ETL")
    with holder.cursor() as cursor:
        cursor.callproc("srdwh_owner.pkg_ops.lock_run")
    before = rows(system_connection, COUNTS)
    process = srdwh_run(data_dir)
    output, _ = process.communicate(timeout=60)
    after = rows(system_connection, COUNTS)
    holder.close()
    assert process.returncode == 1
    assert [e["event"] for e in events(output)] == ["lock_busy", "run_end"]
    assert after == before
    assert all(found == [] for found in statuses(system_connection, data_dir).values())


def test_killed_run_recovers(data_dir: Path, system_connection: oracledb.Connection) -> None:
    process = srdwh_run(data_dir)
    assert process.stdout is not None
    for line in process.stdout:
        if json.loads(line)["event"] == "load_end":
            process.send_signal(signal.SIGKILL)
            break
    process.wait(timeout=60)
    assert process.returncode == -signal.SIGKILL
    rerun = srdwh_run(data_dir)
    output, _ = rerun.communicate(timeout=120)
    assert rerun.returncode == 0, output
    found = statuses(system_connection, data_dir)
    assert all(states and states[-1] == "LOADED" for states in found.values()), found
    assert all(set(states[:-1]) <= {"FAILED"} for states in found.values()), found
