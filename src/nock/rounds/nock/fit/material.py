"""The fit round's material: the window's numbers beside every earlier
round's; the catalogue of rounds with each one's settings here, to set them
up for this project; and the memory as it stands, to keep it."""

from __future__ import annotations

from typing import Any

from nock.reflect import Evidence, Knowledge, Reflection
from nock.rounds import subrounds


def metrics(subround: Any) -> dict[str, Any]:
    reflection = Reflection(subround.project)
    return reflection.metrics(reflection.window())


def evidence(subround: Any) -> str:
    return Evidence(
        subround.project,
        metrics(subround),
        subround.runs.all(),
    ).render()


def knowledge(subround: Any) -> str:
    return Knowledge(subround.project, subround.since).render()


def catalogue(subround: Any) -> str:
    lines = [
        "# The rounds there are, and their settings here",
        "",
        "Each round is on unless the config turns it off, and due when its measure crosses its"
        ' threshold since its last run. Settings live in `.nock/config.toml`, `[rounds."NAME"]`:'
        " `enabled`, `paths` (globs: what it looks at), `any` (globs: a change to one makes it due"
        " at once), `threshold`.",
        "",
    ]
    for other in subrounds(subround.project):
        standing = other.standing()
        measure = standing["measure"]
        state = (
            f"cannot run here: {standing['unavailable']}"
            if standing["unavailable"]
            else "on"
            if standing["on"]
            else "off"
        )
        counted = (
            f"{measure['value']} of {measure['threshold']} {measure['unit']}"
            if measure["value"] is not None
            else f"measure {measure['measure']}, threshold {measure['threshold']}"
        )
        lines.append(
            f"- `{other.name}` ({state}; {counted}; last run {standing['last'] or 'never'}):"
            f" {standing['summary']} For: {other.manifest.data.get('relevant') or 'any project'}"
        )
        if standing["paths"]:
            lines.append(f"  paths: {', '.join(standing['paths'])}")
        configured = other.config()
        if configured:
            lines.append(f"  set here: {configured}")
    return "\n".join(lines) + "\n"


def begun(subround: Any) -> dict[str, Any]:
    return {"metrics": metrics(subround)}


def kept(subround: Any, started: dict[str, Any]) -> dict[str, Any]:
    return {"metrics": started["metrics"], "shared": None}
