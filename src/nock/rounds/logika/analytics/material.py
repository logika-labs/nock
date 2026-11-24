"""The logika analytics round's material: what the ledger already says, the
commits since, what earlier runs left."""

from __future__ import annotations

from typing import Any

from nock.logika import Analytics, Logika


def analytics(subround: Any) -> str:
    logika = Logika(subround.project)
    return Analytics(logika, logika.ledger.read(), subround.runs.last()).render()


def unavailable(subround: Any) -> str:
    return Logika(subround.project).unavailable()


def measure(subround: Any, base: dict[str, Any]) -> tuple[int | None, str]:
    """How many events logika.json gained since the round's baseline."""
    logika = Logika(subround.project)
    try:
        events = logika.ledger.counts(logika.ledger.read())["events"]
    except Exception:
        return None, "events added"
    before = (base.get("ledger") or {}).get("events")
    if before is None:
        before = 0 if base.get("subround") != subround.name else events
    return max(events - int(before), 0), "events added to logika.json"


def begun(subround: Any) -> dict[str, Any]:
    logika = Logika(subround.project)
    return {"ledger": logika.ledger.counts(logika.ledger.read())}


def kept(subround: Any, started: dict[str, Any]) -> dict[str, Any]:
    logika = Logika(subround.project)
    return {
        "ledger_before": started["ledger"],
        "ledger": logika.ledger.counts(logika.ledger.read()),
    }


def problems(subround: Any) -> list[str]:
    return Logika(subround.project).problems()
