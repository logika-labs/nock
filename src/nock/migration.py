"""The move from decisions and review items to topics and items: each
decision becomes a decision item, each review item a derived-file item with
its versions and recipe, each old tag a topic (an item with several goes to
its first; one with none to `general`), notes and the owner's feedback thread
messages, verdicts kept. Done once per project, by `nock init` (so `nock
upgrade` does it too) or `nock topics migrate`; committed in one commit."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from nock.project import Project
from nock.topics import (
    CITATION,
    DECISION_FILE,
    GENERAL,
    ITEM_FILE,
    LARGE,
    MAP,
    NAME,
    TOPIC_FILE,
    Author,
    Topics,
    Verdict,
    checked_decision,
    committed,
    kind_of,
    slugged,
)
from nock.utils import now, read_json, write_json

# Tags that were never topics: the owner's call is now simply an open item.
UNTOPICAL = ("important",)
VERDICTS = {
    "unreviewed": Verdict.OPEN,
    "accepted": Verdict.ACCEPTED,
    "approved": Verdict.ACCEPTED,
    "rejected": Verdict.REJECTED,
}
DESCRIPTIONS = {
    GENERAL: "The decisions and review items that had no tag, from before topics.",
}


def topic_of(tags: list[str]) -> str:
    for tag in tags:
        name = re.sub(r"[^a-z0-9-]+", "-", tag.strip().lower()).strip("-")[:64]
        if name and name not in UNTOPICAL and NAME.match(name):
            return name
    return GENERAL


class Migration:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.topics = Topics(project)
        self.nock = project.root / ".nock"
        self.decisions = self.nock / "decisions"
        self.review = self.nock / "review"

    def pending(self) -> bool:
        return any(self.decisions.glob("[0-9]*.json")) or (
            self.review.is_dir() and any(self.review.rglob("version.json"))
        )

    def run(self) -> dict[str, Any]:
        """Migrate, and commit; what it made, by topic."""
        if not self.pending():
            return {"migrated": False}
        with self.project.lock("topics"):
            self.made: dict[str, dict[str, Any]] = {}
            self.slugs: dict[str, set[str]] = {}
            refs = self.migrate_decisions()
            items = self.migrate_review(refs)
            self.write_topics()
            moved_map = self.move_map()
            config = self.drop_tags()
            paths = [".nock/topics", ".nock/decisions", ".nock/review"]
            if config:
                paths.append(".nock/config.toml")
            problem = committed(
                self.project,
                [
                    path
                    for path in paths
                    if (self.project.root / path).exists() or self.tracked(path)
                ],
                f"Decisions and review items are now items in topics: {len(refs)} decision(s),"
                f" {items} review item(s), {len(self.made)} topic(s)",
            )
        counts = {name: len(topic["items"]) for name, topic in sorted(self.made.items())}
        return {
            "migrated": True,
            "decisions": len(refs),
            "review_items": items,
            "topics": dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))),
            **({"map": moved_map} if moved_map else {}),
            **({"not_committed": problem} if problem else {}),
        }

    def tracked(self, path: str) -> bool:
        return bool(self.project.git("ls-files", "--", path))

    def slot(self, topic: str, wanted: str) -> str:
        taken = self.slugs.setdefault(topic, set())
        slug, number = wanted, 2
        while slug in taken or slug.isdigit():
            slug, number = f"{wanted[:58]}-{number}", number + 1
        taken.add(slug)
        if topic not in self.made:
            self.made[topic] = {"items": [], "first": None}
        return slug

    def write_item(self, topic: str, item: dict[str, Any]) -> None:
        folder = self.topics.directory / topic / item["slug"]
        write_json(folder / ITEM_FILE, item)
        self.made[topic]["items"].append(item["slug"])
        made = self.made[topic]
        made["first"] = min(filter(None, [made["first"], moment_of(item["created"])]), default=None)
        made["last"] = max(filter(None, [made.get("last"), item["updated"]]), default=None)

    # --- decisions --------------------------------------------------------------

    def migrate_decisions(self) -> dict[int, str]:
        """Each decision as an item; the refs by number."""
        decisions = [read_json(path) for path in sorted(self.decisions.glob("[0-9]*.json"))]
        refs: dict[int, str] = {}
        placed = []
        for decision in decisions:
            topic = topic_of(decision.get("tags") or [])
            slug = self.slot(topic, slugged(decision["title"]))
            refs[decision["number"]] = f"{topic}/{slug}"
            placed.append((decision, topic, slug))
        for decision, topic, slug in placed:
            recorded = decision.get("recorded") or {}
            reviewed = decision.get("reviewed")
            verdict = VERDICTS.get(decision.get("review", "unreviewed"), Verdict.OPEN)
            thread = []
            if decision.get("note"):
                thread.append(
                    {
                        "author": str(Author.OWNER),
                        "moment": moment_of(reviewed) or decision.get("updated") or now(),
                        "text": decision["note"],
                    }
                )
            if decision.get("superseded_by") in refs:
                thread.append(
                    {
                        "author": str(Author.AGENT),
                        "moment": decision.get("updated") or now(),
                        "text": f"Superseded by [{refs[decision['superseded_by']]}].",
                    }
                )
            body = [decision.get("summary") or decision["title"]]
            evidence = decision.get("evidence") or []
            if evidence:
                body.append("Evidence:\n\n" + "\n".join(f"- {line}" for line in evidence))
            touches = decision.get("touches") or []
            if touches:
                body.append("Applies to " + ", ".join(f"`{path}`" for path in touches) + ".")
            overturned = [
                refs[number] for number in decision.get("supersedes") or [] if number in refs
            ]
            if overturned:
                body.append("Supersedes " + ", ".join(f"[{ref}]" for ref in overturned) + ".")
            status = "todo" if decision.get("status") == "todo" else "done"
            content = checked_decision(
                {
                    "answer": "\n\n".join(body),
                    "alternatives": decision.get("alternatives") or [],
                    "status": status,
                }
            )
            folder = self.topics.directory / topic / slug / "1"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / DECISION_FILE).write_bytes(content)
            created = {
                "moment": recorded.get("moment") or decision.get("updated") or now(),
                "session": recorded.get("session"),
                "role": recorded.get("role") or "interactive",
            }
            item = {
                "slug": slug,
                "title": decision["title"],
                "aliases": [str(decision["number"])],
                "verdict": str(verdict),
                "decided": (
                    {"moment": moment_of(reviewed), "session": reviewed.get("session")}
                    if reviewed and verdict is not Verdict.OPEN
                    else None
                ),
                "created": created,
                "updated": decision.get("updated") or created["moment"],
                "thread": thread,
                "versions": [
                    {
                        "version": 1,
                        **created,
                        "files": [{"kind": "decision", "name": DECISION_FILE}],
                    }
                ],
            }
            self.write_item(topic, item)
        return refs

    # --- review items -----------------------------------------------------------

    def migrate_review(self, refs: dict[int, str]) -> int:
        if not self.review.is_dir():
            return 0
        keys = sorted(
            {
                str(path.parent.parent.relative_to(self.review))
                for path in self.review.rglob("version.json")
                if path.parent.name.isdigit()
            }
        )
        large = self.project.local / "review"
        for key in keys:
            place = self.review / key
            versions = sorted(
                (
                    read_json(child / "version.json")
                    for child in place.iterdir()
                    if child.name.isdigit() and (child / "version.json").is_file()
                ),
                key=lambda version: version["version"],
            )
            latest = versions[-1]
            topic = topic_of(latest.get("tags") or [])
            slug = self.slot(topic, re.sub(r"[^a-z0-9-]+", "-", key.lower()).strip("-")[:64])
            thread: list[dict[str, Any]] = []
            made = []
            for version in versions:
                recorded = version.get("recorded") or {}
                when = recorded.get("moment") or now()
                files = []
                for entry in version["files"]:
                    source = (
                        (large if entry.get("local") else self.review)
                        / key
                        / str(version["version"])
                        / entry["name"]
                    )
                    if not source.is_file():
                        continue
                    data = source.read_bytes()
                    local = len(data) > LARGE
                    target = (
                        (self.topics.large if local else self.topics.directory)
                        / topic
                        / slug
                        / str(version["version"])
                        / entry["name"]
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    files.append(
                        {
                            "kind": "derived",
                            "name": entry["name"],
                            "type": kind_of(entry["name"], data),
                            "from": [],
                            "when": None,
                            "recipe": version.get("recipe"),
                            "bytes": len(data),
                            "local": local,
                        }
                    )
                (self.topics.directory / topic / slug / str(version["version"])).mkdir(
                    parents=True, exist_ok=True
                )
                made.append(
                    {
                        "version": version["version"],
                        "moment": when,
                        "session": recorded.get("session"),
                        "role": recorded.get("role") or "interactive",
                        "files": files,
                    }
                )
                if version.get("note"):
                    thread.append(
                        {
                            "author": str(Author.AGENT),
                            "moment": when,
                            "text": f"Version {version['version']}: {version['note']}",
                        }
                    )
                if version.get("decision") in refs:
                    thread.append(
                        {
                            "author": str(Author.AGENT),
                            "moment": when,
                            "text": f"Version {version['version']} illustrates [{refs[version['decision']]}].",
                        }
                    )
                if version.get("feedback"):
                    thread.append(
                        {
                            "author": str(Author.OWNER),
                            "moment": moment_of(version.get("reviewed")) or when,
                            "text": f"On version {version['version']}: {version['feedback']}",
                        }
                    )
            verdict = VERDICTS.get(latest.get("verdict", "unreviewed"), Verdict.OPEN)
            reviewed = latest.get("reviewed")
            first = versions[0].get("recorded") or {}
            created = {
                "moment": first.get("moment") or now(),
                "session": first.get("session"),
                "role": first.get("role") or "interactive",
            }
            item = {
                "slug": slug,
                "title": latest["title"],
                "aliases": [],
                "verdict": str(verdict),
                "decided": (
                    {"moment": moment_of(reviewed), "session": reviewed.get("session")}
                    if reviewed and verdict is not Verdict.OPEN
                    else None
                ),
                "created": created,
                "updated": max(entry["moment"] for entry in made),
                "thread": sorted(thread, key=lambda entry: entry["moment"]),
                "versions": made,
            }
            self.write_item(topic, item)
        shutil.rmtree(large, ignore_errors=True)
        return len(keys)

    # --- the rest ---------------------------------------------------------------

    def write_topics(self) -> None:
        for name, made in self.made.items():
            path = self.topics.directory / name / TOPIC_FILE
            if path.is_file():
                continue
            moment = made["first"] or now()
            write_json(
                path,
                {
                    "name": name,
                    "description": DESCRIPTIONS.get(
                        name,
                        f"The decisions and review items tagged `{name}`, from before topics.",
                    ),
                    "created": {"moment": moment, "session": None, "role": "migration"},
                    "thread": [],
                    "updated": made.get("last") or moment,
                },
            )
        for path in sorted(self.decisions.glob("[0-9]*.json")):
            path.unlink()
        shutil.rmtree(self.review, ignore_errors=True)

    def move_map(self) -> str | None:
        """The map of decisions, now beside the topics; its `[D7]` citations
        still resolve, the numbers kept as the items' aliases."""
        old = self.decisions / MAP
        if not old.is_file():
            return None
        target = self.topics.map
        # The stub an install writes, citing nothing, gives way to the map that was.
        if not target.is_file() or not CITATION.search(target.read_text()):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(old, target)
        else:
            old.unlink()
        if self.decisions.is_dir() and not any(self.decisions.iterdir()):
            self.decisions.rmdir()
        return str(target.relative_to(self.project.root))

    def drop_tags(self) -> bool:
        """The `[decisions]` section (the fixed tags) out of the committed
        settings, with the comment over it; whether it was there."""
        path = self.nock / "config.toml"
        if not path.is_file():
            return False
        lines = path.read_text().splitlines(keepends=True)
        start = next(
            (index for index, line in enumerate(lines) if line.strip() == "[decisions]"), None
        )
        if start is None:
            return False
        end = start + 1
        while end < len(lines) and not lines[end].lstrip().startswith("[") and lines[end].strip():
            end += 1
        while end < len(lines) and not lines[end].strip():
            end += 1
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        path.write_text("".join(lines[:start] + lines[end:]))
        return True


def moment_of(record: dict[str, Any] | None) -> str:
    return (record or {}).get("moment") or ""


def migrate_in(root: Path) -> dict[str, Any] | None:
    """Migrate the project at `root`, when it holds decisions or review items."""
    project = Project.discover(root)
    migration = Migration(project)
    return migration.run() if migration.pending() else None
