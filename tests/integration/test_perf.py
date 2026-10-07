import json
import os
import resource
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import oracledb
import pytest

pytestmark = [pytest.mark.perf, pytest.mark.db]
ROOT = Path(__file__).resolve().parents[2]
BUDGET_SECONDS = 600
RSS_LIMIT_MB = 1024
VOLUME_LIMIT_BYTES = 12 * 1024**3


@dataclass(frozen=True)
class Measure:
    seconds: float
    run_rss_mb: float
    child_rss_mb: float


def executable(name: str) -> str:
    found = shutil.which(name)
    assert found is not None, name
    return found


def make(*targets: str) -> list[dict[str, object]]:
    done = subprocess.run(
        [executable("make"), *targets], cwd=ROOT, capture_output=True, text=True, check=False, timeout=1800
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    return [event for event in events if event["event"] == "run_end"]


@pytest.fixture(scope="module")
def dev_e2e(tmp_path_factory: pytest.TempPathFactory) -> Measure:
    data_dir = tmp_path_factory.mktemp("dev")
    subprocess.run([executable("docker"), "compose", "down", "--volumes"], cwd=ROOT, capture_output=True, check=True)
    started = time.monotonic()
    make("setup")
    ends = make("e2e", "PROFILE=dev", f"DATA_DIR={data_dir}")
    seconds = time.monotonic() - started
    child_rss_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    print(f"dev e2e {seconds:.0f} s, run peak RSS {ends[-1]['peak_rss_mb']} MB, children max RSS {child_rss_mb:.0f} MB")
    return Measure(seconds, max(float(str(end["peak_rss_mb"])) for end in ends), child_rss_mb)


def test_dev_e2e_under_10_min(dev_e2e: Measure) -> None:
    assert dev_e2e.seconds < BUDGET_SECONDS, f"{dev_e2e.seconds:.0f} s"


def test_peak_rss_under_1gb(dev_e2e: Measure) -> None:
    assert dev_e2e.run_rss_mb < RSS_LIMIT_MB
    assert dev_e2e.child_rss_mb < RSS_LIMIT_MB


def test_volume_within_12gb(dev_e2e: Measure) -> None:
    with oracledb.connect(user="system", password=os.environ["ORACLE_PASSWORD"], dsn=os.environ["SRDWH_DSN"]) as c:
        (used,) = c.cursor().execute("SELECT sum(bytes) FROM dba_segments").fetchone()
    assert int(used) < VOLUME_LIMIT_BYTES
