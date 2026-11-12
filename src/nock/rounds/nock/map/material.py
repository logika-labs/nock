"""The map round's material: the decisions changed since the last map round, every topic, the map."""

from __future__ import annotations

from typing import Any

from nock.reflect import Knowledge, Window


def knowledge(protocol: Any) -> str:
    return Knowledge(protocol.project, Window(protocol.since, [])).render()
