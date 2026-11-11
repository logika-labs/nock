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


def due(protocol: Any) -> str:
    days = protocol.setting("days")
    return Logika(protocol.project).due(
        protocol.rounds.last(), float(days if days is not None else 30)
    )


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
