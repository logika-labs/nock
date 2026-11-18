"""The logika instrument round's material: the repository's `logika map` when
the round starts, its open items and the reasons earlier rounds left them with."""

from __future__ import annotations

from typing import Any

from nock.logika import Instrument, Logika, Map


def instrument(protocol: Any) -> str:
    return Instrument(Map(protocol.project), protocol.rounds.all()).render()


def unavailable(protocol: Any) -> str:
    return Logika(protocol.project).unavailable()


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
        "open_before": started["open"],
        "open": Map(protocol.project).counts(),
    }


def problems(protocol: Any) -> list[str]:
    return Logika(protocol.project).problems()
