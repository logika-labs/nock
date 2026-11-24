"""The toolbox round's material: the telemetry since the last toolbox round."""

from __future__ import annotations

from typing import Any

from nock.reflect import Material, Reflection, Window
from nock.sessions import Sessions


def window(subround: Any) -> Window:
    sessions = Sessions(subround.project)
    sessions.catch_up()
    return Window(subround.since, sessions.since(subround.since))


def process(subround: Any) -> str:
    return Material(subround.project, window(subround), subround.runs.last()).render()


def kept(subround: Any, started: dict[str, Any]) -> dict[str, Any]:
    """Each tool's numbers over the window, for the next run to compare."""
    return {"snapshot": Reflection(subround.project).snapshot(started["since"])}
