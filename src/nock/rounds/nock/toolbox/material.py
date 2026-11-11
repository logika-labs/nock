"""The toolbox round's material: the telemetry since the last toolbox round."""

from __future__ import annotations

from typing import Any

from nock.reflect import Material, Reflection, Window
from nock.sessions import Sessions


def window(protocol: Any) -> Window:
    sessions = Sessions(protocol.project)
    sessions.catch_up()
    return Window(protocol.since, sessions.since(protocol.since))


def process(protocol: Any) -> str:
    return Material(protocol.project, window(protocol), protocol.rounds.last()).render()


def kept(protocol: Any, started: dict[str, Any]) -> dict[str, Any]:
    """Each tool's numbers over the window, for the next round to compare."""
    return {"snapshot": Reflection(protocol.project).snapshot(started["since"])}
