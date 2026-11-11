"""The fit round's material: the window's numbers beside every earlier
round's, and the catalogue of rounds, to recommend the ones that fit."""

from __future__ import annotations

from typing import Any

from nock.reflect import Evidence, Reflection, feedback
from nock.rounds import protocols


def metrics(protocol: Any) -> dict[str, Any]:
    reflection = Reflection(protocol.project)
    return reflection.metrics(reflection.window())


def evidence(protocol: Any) -> str:
    return Evidence(
        protocol.project,
        metrics(protocol),
        protocol.rounds.all(),
        feedback(protocol.project, protocol.since),
    ).render()


def catalogue(protocol: Any) -> str:
    lines = ["# The rounds there are", ""]
    for other in protocols(protocol.project):
        standing = other.standing()
        state = (
            f"cannot run here: {standing['unavailable']}"
            if standing["unavailable"]
            else "adopted"
            if standing["adopted"]
            else "not adopted"
        )
        lines.append(
            f"- `{other.name}` ({state}): {standing['summary']} For: "
            f"{other.manifest.data.get('relevant') or 'any project'}"
        )
    return "\n".join(lines) + "\n"


def begun(protocol: Any) -> dict[str, Any]:
    return {"metrics": metrics(protocol)}


def kept(protocol: Any, started: dict[str, Any]) -> dict[str, Any]:
    return {"metrics": started["metrics"], "shared": None}
