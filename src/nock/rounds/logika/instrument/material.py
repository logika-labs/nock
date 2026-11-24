"""The logika instrument subround's material: the repository's `logika map`
when the run starts, its open items and the reasons earlier runs left them
with; and its measure, how much the map's open items grew since the last run."""

from __future__ import annotations

from typing import Any

from nock.logika import Instrument, Logika, Map

# The open items its measure counts: events no rule reads, verdict-only events.
COUNTED = ("unread", "verdicts")


def instrument(subround: Any) -> str:
    return Instrument(Map(subround.project), subround.runs.all()).render()


def unavailable(subround: Any) -> str:
    return Logika(subround.project).unavailable()


def measure(subround: Any, base: dict[str, Any]) -> tuple[int | None, str]:
    """How much `logika map`'s open items grew since the subround's baseline."""
    counts = Map(subround.project).counts()
    if counts is None:
        return None, "open items"
    before = (base.get("open") or {}) if base.get("subround") == subround.name else {}
    grown = sum(counts.get(kind, 0) for kind in COUNTED) - sum(
        int(before.get(kind) or 0) for kind in COUNTED
    )
    return max(grown, 0), "more open items in logika map"


def begun(subround: Any) -> dict[str, Any]:
    logika = Logika(subround.project)
    return {
        "ledger": logika.ledger.counts(logika.ledger.read()),
        "open": Map(subround.project).counts(),
    }


def kept(subround: Any, started: dict[str, Any]) -> dict[str, Any]:
    logika = Logika(subround.project)
    return {
        "ledger_before": started["ledger"],
        "ledger": logika.ledger.counts(logika.ledger.read()),
        "open_before": started["open"],
        "open": Map(subround.project).counts(),
    }


def problems(subround: Any) -> list[str]:
    return Logika(subround.project).problems()
