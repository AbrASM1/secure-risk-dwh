import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import polars as pl
import pytest

from srdwh.contracts.feeds import COUNTERPARTY_COLUMNS, validate_feed
from srdwh.contracts.validation import ContractError
from srdwh.log import FIELDS, Event, emit, run_end

NAME = "Hélène Secretname"
LEI = "529900T8BM49AURSDO55"
NOW = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


def lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_line_fields() -> None:
    stream = io.StringIO()
    event = Event(
        "rejects_end",
        "rejects",
        run_id=7,
        as_of=date(2025, 1, 31),
        feed="exposure",
        load_id=3,
        rows_rejected=12,
        reject_rate=Decimal("0.0125"),
        duration_ms=40,
    )
    emit(event, stream, lambda: NOW)
    (line,) = lines(stream)
    assert list(line) == list(FIELDS)
    assert line["ts"] == "2026-01-31T12:00:00.000+00:00"
    assert datetime.fromisoformat(str(line["ts"])).utcoffset() is not None
    assert {k: line[k] for k in ("level", "event", "run_id", "step", "as_of", "feed", "load_id")} == {
        "level": "INFO",
        "event": "rejects_end",
        "run_id": 7,
        "step": "rejects",
        "as_of": "2025-01-31",
        "feed": "exposure",
        "load_id": 3,
    }
    assert (line["rows_rejected"], line["reject_rate"], line["duration_ms"], line["exit_code"]) == (
        12,
        0.0125,
        40,
        None,
    )


def test_last_line_peak_rss() -> None:
    stream = io.StringIO()
    emit(Event("run_start", "run", run_id=7), stream)
    run_end(7, 2, 1500, stream)
    last = lines(stream)[-1]
    assert (last["event"], last["exit_code"], last["level"], last["duration_ms"]) == ("run_end", 2, "ERROR", 1500)
    assert isinstance(last["peak_rss_mb"], float)
    assert last["peak_rss_mb"] > 0


def test_no_name_or_lei_in_logs() -> None:
    frame = pl.DataFrame(
        {column: ["x"] for column in COUNTERPARTY_COLUMNS} | {"cpty_name": [NAME * 300], "lei": [LEI * 300]}
    )
    with pytest.raises(ContractError) as error:
        validate_feed("counterparty", frame)
    stream = io.StringIO()
    emit(
        Event("structural_check_failed", "ingest", level="ERROR", feed="counterparty", message=str(error.value)), stream
    )
    output = stream.getvalue()
    assert NAME not in output
    assert LEI not in output
    assert "column=cpty_name check=max_bytes" in output


@pytest.mark.parametrize(
    ("event", "step", "level"),
    [("cpty_loaded", "ingest", "INFO"), ("load_end", "bronze", "INFO"), ("load_end", "ingest", "DEBUG")],
)
def test_unknown_event_rejected(event: str, step: str, level: str) -> None:
    with pytest.raises(ValueError, match="unknown log event"):
        Event(event, step, level=level)


def test_unserialisable_value_rejected() -> None:
    event = Event("error", "run", level="ERROR")
    object.__setattr__(event, "message", object())
    with pytest.raises(TypeError, match="not serialisable"):
        emit(event, io.StringIO())
