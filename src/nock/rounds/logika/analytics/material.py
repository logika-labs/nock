"""The logika analytics round's material: what the ledger already says, the
commits since, what earlier rounds left."""

from __future__ import annotations

from typing import Any

from nock.logika import Analytics, Logika


def analytics(protocol: Any) -> str:
    logika = Logika(protocol.project)
    return Analytics(logika, logika.ledger.read(), protocol.rounds.last()).render()


def unavailable(protocol: Any) -> str:
    return Logika(protocol.project).unavailable()


def measure(protocol: Any, base: dict[str, Any]) -> tuple[int | None, str]:
    """How many events logika.json gained since the round's baseline."""
    logika = Logika(protocol.project)
    try:
        events = logika.ledger.counts(logika.ledger.read())["events"]
    except Exception:
        return None, "events added"
    before = (base.get("ledger") or {}).get("events")
    if before is None:
        before = 0 if base.get("protocol") != protocol.name else events
    return max(events - int(before), 0), "events added to logika.json"


def begun(protocol: Any) -> dict[str, Any]:
    logika = Logika(protocol.project)
    return {"ledger": logika.ledger.counts(logika.ledger.read())}


def kept(protocol: Any, started: dict[str, Any]) -> dict[str, Any]:
    logika = Logika(protocol.project)
    return {
        "ledger_before": started["ledger"],
        "ledger": logika.ledger.counts(logika.ledger.read()),
    }


def problems(protocol: Any) -> list[str]:
    return Logika(protocol.project).problems()
