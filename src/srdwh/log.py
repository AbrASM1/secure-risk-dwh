import json
import resource
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TextIO

LEVELS = frozenset({"INFO", "WARNING", "ERROR"})
EVENTS = frozenset(
    {
        "run_start",
        "lock_busy",
        "partition_not_ready",
        "structural_check_failed",
        "load_skipped",
        "load_end",
        "plan",
        "rejects_end",
        "threshold_breach",
        "silver_end",
        "rewind_end",
        "gold_end",
        "export_end",
        "error",
        "run_end",
    }
)
STEPS = frozenset({"config", "lock", "ingest", "plan", "rejects", "silver", "rewind", "gold", "stats", "export", "run"})
FIELDS = (
    "ts",
    "level",
    "event",
    "run_id",
    "step",
    "as_of",
    "feed",
    "load_id",
    "rows",
    "rows_rejected",
    "reject_rate",
    "duration_ms",
    "exit_code",
    "peak_rss_mb",
    "message",
)


@dataclass(frozen=True)
class Event:
    event: str
    step: str
    level: str = "INFO"
    run_id: int | None = None
    as_of: date | None = None
    feed: str | None = None
    load_id: int | None = None
    rows: int | None = None
    rows_rejected: int | None = None
    reject_rate: Decimal | None = None
    duration_ms: int | None = None
    exit_code: int | None = None
    peak_rss_mb: Decimal | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.event not in EVENTS or self.step not in STEPS or self.level not in LEVELS:
            raise ValueError(f"unknown log event {self.event!r}, step {self.step!r} or level {self.level!r}")


def utc_now() -> datetime:
    return datetime.now(UTC)


def emit(event: Event, stream: TextIO = sys.stdout, now: Callable[[], datetime] = utc_now) -> None:
    values = asdict(event) | {"ts": now().isoformat(timespec="milliseconds")}
    stream.write(json.dumps({name: values[name] for name in FIELDS}, default=_json_value, ensure_ascii=False) + "\n")
    stream.flush()


def run_end(run_id: int | None, exit_code: int, duration_ms: int, stream: TextIO = sys.stdout) -> None:
    level = "INFO" if exit_code == 0 else "ERROR"
    emit(
        Event(
            "run_end",
            "run",
            level=level,
            run_id=run_id,
            exit_code=exit_code,
            duration_ms=duration_ms,
            peak_rss_mb=peak_rss_mb(),
        ),
        stream,
    )


def peak_rss_mb() -> Decimal:
    peak = Decimal(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = Decimal(1024 * 1024) if sys.platform == "darwin" else Decimal(1024)
    return (peak / divisor).quantize(Decimal("0.1"))


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not serialisable in a log line: {type(value).__name__}")
