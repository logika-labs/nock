"""The telemetry store: one SQLite database in `.nock/local/`, never committed —
every call to a nock command, every supervised process, and what each Claude
Code session did (and how far its transcript has been read), read from its transcript (and which items it was told of or
shown), and which of a session's agents runs each nock command. Reflection reads it; so can any
agent, with `nock query`."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nock.errors import UsageError

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,          -- the command as typed: `failures`, `gen add`; unknown ones too
    arguments TEXT NOT NULL,     -- JSON list of the words after the command
    source TEXT,                 -- `nock`, or the tools file that defines it
    session TEXT,
    directory TEXT,
    started TEXT NOT NULL,
    duration REAL,               -- seconds
    exit_code INTEGER,
    output_bytes INTEGER,        -- what the caller read, after condensing and capping
    output_lines INTEGER,
    full_bytes INTEGER,          -- what it would have read uncapped
    cached INTEGER DEFAULT 0,
    error TEXT,                  -- the first line of what went wrong
    fingerprint TEXT,            -- hash of the output, to notice a repeat
    tree TEXT                    -- hash of HEAD and the dirty files, on failure
);
CREATE INDEX IF NOT EXISTS calls_tool ON calls (tool, started);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call INTEGER,                -- the nock call that started it
    command TEXT NOT NULL,       -- JSON argv
    directory TEXT,
    session TEXT,
    started TEXT NOT NULL,
    finished TEXT,
    exit_code INTEGER,
    pid INTEGER,
    supervisor INTEGER,
    note TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    role TEXT,                   -- `interactive`, `headless` (`claude -p`, the SDK), or the role nock dispatched it as
    title TEXT,
    started TEXT,
    ended TEXT,
    model TEXT,
    prompts INTEGER,
    interrupts INTEGER,
    compactions INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    cost REAL,                   -- dollars at API prices (API-equivalent); NULL when unpriced
    transcript TEXT,
    ingested TEXT
);
CREATE TABLE IF NOT EXISTS prompts (
    session TEXT NOT NULL,
    moment TEXT,
    text TEXT NOT NULL           -- what the human typed, up to 600 characters
);
CREATE INDEX IF NOT EXISTS prompts_session ON prompts (session);
CREATE TABLE IF NOT EXISTS events (
    session TEXT NOT NULL,
    moment TEXT,
    tool TEXT NOT NULL,          -- Claude Code's tool: Bash, Read, Edit, Grep…
    input TEXT,                  -- the command, path or pattern, up to 400 characters
    failed INTEGER,
    output_bytes INTEGER,
    duration REAL                -- seconds between the call and its result
);
CREATE INDEX IF NOT EXISTS events_session ON events (session);
CREATE TABLE IF NOT EXISTS transcripts (
    session TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    offset INTEGER NOT NULL,     -- bytes read so far, to the end of a whole line
    state TEXT NOT NULL          -- JSON: the totals and open tool calls reading on needs
);
CREATE TABLE IF NOT EXISTS told (
    session TEXT NOT NULL,       -- a session told of the owner's word on an item it made
    item TEXT NOT NULL,          -- the item's ref, topic/slug
    updated TEXT NOT NULL        -- the owner's word on it, as told: its moment and digest (`owner_word`); a bare moment from an earlier nock
);
CREATE TABLE IF NOT EXISTS shown_items (
    session TEXT NOT NULL,       -- a session shown an item about a file it edited
    item TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS callers (
    session TEXT NOT NULL,       -- the Claude Code session a `.nock/nock` Bash command runs in
    agent TEXT,                  -- the subagent running it (hook input's `agent_id`); NULL: the session's own thread
    type TEXT,                   -- the subagent's type
    command TEXT NOT NULL,       -- the command, as the before-tool hook saw it
    moment TEXT NOT NULL,
    claimed INTEGER NOT NULL DEFAULT 0 -- 1 once the command, running, took it as its own
);
CREATE INDEX IF NOT EXISTS callers_session ON callers (session, claimed);
CREATE TABLE IF NOT EXISTS wrote (
    session TEXT NOT NULL,       -- a session that did work in a topic: opened it, or an item, a version or a reply there
    parent TEXT,                 -- the session that dispatched it, for a subagent or a session nock dispatched
    topic TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stated (
    session TEXT NOT NULL        -- a session the stop hook asked once to set its topics' status
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moment TEXT NOT NULL,        -- when the owner was told it is their turn in a topic
    topic TEXT NOT NULL,
    reason TEXT NOT NULL,        -- review, answered or reworked
    text TEXT NOT NULL,          -- what it said
    shown TEXT NOT NULL,         -- studio (a page watching), desktop, or nowhere (no display)
    event TEXT,                  -- the timeline event it told of (`nock.timeline`), by its key
    address TEXT,                -- where in the studio it leads: `#topics/REF~chat`
    preview TEXT                 -- the event's preview: what the agent said, the item's description
);
CREATE TABLE IF NOT EXISTS nudged (
    round TEXT NOT NULL          -- a round whose unshared summary, or a week's logika-round offer, a session start mentioned
);
"""


# Columns a table gained after it was first made: added to a database made before.
ADDED = {"notifications": (("event", "TEXT"), ("address", "TEXT"), ("preview", "TEXT"))}
# The databases already holding them, in this process.
CURRENT: set[Path] = set()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def add_columns(self, connection: sqlite3.Connection) -> None:
        if self.path in CURRENT:
            return
        for table, columns in ADDED.items():
            have = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns:
                if name not in have:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        CURRENT.add(self.path)

    @contextlib.contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(SCHEMA)
            self.add_columns(connection)
            yield connection
            connection.commit()
        finally:
            connection.close()

    def insert(self, table: str, values: dict[str, Any]) -> int:
        names = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self.connection() as connection:
            cursor = connection.execute(
                f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(values.values())
            )
            return int(cursor.lastrowid or 0)

    def update(self, table: str, key: int, values: dict[str, Any]) -> None:
        assignments = ", ".join(f"{name} = ?" for name in values)
        with self.connection() as connection:
            connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?", (*values.values(), key)
            )

    def rows(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(sql, parameters)]

    def query(self, sql: str) -> list[dict[str, Any]]:
        """A read-only query, as `nock query` runs it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection():
            pass  # make sure the schema exists before opening read-only
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(sql)]
        except sqlite3.Error as error:
            raise UsageError(f"{error} — the tables are: {', '.join(self.tables())}") from error
        finally:
            connection.close()

    def tables(self) -> list[str]:
        return [
            row["name"]
            for row in self.rows("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not row["name"].startswith("sqlite_")
        ]
