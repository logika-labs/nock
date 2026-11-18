"""The file kinds of `.nock/shared/`: each event's schema by where it lives
(a topic, an item, an asset, the review), an asset version's `asset.json`,
a review version's `review.json` and its blocks, and how an event file is
named. Agents write these files; `nock.shared` validates, completes and
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
ASSET_FILE_NAME = "asset.json"
# Text kept beside a version in git; anything larger, or not text, is media.
SMALL_TEXT = 256 * 1024
# The fields an event's writer never gives: completing the event fills them.
ENVELOPE = ("moment", "id", "by")

STATES = ["planned", "active", "review", "done", "abandoned"]
# What an item is: a decision, done and carried on with; a proposal, a todo the
# agent wants done, which the owner accepts (it becomes a decision once done)
# or rejects (dropped).
TYPES = ["decision", "proposal"]
VERDICTS = ["accepted", "rejected"]
TEXT = {"type": "string"}
LINE = {"type": "string", "maxLength": 2000}
# A few lines on what it means for the owner: behaviour, cost, what users see.
MEANS = {"type": "string", "maxLength": 1200}
REVIEW_FILE = "review.json"

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
# What a note is pinned on: an item, an asset (a version, a line of it), a block
# of the review (a span of its text); at least one of item, asset, block.
TARGET = {
    "type": "object",
    "properties": {
        "item": TEXT,
        "asset": TEXT,
        "version": {"type": "integer", "minimum": 1},
        "line": {"type": "integer", "minimum": 1},
        "side": {"enum": ["before", "after"]},
        "block": TEXT,
        "review": {"type": "integer", "minimum": 1},
        "quote": {"type": "string", "maxLength": 2000},
        "memory": {"type": "boolean", "description": "a line of .nock/shared/memory.md"},
    },
    "additionalProperties": False,
}
MESSAGE = {
    "text": TEXT,
    "attachments": {"type": "array", "items": ATTACHMENT},
    "answers": {**TEXT, "description": "the id of the message it answers"},
    "notes": {
        "type": "array",
        "items": {"type": "string", "pattern": "^[0-9a-f]{8}$"},
        "description": "the owner's notes it carries, by id",
    },
    "now": {"type": "boolean", "description": "the owner asked for an answer now"},
    "blocks": {
        "type": "array",
        "items": {"type": "object"},
        "description": "what an agent's reply shows: the review's blocks",
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
    "note": {
        "required": ["on", "text"],
        "properties": {
            "on": TARGET,
            "text": TEXT,
            "replaces": {**TEXT, "description": "the note it edits; empty text removes it"},
        },
    },
    "reviewed": {
        "required": ["version"],
        "properties": {"version": {"type": "integer", "minimum": 1}},
    },
    "plan": {
        "required": ["steps"],
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["title", "estimate"],
                    "properties": {
                        "title": LINE,
                        "estimate": {
                            "type": "number",
                            "minimum": 0,
                            "description": "minutes",
                        },
                    },
                    "additionalProperties": False,
                },
            }
        },
    },
    "step": {
        "required": ["title", "state"],
        "properties": {"title": LINE, "state": {"enum": ["started", "done"]}},
    },
}
ITEM_EVENTS: dict[str, dict[str, Any]] = {
    "created": {
        "required": ["type", "title", "means"],
        "properties": {
            "type": {"enum": TYPES},
            "title": LINE,
            "means": MEANS,
            "why": LINE,
            "takes": LINE,
        },
    },
    "revised": {
        "properties": {"title": LINE, "means": MEANS, "why": LINE, "takes": LINE},
    },
    "verdict": {"required": ["verdict"], "properties": {"verdict": {"enum": VERDICTS}}},
    "implemented": {
        "properties": {"means": MEANS, "why": LINE},
    },
}
ASSET_EVENTS: dict[str, dict[str, Any]] = {
    "created": {"required": ["title"], "properties": {"title": LINE, "description": TEXT}},
    "titled": {"properties": {"title": LINE, "description": TEXT}},
    "version": {
        "required": ["version"],
        "properties": {"version": {"type": "integer", "minimum": 1}},
    },
}
REVIEW_EVENTS: dict[str, dict[str, Any]] = {
    "version": {
        "required": ["version"],
        "properties": {"version": {"type": "integer", "minimum": 1}},
    },
}
PLACES = {
    "topic": TOPIC_EVENTS,
    "item": ITEM_EVENTS,
    "asset": ASSET_EVENTS,
    "review": REVIEW_EVENTS,
}

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
    },
    "additionalProperties": False,
}
ASSET = {
    "type": "object",
    "required": ["file"],
    "properties": {
        "file": ASSET_FILE,
        "blobs": {
            "type": "object",
            "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    },
    "additionalProperties": False,
}

# The review's blocks, by kind: each block's own fields, the required first.
SERIES = {
    "type": "object",
    "required": ["name", "values"],
    "properties": {"name": TEXT, "values": {"type": "array", "items": {"type": "number"}}},
    "additionalProperties": False,
}
BLOCKS: dict[str, dict[str, Any]] = {
    "text": {"required": ["text"], "properties": {"text": TEXT}},
    "item": {"required": ["item"], "properties": {"item": TEXT}},
    "diff": {
        "required": ["asset"],
        "properties": {
            "asset": TEXT,
            "from": {"type": "integer", "minimum": 1},
            "to": {"type": "integer", "minimum": 1},
        },
    },
    "doc": {
        "required": ["asset"],
        "properties": {"asset": TEXT, "version": {"type": "integer", "minimum": 1}},
    },
    "excerpt": {
        "required": ["asset", "lines"],
        "properties": {
            "asset": TEXT,
            "version": {"type": "integer", "minimum": 1},
            "lines": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "minItems": 2,
                "maxItems": 2,
            },
        },
    },
    "image": {
        "required": ["asset"],
        "properties": {"asset": TEXT, "version": {"type": "integer", "minimum": 1}},
    },
    "table": {
        "required": ["columns", "rows"],
        "properties": {
            "columns": {"type": "array", "items": TEXT},
            "rows": {"type": "array", "items": {"type": "array"}},
        },
    },
    "chart": {
        "required": ["chart", "labels", "series"],
        "properties": {
            "chart": {"enum": ["bar", "line"]},
            "labels": {"type": "array", "items": TEXT},
            "series": {"type": "array", "items": SERIES, "minItems": 1},
            "unit": TEXT,
        },
    },
    "html": {
        "required": ["file"],
        "properties": {
            "file": TEXT,
            "height": {"type": "integer", "minimum": 40, "maximum": 4000},
        },
    },
}
BLOCK_COMMON = {
    "kind": TEXT,
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,63}$"},
    "caption": LINE,
    "title": LINE,
}
REVIEW = {
    "type": "object",
    "required": ["summary", "blocks"],
    "properties": {
        "summary": LINE,
        "blocks": {"type": "array", "items": {"type": "object"}, "minItems": 1},
    },
    "additionalProperties": False,
}


def block_problems(block: Any) -> list[str]:
    """What is wrong with one block of a review: its kind and its fields."""
    if not isinstance(block, dict):
        return ["a block is a JSON object"]
    kind = block.get("kind")
    if kind not in BLOCKS:
        return [f"`kind` is one of {', '.join(BLOCKS)}, not {kind!r}"]
    own = BLOCKS[kind]
    schema = {
        "type": "object",
        "required": ["kind", *own["required"]],
        "properties": {**BLOCK_COMMON, **own["properties"]},
        "additionalProperties": False,
    }
    return Validator().problems(block, schema)


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
