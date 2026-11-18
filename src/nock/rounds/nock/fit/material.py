"""The fit round's material: the window's numbers beside every earlier
round's; the catalogue of rounds with each one's settings here, to set them
up for this project; and how the owner meets the reviews (the html blocks
agents wrote, the owner's notes on how things are shown, what they skipped),
to grow the studio's blocks and the project's review preferences."""

from __future__ import annotations

from typing import Any

from nock.reflect import Evidence, Knowledge, Reflection
from nock.rounds import protocols


def metrics(protocol: Any) -> dict[str, Any]:
    reflection = Reflection(protocol.project)
    return reflection.metrics(reflection.window())


def evidence(protocol: Any) -> str:
    return Evidence(
        protocol.project,
        metrics(protocol),
        protocol.rounds.all(),
    ).render()


def knowledge(protocol: Any) -> str:
    return Knowledge(protocol.project, protocol.since).render()


def catalogue(protocol: Any) -> str:
    lines = [
        "# The rounds there are, and their settings here",
        "",
        "Each round is on unless the config turns it off, and due when its measure crosses its"
        ' threshold since its last run. Settings live in `.nock/config.toml`, `[rounds."NAME"]`:'
        " `enabled`, `paths` (globs: what it looks at), `any` (globs: a change to one makes it due"
        " at once), `threshold`.",
        "",
    ]
    for other in protocols(protocol.project):
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


def presentation(protocol: Any) -> str:
    """How the owner meets the reviews since the last run: the html blocks
    agents wrote (a recurring one is a built-in to be), the owner's notes on
    review blocks (how things are shown), and what they skipped (reviews
    replaced or left without Done, proposals left undecided)."""
    from nock.topics import Topics

    topics = Topics(protocol.project)
    since = protocol.since or ""
    html, notes, skipped = [], [], []
    for name in topics.names():
        topic = topics.topic(name)
        review = topics.review(name)
        done = {entry["version"] for entry in topic["reviewed"]}
        versions = review["versions"]
        for version in versions:
            if version["moment"] <= since:
                continue
            for block in version["blocks"]:
                if block["kind"] == "html":
                    path = (
                        topics.shared.review_folder(name)
                        / "versions"
                        / str(version["version"])
                        / block["file"]
                    )
                    head = path.read_text(errors="replace")[:600] if path.is_file() else ""
                    html.append(
                        f"- {name} v{version['version']} `{block['file']}`"
                        f" ({block.get('title') or block.get('caption') or 'untitled'}):"
                        f" {' '.join(head.split())[:300]}"
                    )
            if version["version"] not in done and version is not versions[-1]:
                skipped.append(f"- {name}: review v{version['version']} was replaced before Done")
        if (
            versions
            and versions[-1]["version"] not in done
            and topic["state"] in ("done", "abandoned")
        ):
            skipped.append(f"- {name}: closed with its review never done")
        blocks = {block["id"]: block for version in versions for block in version["blocks"]}
        for note in topic["notes"]:
            if note["moment"] <= since:
                continue
            on = note["on"]
            kind = blocks.get(on.get("block") or "", {}).get("kind")
            where = (
                f"block {on['block']} ({kind})"
                if on.get("block")
                else (f"asset {on['asset']}" if on.get("asset") else f"item {on.get('item')}")
            )
            notes.append(f"- {name}, {where}: {' '.join(note['text'].split())[:300]}")
        if topic["state"] in ("done", "abandoned"):
            skipped += [
                f"- {name}: proposal [{item['ref']}] left undecided"
                for item in topics.items(name)
                if item["status"] == "open"
            ]
    return "\n".join(
        [
            "# How the owner meets the reviews",
            "",
            "## The html blocks agents wrote",
            "",
            *(html or ["None."]),
            "",
            "## The owner's notes (those on blocks are about how things are shown, often)",
            "",
            *(notes or ["None."]),
            "",
            "## What the owner skipped",
            "",
            *(skipped or ["Nothing."]),
            "",
        ]
    )


def begun(protocol: Any) -> dict[str, Any]:
    return {"metrics": metrics(protocol)}


def kept(protocol: Any, started: dict[str, Any]) -> dict[str, Any]:
    return {"metrics": started["metrics"], "shared": None}
