"""The file kinds of `.nock/shared/`: each event's schema by where it lives
(a topic, a decision, an asset of a decision), a decision version's
`decision.json` and an asset version's `assets.json`, and how an event file
is named. Agents write these files; `nock.shared` validates, completes and
commits them, and `nock docs files` documents each with an example."""

from __future__ import annotations

import re
from typing import Any

from nock.schema import Validator

# An event's file once completed: `<stamp>-<id>.json`, the stamp its moment to
# the millisecond, so names sort in time order and `(stamp, id)` breaks ties.
EVENT_FILE = re.compile(r"^(?P<stamp>\d{8}T\d{6}\.\d{3}Z)-(?P<id>[0-9a-f]{8})\.json$")
# The folder an agent writes a new version into; completing it numbers it.
NEXT = "next"
DECISION_FILE = "decision.json"
ASSETS_FILE = "assets.json"
# Text kept beside a version in git; anything larger, or not text, is media.
SMALL_TEXT = 256 * 1024
# The fields an event's writer never gives: completing the event fills them.
ENVELOPE = ("moment", "id", "by")

STATES = ["planned", "active", "review", "done", "abandoned"]
VERDICTS = ["open", "accepted", "rejected", "dropped"]
TEXT = {"type": "string"}
LINE = {"type": "string", "maxLength": 2000}

ATTACHMENT = {
    "type": "object",
    "properties": {
        "path": {**TEXT, "description": "a file to attach, read when the event is completed"},
        "name": TEXT,
        "type": TEXT,
        "bytes": {"type": "integer"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "additionalProperties": False,
}
MESSAGE = {
    "text": TEXT,
    "attachments": {"type": "array", "items": ATTACHMENT},
    "answers": {**TEXT, "description": "the id of the message it answers"},
    "now": {"type": "boolean", "description": "sent with Address now"},
    "withdraws": {**TEXT, "description": "the id of the owner's message it takes back"},
    "verdict": {"enum": VERDICTS, "description": "the verdict a comment came with"},
    "note": {
        "enum": ["task", "split", "revival"],
        "description": "nock's own note, kept from an earlier layout",
    },
}

# Each event kind's own fields, by where it lives.
TOPIC_EVENTS: dict[str, dict[str, Any]] = {
    "created": {
        "required": ["description"],
        "properties": {"description": TEXT, "state": {"enum": STATES}, "status": LINE},
    },
    "described": {"required": ["description"], "properties": {"description": TEXT}},
    "renamed": {
        "required": ["name"],
        "properties": {"name": TEXT, "from": TEXT},
    },
    "state": {
        "properties": {
            "state": {"enum": STATES},
            "status": LINE,
            "priority": {"type": "integer", "minimum": 0},
            "revived": {"type": "boolean"},
            "note": TEXT,
        }
    },
    "message": {"properties": MESSAGE},
}
DECISION_EVENTS: dict[str, dict[str, Any]] = {
    "created": {
        "required": ["title"],
        "properties": {
            "title": LINE,
            "description": TEXT,
            "aliases": {"type": "array", "items": TEXT},
        },
    },
    "titled": {"properties": {"title": LINE, "description": TEXT}},
    "version": {
        "required": ["version"],
        "properties": {"version": {"type": "integer", "minimum": 1}},
    },
    "verdict": {
        "required": ["verdict"],
        "properties": {"verdict": {"enum": VERDICTS}, "comment": TEXT},
    },
    "moved": {"required": ["to"], "properties": {"from": TEXT, "to": TEXT}},
    "message": {"properties": MESSAGE},
}
ASSET_EVENTS: dict[str, dict[str, Any]] = {
    "created": {"required": ["title"], "properties": {"title": LINE, "description": TEXT}},
    "titled": {"properties": {"title": LINE, "description": TEXT}},
    "version": {
        "required": ["version"],
        "properties": {"version": {"type": "integer", "minimum": 1}},
    },
    "preferred": {
        "required": ["version"],
        "properties": {
            "version": {"type": "integer", "minimum": 1},
            "name": {"type": ["string", "null"]},
        },
    },
}
PLACES = {"topic": TOPIC_EVENTS, "decision": DECISION_EVENTS, "asset": ASSET_EVENTS}

BY = {
    "type": "object",
    "properties": {
        "author": {"enum": ["owner", "agent"]},
        "on_behalf": {"enum": ["interactive", "agent"]},
        "user": {"type": ["string", "null"]},
        "session": {"type": ["string", "null"]},
        "parent": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]},
        "host": {"type": ["string", "null"]},
    },
    "required": ["author"],
}

DECISION = {
    "type": "object",
    "required": ["answer"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["option", "why_not"],
                "properties": {"option": TEXT, "why_not": TEXT},
                "additionalProperties": False,
            },
        },
        "status": {"enum": ["done", "todo"]},
    },
    "additionalProperties": False,
}
RECIPE = {
    "type": "object",
    "properties": {"command": TEXT, "instruction": TEXT},
    "additionalProperties": False,
}
ASSET_FILE = {
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {"enum": ["project", "derived"]},
        "path": {**TEXT, "description": "a project file: its path in the repository"},
        "commit": {"type": "string", "pattern": "^[0-9a-f]{7,64}$"},
        "name": {**TEXT, "description": "a derived file: its name beside the version"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "type": TEXT,
        "bytes": {"type": "integer"},
        "from": {"type": "array", "items": TEXT},
        "when": {"type": ["string", "null"]},
        "recipe": {"anyOf": [RECIPE, {"type": "null"}]},
        "captions": TEXT,
        "poster": TEXT,
        "local": {"type": "boolean"},
    },
    "additionalProperties": False,
}
ASSETS = {
    "type": "object",
    "properties": {
        "variants": {"type": "boolean"},
        "files": {"type": "array", "items": ASSET_FILE},
        "views": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": TEXT, "title": TEXT, "bytes": {"type": "integer"}},
                "additionalProperties": False,
            },
        },
        "blobs": {
            "type": "object",
            "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    },
    "additionalProperties": False,
}


def event_schema(kinds: dict[str, dict[str, Any]], kind: str, complete: bool) -> dict[str, Any]:
    """The whole schema of one kind of event: its own fields and, once
    completed, the envelope; a draft may not give the envelope."""
    own = kinds[kind]
    properties = {"kind": {"const": kind}, **own.get("properties", {})}
    required = ["kind", *own.get("required", [])]
    if complete:
        properties |= {
            "moment": TEXT,
            "id": {"type": "string", "pattern": "^[0-9a-f]{8}$"},
            "by": BY,
        }
        required += list(ENVELOPE)
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def event_problems(record: Any, place: str, complete: bool) -> list[str]:
    """What is wrong with an event of a topic, a decision or an asset
    (`place`): its kind, its fields, and the envelope, which a draft never
    gives."""
    kinds = PLACES[place]
    if not isinstance(record, dict):
        return ["an event is a JSON object"]
    kind = record.get("kind")
    if kind not in kinds:
        return [f"`kind` is one of {', '.join(sorted(kinds))} for a {place} event, not {kind!r}"]
    if not complete:
        given = [field for field in ENVELOPE if field in record]
        if given:
            return [f"leave out {', '.join(given)}: nock fills them in"]
    return Validator().problems(record, event_schema(kinds, kind, complete))


def shape_problems(record: Any, schema: dict[str, Any]) -> list[str]:
    return Validator().problems(record, schema)
