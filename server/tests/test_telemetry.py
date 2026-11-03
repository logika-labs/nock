"""The server's own spans, through the real OpenTelemetry SDK: each is declared in `logika.json` with
exactly its params, an expected refusal is no error, and nothing a sender is or sent leaves in them."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from opentelemetry.trace import StatusCode

from tests.conftest import Api, Clock, Spans
from tests.test_api import REPORT

LEDGER = json.loads((Path(__file__).resolve().parents[1] / "logika.json").read_text())
SENDER = "203.0.113.77"
SUMMARY = "The toolbox grew a deploy tool."


def declared() -> dict[str, tuple[set[str], set[str]]]:
    """Each event's span name to its (required, optional) params."""
    events: dict[str, tuple[set[str], set[str]]] = {}

    def walk(event: dict[str, Any], prefix: str) -> None:
        name = prefix + event["name"]
        params = event.get("params", [])
        events[name] = (
            {param for param in params if not param.endswith("?")},
            {param.removesuffix("?") for param in params if param.endswith("?")},
        )
        for child in event.get("children", []):
            walk(child, name + ".")

    for event in LEDGER["events"]:
        walk(event, "")
    return events


def test_every_span_is_declared_with_its_params_and_carries_nothing_sent(
    api: Api, clock: Clock, spans: Spans
) -> None:
    assert api.post("/reflections", {"summary": SUMMARY, "round": "2026-11-01"}, SENDER)[0] == 201
    assert api.post("/usage", REPORT, SENDER)[0] == 201
    assert api.post("/usage", {**REPORT, "level": "x"}, SENDER)[0] == 400
    assert api.post("/reflections", b"{" + b" " * 80_000 + b"}", SENDER)[0] == 413
    assert api.post("/usage", REPORT, SENDER)[0] == 201
    assert api.post("/usage", REPORT, SENDER)[0] == 429
    finished = [
        span
        for span in spans.finished()
        if span.instrumentation_scope and span.instrumentation_scope.name == "nock_api"
    ]
    events = declared()
    for span in finished:
        required, optional = events[span.name]
        attributes = dict(span.attributes or {})
        assert required <= set(attributes) <= required | optional, span.name
        for value in attributes.values():
            assert SENDER not in str(value) and "toolbox" not in str(value)
    by_name = {span.name: span for span in finished}
    assert dict(by_name["reflection.kept"].attributes or {}) == {
        "row_id": 1,
        "summary_chars": len(SUMMARY),
        "dated": True,
    }
    assert dict(by_name["usage.kept"].attributes or {})["schema"] == 2
    refusals = [dict(span.attributes or {}) for span in finished if span.name.endswith(".refused")]
    assert refusals == [
        {"http_status": 400, "reason": "fields"},
        {"http_status": 413, "reason": "too_large"},
    ]
    assert dict(by_name["limited"].attributes or {}) == {"retry_after": 10}
    operations = [span for span in finished if span.name in ("reflection", "usage")]
    assert len(operations) == 5
    assert all(span.status.status_code is not StatusCode.ERROR for span in operations)
    for span in finished:
        if span.name.endswith((".kept", ".refused")):
            assert span.parent is not None


def test_a_key_the_enhancer_cannot_use_never_takes_the_server_down(
    empty_database_url: str,
) -> None:
    environment = {
        **os.environ,
        "DATABASE_URL": empty_database_url,
        "OTEL_EXPORTER_OTLP_HEADERS": "authorization=Bearer not-a-key",
        # Nothing listens there: the enhancer's handshake cannot succeed.
        "LOGIKA_CONTROL_URL": "http://127.0.0.1:9",
    }
    ran = subprocess.run(
        [sys.executable, "-m", "nock_api", "migrate"],
        capture_output=True,
        text=True,
        env=environment,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )
    assert ran.returncode == 0, ran.stderr
    assert "1 migration(s) applied" in ran.stdout
