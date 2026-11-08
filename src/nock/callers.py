"""Which agent of a Claude Code session runs a nock command. A subagent's
commands carry its parent's session id (`CLAUDE_CODE_SESSION_ID`) and
nothing of its own; only Claude Code's hook input names the subagent
(`agent_id`, `agent_type`). So the before-tool hook notes every `.nock/nock`
command a session's agents are about to run, and the command, once running,
claims the newest note of its session whose words it carries."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from nock.store import Store
from nock.utils import now, parse_moment

# How long a note waits to be claimed: a command may wait on a permission prompt.
WINDOW = timedelta(hours=1)
# The arguments a shell leaves as they are in the command line, so matching them is exact.
PLAIN = re.compile(r"^[\w./:@=+,-]+$")
MARK = ".nock/nock"


class Callers:
    def __init__(self, store: Store) -> None:
        self.store = store

    def note(self, payload: dict[str, Any]) -> None:
        """From the before-tool hook: a Bash command about to run nock."""
        session = payload.get("session_id")
        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(session, str) or not isinstance(command, str) or MARK not in command:
            return
        agent = payload.get("agent_id")
        kind = payload.get("agent_type")
        self.store.insert(
            "callers",
            {
                "session": session,
                "agent": agent if isinstance(agent, str) and agent else None,
                "type": kind if isinstance(kind, str) and kind else None,
                "command": command,
                "moment": now(),
            },
        )

    def claim(self, session: str, arguments: list[str]) -> dict[str, Any] | None:
        """The note of the command now running in this session: the newest
        unclaimed one carrying each of its plain arguments; marked claimed."""
        moment = parse_moment(now())
        since = (moment - WINDOW).isoformat().replace("+00:00", "Z") if moment else ""
        words = [argument for argument in arguments if PLAIN.match(argument)]
        with self.store.connection() as connection:
            rows = connection.execute(
                "SELECT rowid, agent, type, command FROM callers"
                " WHERE session = ? AND claimed = 0 AND moment >= ? ORDER BY rowid DESC",
                (session, since),
            ).fetchall()
            for row in rows:
                if all(word in row["command"] for word in words):
                    connection.execute(
                        "UPDATE callers SET claimed = 1 WHERE rowid = ?", (row["rowid"],)
                    )
                    return {"agent": row["agent"], "type": row["type"]}
        return None
