"""The logika rules round's material: what the ledger already says, the
commits since, what earlier rounds left; and its measure, how much `logika
map`'s open items grew since the last run."""

from __future__ import annotations

from typing import Any

from nock.logika import Logika, Map, Material


def rules(protocol: Any) -> str:
    logika = Logika(protocol.project)
    return Material(logika, logika.ledger.read(), protocol.rounds.last()).render()


def unavailable(protocol: Any) -> str:
    return Logika(protocol.project).unavailable()


def measure(protocol: Any, base: dict[str, Any]) -> tuple[int | None, str]:
    """How much `logika map`'s open items (events no rule reads, verdict-only
    events) grew since the round's baseline."""
    counts = Map(protocol.project).counts()
    if counts is None:
        return None, "open items"
    before = (base.get("open") or {}) if base.get("protocol") == protocol.name else {}
    grown = sum(counts.get(kind, 0) for kind in ("unread", "verdicts")) - sum(
        int(before.get(kind) or 0) for kind in ("unread", "verdicts")
    )
    return max(grown, 0), "more open items in logika map"


def begun(protocol: Any) -> dict[str, Any]:
    logika = Logika(protocol.project)
    return {
        "ledger": logika.ledger.counts(logika.ledger.read()),
        "open": Map(protocol.project).counts(),
    }


def kept(protocol: Any, started: dict[str, Any]) -> dict[str, Any]:
    logika = Logika(protocol.project)
    return {
        "ledger_before": started["ledger"],
        "ledger": logika.ledger.counts(logika.ledger.read()),
        "open": started.get("open"),
    }


def problems(protocol: Any) -> list[str]:
    return Logika(protocol.project).problems()
