"""The move from decisions and review items to topics and items: each
decision becomes a decision item, each review item a derived-file item with
its versions and recipe, each old tag a topic (an item with several goes to
its first; one with none to `general`), notes and the owner's feedback thread
messages, verdicts kept. Then the move to one asset per item: an item
holding several files becomes one item per file, each with the versions
that hold it, the thread copied and the verdict kept. Then the move of
progress to the topic: each topic given its state (done when every item is
decided, active otherwise), and any task item, dispatched work kept as an
item, turned into a note in its topic's thread. Each done once per project,
by `nock init` (so `nock upgrade` does it too) or `nock topics migrate`; each
committed in one commit."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
from datetime import UTC
from pathlib import Path
from typing import Any

from nock.errors import NotFoundError
from nock.fold import ASSETS as ASSETS_DIR
from nock.legacy import (
    CITATION,
    DECISION_FILE,
    GENERAL,
    ITEM_FILE,
    LARGE,
    MAP,
    NAME,
    SPLIT,
    STATUS,
    TOPIC_FILE,
    Author,
    LegacyTopics,
    Verdict,
    checked_decision,
    committed,
    companions,
    entry_name,
    has_variants,
    kind_of,
    slugged,
    state_of,
    stored,
)
from nock.legacy import (
    owner_word as legacy_word,
)
from nock.project import Project
from nock.records import ASSETS_FILE
from nock.shared import Shared, is_media
from nock.topics import Topics, owner_word
from nock.utils import now, parse_moment, read_json, write_json

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
        self.topics = LegacyTopics(project)
        self.nock = project.root / ".nock"
        self.decisions = self.nock / "decisions"
        self.review = self.nock / "review"

    def pending(self) -> bool:
        return any(self.decisions.glob("[0-9]*.json")) or (
            self.review.is_dir() and any(self.review.rglob("version.json"))
        )

    def run(self, mark_seen: bool = False) -> dict[str, Any]:
        """Migrate, and commit; what it made, by topic. The owner's notes and
        verdicts it carries over were acted on long ago, so they count as
        told already. A project that migrated before that, `mark_seen`, has
        every word the owner has said so far marked told instead."""
        split = Splitting(self.project)
        stating = Stating(self.project)
        if not self.pending():
            done: dict[str, Any] = {"migrated": False}
            if mark_seen:
                done["marked_told"] = Topics(self.project).mark_told()
            if split.pending():
                done["split"] = split.run()
            if stating.pending():
                done["stated"] = stating.run()
            storing = Storing(self.project)
            if storing.pending():
                done["stored"] = storing.run()
            return done
        with self.project.lock("topics"):
            self.made: dict[str, dict[str, Any]] = {}
            self.slugs: dict[str, set[str]] = {}
            refs = self.migrate_decisions()
            items = self.migrate_review(refs)
            self.write_topics()
            marked = self.topics.mark_told(
                {f"{topic}/{slug}" for topic, made in self.made.items() for slug in made["items"]}
            )
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
        divided = split.run() if split.pending() else None
        stated = stating.run() if stating.pending() else None
        storing = Storing(self.project)
        stored_counts = storing.run() if storing.pending() else None
        return {
            "migrated": True,
            "decisions": len(refs),
            "review_items": items,
            "topics": dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))),
            "marked_told": marked,
            **({"map": moved_map} if moved_map else {}),
            **({"not_committed": problem} if problem else {}),
            **({"split": divided} if divided else {}),
            **({"stated": stated} if stated else {}),
            **({"stored": stored_counts} if stored_counts else {}),
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


class Splitting:
    """One asset per item: an item holding several files (not as options)
        becomes one item per file. The item keeps its first file (a decision, its
        decision and the project files it concerns) under its ref; each other
        file goes to `SLUG-FILE`, with the versions that hold it, numbered as
    they were, so the thread's "version 3" still means the same. Each
        keeps the verdict and a copy of the thread, opened by a note that says
        so, dated before the rest so it changes nothing about who spoke last."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.topics = LegacyTopics(project)

    def crowded(self) -> list[dict[str, Any]]:
        return [item for item in self.topics.every() if len(self.pieces(item)) > 1]

    def pending(self) -> bool:
        return bool(self.crowded())

    def pieces(self, item: dict[str, Any]) -> list[str]:
        """What it splits into, by file name: the item itself first (`""`
        for a decision), then each file of its own."""
        if item.get("task") or item.get("options") or item.get("variants"):
            return [""]
        decided = any(
            entry["kind"] == "decision"
            for version in item["versions"]
            for entry in version["files"]
        )
        names: list[str] = []
        for version in reversed(item["versions"]):
            for entry in version["files"]:
                if entry["kind"] == "decision" or (decided and entry["kind"] == "project"):
                    continue
                if entry_name(entry) not in names:
                    names.append(entry_name(entry))
        return ["", *names] if decided else names or [""]

    def run(self) -> dict[str, Any]:
        with self.project.lock("topics"):
            crowded = self.crowded()
            made: list[str] = []
            for item in crowded:
                made += self.split(item)
            self.topics.mark_told(set(made))
            problem = committed(
                self.project,
                [".nock/topics"],
                f"One asset per item: {len(crowded)} item(s) holding several files split into"
                f" {len(crowded) + len(made)}",
            )
        return {
            "items": len(crowded),
            "into": len(crowded) + len(made),
            **({"not_committed": problem} if problem else {}),
        }

    def split(self, item: dict[str, Any]) -> list[str]:
        """Split one item; the refs of the items it made."""
        topic, slug = item["topic"], item["slug"]
        pieces = self.pieces(item)
        taken = {other["slug"] for other in self.topics.items(topic)}
        slugs = [slug]
        for name in pieces[1:]:
            wanted = f"{slug[:30]}-{slugged(Path(name).stem)}"[:60].strip("-")
            candidate, number = wanted, 2
            while candidate in taken or candidate.isdigit():
                candidate, number = f"{wanted}-{number}", number + 1
            taken.add(candidate)
            slugs.append(candidate)
        refs = [f"{topic}/{piece}" for piece in slugs]
        aside = f".{slug}.splitting"
        bases = [self.topics.directory, self.topics.large]
        for base in bases:
            if (base / topic / slug).is_dir():
                (base / topic / slug).rename(base / topic / aside)
        note = (
            f"Split out of [{refs[0]}], which held {len(pieces)} files: each is an item of its own"
            f" now — {', '.join(f'[{ref}]' for ref in refs)}. The thread before this is copied"
            " to each."
        )
        for index, (name, piece) in enumerate(zip(pieces, slugs, strict=True)):
            versions = []
            for version in item["versions"]:
                if name:
                    kept = [entry for entry in version["files"] if entry_name(entry) == name]
                else:
                    kept = [
                        entry for entry in version["files"] if entry_name(entry) not in pieces[1:]
                    ]
                if not kept:
                    continue
                number = version["version"]
                for entry in kept:
                    base = self.topics.large if entry.get("local") else self.topics.directory
                    source = base / topic / aside / str(version["version"]) / stored(entry)
                    target = base / topic / piece / str(number) / stored(entry)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                (self.topics.directory / topic / piece / str(number)).mkdir(
                    parents=True, exist_ok=True
                )
                versions.append({**version, "version": number, "files": kept})
            title = item["title"] if not index else f"{item['title']} — {Path(name).name}"
            first = moment_of(item["created"]) or item["updated"]
            thread = [
                {
                    "author": str(Author.AGENT),
                    "moment": first,
                    "text": note,
                    "kind": SPLIT,
                    "split": now(),
                },
                *item["thread"],
            ]
            record = {
                key: value
                for key, value in item.items()
                if key not in ("topic", "ref", "slug", "title", "versions", "thread", "aliases")
            }
            write_json(
                self.topics.directory / topic / piece / ITEM_FILE,
                {
                    "slug": piece,
                    "title": title,
                    "aliases": item.get("aliases", []) if not index else [],
                    **record,
                    "thread": thread,
                    "versions": versions,
                },
            )
        for base in bases:
            shutil.rmtree(base / topic / aside, ignore_errors=True)
        return refs[1:]


class Stating:
    """Progress is the topic's: each topic without a state gets one — done
    when it has items and every one is decided, active otherwise — and each
    task item (dispatched work, kept as an item before topics had a state)
    becomes a note in its topic's thread: its brief, branch, worktree, state
    and thread, the item removed."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.topics = LegacyTopics(project)

    def pending(self) -> bool:
        return any(
            not self.topics.topic(name).get("state")
            or any(item.get("task") for item in self.topics.items(name))
            for name in self.topics.names()
        )

    def run(self) -> dict[str, Any]:
        with self.project.lock("topics"):
            states: dict[str, int] = {}
            tasks = 0
            for name in self.topics.names():
                topic = self.topics.topic(name)
                items = self.topics.items(name)
                for item in [item for item in items if item.get("task")]:
                    note = self.note(item)
                    # In its place in time, so it changes nothing about who spoke last.
                    at = next(
                        (
                            index
                            for index, entry in enumerate(topic["thread"])
                            if entry["moment"] > note["moment"]
                        ),
                        len(topic["thread"]),
                    )
                    topic["thread"].insert(at, note)
                    shutil.rmtree(self.topics.directory / name / item["slug"])
                    shutil.rmtree(self.topics.large / name / item["slug"], ignore_errors=True)
                    items.remove(item)
                    tasks += 1
                if not topic.get("state"):
                    topic["state"] = str(state_of(topic, items))
                    topic.setdefault("status", "")
                    states[topic["state"]] = states.get(topic["state"], 0) + 1
                write_json(self.topics.directory / name / TOPIC_FILE, topic)
            problem = committed(
                self.project,
                [".nock/topics"],
                "Progress is the topic's: "
                + ", ".join(f"{count} topic(s) {state}" for state, count in sorted(states.items()))
                + (f"; {tasks} task item(s) now notes in their topics' threads" if tasks else ""),
            )
        return {
            "topics": dict(sorted(states.items())),
            **({"tasks": tasks} if tasks else {}),
            **({"not_committed": problem} if problem else {}),
        }

    def note(self, item: dict[str, Any]) -> dict[str, Any]:
        task = item["task"]
        where = ", ".join(f"{key} `{task[key]}`" for key in ("branch", "worktree") if task.get(key))
        lines = [
            f"Task [{item['ref']}] {item['title']}, {task.get('state') or 'queued'}"
            + (f" ({where})" if where else "")
            + ", kept as an item before topics had a state:",
            "",
            task.get("brief") or "",
            *(
                f"\n> {entry['author']}, {entry['moment']}: {entry['text']}"
                for entry in item["thread"]
            ),
        ]
        created = item.get("created") or {}
        return {
            "author": str(Author.AGENT),
            "moment": moment_of(created) or item["updated"],
            "text": "\n".join(lines).strip(),
            **{key: created[key] for key in ("session", "parent", "role") if created.get(key)},
            "kind": "task",
        }


def migrate_in(root: Path) -> dict[str, Any] | None:
    """Migrate the project at `root`, when it holds decisions or review
    items, items holding several files, or topics without a state."""
    project = Project.discover(root)
    migration = Migration(project)
    if (
        migration.pending()
        or Splitting(project).pending()
        or Stating(project).pending()
        or Storing(project).pending()
    ):
        return migration.run()
    return None


class Storing:
    """The move to the store: `.nock/topics/` (and its large files under
    `.nock/local/topics/`) becomes `.nock/shared/`, one immutable file per
    event, in one commit. Each topic's history becomes its events — created,
    each status entry a `state`, each message a `message` — and each item's
    its `created`, a `version` per version (its folder `versions/N/`: the
    decision, `assets.json`, small text beside it, everything else in
    `media/` by sha256; a project file copied then becomes a link to the
    commit that made the version when its content matches, else it is kept
    by content), its messages, its verdict and its preferred variant. Every
    event keeps its moment and who wrote it; the map moves too."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.topics = LegacyTopics(project)
        self.store = Shared(project)
        self.old = project.root / ".nock" / "topics"

    def pending(self) -> bool:
        return self.old.is_dir() and any(self.old.glob(f"*/{TOPIC_FILE}"))

    def run(self) -> dict[str, Any]:
        counts = {"topics": 0, "items": 0, "events": 0, "links": 0, "media": 0}
        with self.project.lock("topics"):
            self.user = self.project.git("config", "user.email", check=False) or None
            told = self.told()
            self.ties()
            for name in self.topics.names():
                self.topic(name, counts)
            if self.topics.map.is_file():
                self.store.map.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(self.topics.map, self.store.map)
            shutil.rmtree(self.old, ignore_errors=True)
            shutil.rmtree(self.topics.large, ignore_errors=True)
            paths = [".nock/shared"]
            if self.tracked(".nock/topics"):
                paths.append(".nock/topics")
            problem = committed(
                self.project,
                paths,
                f"Topics are in the store, .nock/shared/: {counts['topics']} topic(s),"
                f" {counts['items']} item(s), {counts['events']} event(s)",
            )
            self.tell_again(told)
        return {**counts, **({"not_committed": problem} if problem else {})}

    def told(self) -> list[tuple[str, str]]:
        """Which sessions have been told the owner's latest word on which items."""
        words = {item["ref"]: legacy_word(item) for item in self.topics.every()}
        return [
            (row["session"], row["item"])
            for row in self.project.store.rows("SELECT session, item, updated FROM told")
            if words.get(row["item"]) and row["updated"] == words[row["item"]]
        ]

    def tell_again(self, told: list[tuple[str, str]]) -> None:
        """What a session was told still counts as told: the owner's word as the
        store now reads it."""
        topics = Topics(self.project)
        for session, ref in told:
            try:
                word = owner_word(topics.item(ref))
            except NotFoundError:
                continue
            if word:
                self.project.store.insert(
                    "told", {"session": session, "item": ref, "updated": word}
                )

    def tracked(self, path: str) -> bool:
        return bool(self.project.git("ls-files", "--", path))

    def by(self, stamp: dict[str, Any] | None, author: str | None = None) -> dict[str, Any]:
        stamp = stamp or {}
        who = author or stamp.get("author") or "agent"
        role = stamp.get("role")
        interactive = who == "owner" or (role in (None, "interactive") and not stamp.get("parent"))
        return {
            key: value
            for key, value in {
                "author": who,
                "on_behalf": "interactive" if interactive else "agent",
                "user": self.user,
                "session": stamp.get("session"),
                "parent": stamp.get("parent"),
                "role": role,
            }.items()
            if value is not None
        }

    def write(
        self,
        folder: Path,
        events: list[tuple[str, dict[str, Any]]],
        counts: dict[str, int],
    ) -> dict[str, str]:
        """Write events, each `(moment, record with its by)`, in order: their
        files named by their moment, a millisecond apart within one second so
        they sort as they were said. The ids given, by moment."""
        ids: dict[str, str] = {}
        last = ""
        milliseconds = 0
        for moment, record in events:
            base = moment_stamp(moment)
            milliseconds = milliseconds + 1 if base == last else 0
            last = base
            identifier = secrets.token_hex(4)
            complete = {
                "kind": record.pop("kind"),
                "moment": moment,
                "id": identifier,
                "by": record.pop("by"),
                **record,
            }
            write_json(
                folder / "events" / f"{base}.{milliseconds:03d}Z-{identifier}.json", complete
            )
            if complete["kind"] == "message":
                ids.setdefault(moment, identifier)
            counts["events"] += 1
        return ids

    def topic(self, name: str, counts: dict[str, int]) -> None:
        topic = self.topics.topic(name)
        folder = self.store.topic_folder(name)
        created = topic.get("created") or {}
        first = created.get("moment") or topic.get("updated") or now()
        statuses = [entry for entry in topic["thread"] if entry.get("kind") == STATUS]
        events: list[tuple[str, dict[str, Any]]] = [
            (
                first,
                {
                    "kind": "created",
                    "by": self.by(created),
                    "description": topic["description"],
                    "state": "active" if statuses else str(state_of(topic)),
                },
            )
        ]
        events += self.thread(topic["thread"], name, None, statuses=True)
        last_state = {"state": "active", "status": ""}
        for entry in statuses:
            if entry.get("state"):
                last_state["status"] = (
                    "" if entry["state"] != last_state["state"] else last_state["status"]
                )
                last_state["state"] = entry["state"]
            if "status" in entry:
                last_state["status"] = entry.get("status") or ""
        now_state = {"state": str(state_of(topic)), "status": topic.get("status") or ""}
        final: dict[str, Any] = {}
        if statuses and now_state != last_state:
            final |= now_state
        if topic.get("priority"):
            final["priority"] = topic["priority"]
        if final:
            events.append(
                (topic.get("updated") or first, {"kind": "state", "by": self.by(created), **final})
            )
        events.sort(key=lambda pair: pair[0])
        ids = self.write(folder, events, counts)
        self.link_answers(folder, ids)
        counts["topics"] += 1
        for item in self.topics.items(name):
            self.item(name, item, counts)

    def thread(
        self,
        thread: list[dict[str, Any]],
        topic: str,
        slug: str | None,
        statuses: bool,
    ) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        for entry in thread:
            if entry.get("kind") == STATUS:
                if statuses:
                    record: dict[str, Any] = {"kind": "state", "by": self.by(entry, "agent")}
                    for key in ("state", "status"):
                        if key in entry:
                            record[key] = entry.get(key) or ""
                    if entry.get("revived"):
                        record["revived"] = True
                        record["note"] = entry.get("text") or ""
                    events.append((entry["moment"], record))
                continue
            text = entry.get("text") or ""
            record = {"kind": "message", "by": self.by(entry, entry.get("author")), "text": text}
            if entry.get("kind") in ("task", "split", "revival"):
                record["note"] = entry["kind"]
            if entry.get("kind") == "revival" and statuses:
                record = {
                    "kind": "state",
                    "by": self.by(entry, "agent"),
                    "state": "active",
                    "revived": True,
                    "note": text,
                }
            if entry.get("verdict") and record["kind"] == "message":
                record["verdict"] = entry["verdict"]
            files = []
            for file in entry.get("attachments", []):
                path = self.topics.where(file, topic, slug)
                if path.is_file():
                    files.append(
                        {
                            "name": file["name"],
                            "type": file.get("type") or kind_of(file["name"], b""),
                            "bytes": path.stat().st_size,
                            "sha256": self.store.keep(path.read_bytes()),
                        }
                    )
            if files:
                record["attachments"] = files
            if not text and not files and record["kind"] == "message":
                record["text"] = "(no text)"
            if entry.get("answers"):
                record["answers_moment"] = entry["answers"]
            events.append((entry["moment"], record))
        return events

    def item(self, topic: str, item: dict[str, Any], counts: dict[str, int]) -> None:
        """A decision item as a decision, its project files its assets, and the
        asset items its thread or theirs ties to it as assets of it too; an
        asset item tied to none as an asset of a "Review" decision wrapping it."""
        if item["ref"] in self.attached:
            return
        decided_kind = any(
            entry["kind"] == "decision"
            for version in item["versions"]
            for entry in version["files"]
        )
        folder = self.store.item_folder(topic, item["slug"])
        created = item.get("created") or {}
        first = created.get("moment") or item.get("updated") or now()
        title = item["title"] if decided_kind else f"Review: {item['title']}"
        # The asset items it now holds keep their refs, as its aliases.
        aliases = [
            *item.get("aliases", []),
            *(other["ref"] for other in self.tied.get(item["ref"], [])),
        ]
        events: list[tuple[str, dict[str, Any]]] = [
            (
                first,
                {
                    "kind": "created",
                    "by": self.by(created),
                    "title": title,
                    **({"description": item["description"]} if item.get("description") else {}),
                    **({"aliases": aliases} if aliases else {}),
                },
            )
        ]
        number = 0
        for version in item["versions"]:
            decision = self.topics.folder(topic, item["slug"], version["version"]) / DECISION_FILE
            if decided_kind and not decision.is_file():
                continue
            number += 1
            target = folder / "versions" / str(number)
            target.mkdir(parents=True, exist_ok=True)
            if decided_kind:
                shutil.copy2(decision, target / DECISION_FILE)
            else:
                answer = item.get("description") or f"Review {item['title']}."
                write_json(
                    target / DECISION_FILE,
                    {"answer": answer, "alternatives": [], "status": "done"},
                )
            events.append(
                (
                    version.get("moment") or first,
                    {"kind": "version", "by": self.by(version), "version": number},
                )
            )
            if not decided_kind:
                break
        events += self.thread(item["thread"], topic, item["slug"], statuses=False)
        latest_asset = self.assets(topic, item, folder, counts)
        for other in self.tied.get(item["ref"], []):
            events += self.thread(other["thread"], other["topic"], other["slug"], statuses=False)
            latest_asset = max(latest_asset, self.assets(other["topic"], other, folder, counts))
        decided = item.get("decided")
        if item["verdict"] != "open" and decided:
            moment = decided.get("moment") or item.get("updated") or first
            events.append(
                (
                    moment,
                    {
                        "kind": "verdict",
                        "by": self.by(decided, "owner"),
                        "verdict": item["verdict"],
                    },
                )
            )
            accepted_too = all(
                other["verdict"] == item["verdict"] for other in self.tied.get(item["ref"], [])
            )
            for other in self.tied.get(item["ref"], []):
                # A screenshot the owner rejected asks for rework of what it shows.
                said = other.get("decided") or {}
                if other["verdict"] == "rejected" and said.get("moment"):
                    events.append(
                        (
                            said["moment"],
                            {
                                "kind": "verdict",
                                "by": self.by(said, "owner"),
                                "verdict": "rejected",
                            },
                        )
                    )
            if latest_asset > moment and accepted_too:
                # Its assets were judged as items of their own, the same way: the verdict
                # still holds after them, rather than the move reopening what was decided.
                events.append(
                    (
                        latest_asset,
                        {
                            "kind": "verdict",
                            "by": self.by(decided, "owner"),
                            "verdict": item["verdict"],
                        },
                    )
                )
        order = {"created": 0}
        events.sort(key=lambda pair: (pair[0], order.get(pair[1]["kind"], 1)))
        ids = self.write(folder, events, counts)
        self.link_answers(folder, ids)
        counts["items"] += 1

    def assets(self, topic: str, item: dict[str, Any], folder: Path, counts: dict[str, int]) -> str:
        """An item's files, by version, as assets of the decision in `folder`:
        each project file an asset, its derived files one (with its variants
        and views); a version only where a file changed. The latest moment."""
        made: dict[str, dict[str, Any]] = {}
        latest = ""
        for version in item["versions"]:
            number = version["version"]
            old = self.topics.folder(topic, item["slug"], number)
            commit = self.made_by(old)
            derived = [entry for entry in version["files"] if entry["kind"] == "derived"]
            groups: list[tuple[str, str, list[dict[str, Any]]]] = [
                (slugged(entry["path"]), entry["path"], [entry])
                for entry in version["files"]
                if entry["kind"] == "project"
            ]
            if derived:
                groups.append(
                    (
                        item["slug"],
                        item["title"],
                        derived,
                    )
                )
            for name, title, entries in groups:
                record = self.asset_record(
                    topic, item, number, old, commit, entries, version, counts
                )
                kept = made.get(name)
                if kept is not None and kept["last"] == record["digest"]:
                    continue
                if kept is None:
                    kept = made[name] = {"versions": 0, "last": None, "title": title, "events": []}
                    kept["events"].append(
                        (
                            version.get("moment") or "",
                            {"kind": "created", "by": self.by(version), "title": title},
                        )
                    )
                kept["versions"] += 1
                kept["last"] = record["digest"]
                target = folder / ASSETS_DIR / name / "versions" / str(kept["versions"])
                target.mkdir(parents=True, exist_ok=True)
                for file_name, data in record["beside"].items():
                    (target / file_name).write_bytes(data)
                write_json(target / ASSETS_FILE, record["assets"])
                moment = version.get("moment") or ""
                kept["events"].append(
                    (
                        moment,
                        {"kind": "version", "by": self.by(version), "version": kept["versions"]},
                    )
                )
                latest = max(latest, moment)
        preferred = item.get("preferred")
        for name, kept in made.items():
            if preferred and name == item["slug"]:
                at = next(
                    (
                        index
                        for index, (_, record) in enumerate(kept["events"])
                        if record["kind"] == "version"
                    ),
                    None,
                )
                if at is not None:
                    decided = item.get("decided") or {}
                    kept["events"].append(
                        (
                            decided.get("moment") or item.get("updated") or "",
                            {
                                "kind": "preferred",
                                "by": self.by(decided, "owner"),
                                "version": kept["versions"],
                                "name": preferred["name"],
                            },
                        )
                    )
            kept["events"].sort(
                key=lambda pair: (pair[0], 0 if pair[1]["kind"] == "created" else 1)
            )
            self.write(folder / ASSETS_DIR / name, kept["events"], counts)
        return latest

    def asset_record(
        self,
        topic: str,
        item: dict[str, Any],
        number: int,
        old: Path,
        commit: str | None,
        entries: list[dict[str, Any]],
        version: dict[str, Any],
        counts: dict[str, int],
    ) -> dict[str, Any]:
        """One asset's version from an old version's files: its `assets.json`,
        the small text kept beside it, and a digest to tell a change."""
        files: list[dict[str, Any]] = []
        blobs: dict[str, str] = {}
        beside: dict[str, bytes] = {}
        for entry in entries:
            source = self.topics.located(topic, item["slug"], number, entry)
            data = source.read_bytes() if source.is_file() else b""
            if entry["kind"] == "project":
                linked: dict[str, Any] = {
                    "kind": "project",
                    "path": entry["path"],
                    "type": entry.get("type") or kind_of(entry["path"], data),
                    "bytes": len(data),
                }
                then = self.at(commit, entry["path"]) if commit else None
                if then is not None and then == data:
                    linked["commit"] = commit
                    counts["links"] += 1
                elif data:
                    linked["sha256"] = self.store.keep(data)
                    counts["media"] += 1
                files.append(linked)
                continue
            kept: dict[str, Any] = {
                key: entry[key]
                for key in ("kind", "name", "type", "from", "when", "recipe", "captions", "poster")
                if key in entry
            }
            kept["bytes"] = len(data)
            if is_media(entry["name"], data):
                kept["sha256"] = self.store.keep(data)
                counts["media"] += 1
            else:
                beside[entry["name"]] = data
            for name in companions(entry).values():
                path = old / name
                if path.is_file():
                    content = path.read_bytes()
                    if is_media(name, content):
                        blobs[name] = self.store.keep(content)
                    else:
                        beside[name] = content
            files.append(kept)
        views = []
        if any(entry["kind"] == "derived" for entry in entries):
            for view in version.get("views", []):
                path = old / view["name"]
                if path.is_file():
                    beside[view["name"]] = path.read_bytes()
                    views.append(
                        {
                            "name": view["name"],
                            "title": view.get("title") or "",
                            "bytes": path.stat().st_size,
                        }
                    )
        assets: dict[str, Any] = {"files": files}
        if len(files) > 1 and has_variants(item):
            assets["variants"] = True
        if views:
            assets["views"] = views
        if blobs:
            assets["blobs"] = blobs
        # What tells one version from the next: the files' content, not the commit
        # a project file was linked at.
        plain = json.loads(json.dumps(assets))
        for entry in plain["files"]:
            entry.pop("commit", None)
        contents = sorted((name, hashlib.sha256(data).hexdigest()) for name, data in beside.items())
        digest = hashlib.sha256(json.dumps([plain, contents], sort_keys=True).encode()).hexdigest()
        return {"assets": assets, "beside": beside, "digest": digest}

    def ties(self) -> None:
        """Which asset items belong to which decision: one a decision's thread
        names ("Screenshots: [ref]"), or whose own thread names the decision it
        illustrates; each asset item to one decision at most."""
        every = {item["ref"]: item for item in self.topics.every()}
        decisions = {
            ref
            for ref, item in every.items()
            if any(e["kind"] == "decision" for v in item["versions"] for e in v["files"])
        }
        self.tied: dict[str, list[dict[str, Any]]] = {}
        self.attached: set[str] = set()

        def tie(asset: str, decision: str) -> None:
            if asset in self.attached or asset in decisions or decision not in decisions:
                return
            if asset == decision or asset not in every:
                return
            self.attached.add(asset)
            self.tied.setdefault(decision, []).append(every[asset])

        for ref in sorted(decisions):
            for entry in every[ref]["thread"]:
                text = entry.get("text") or ""
                if SCREENSHOTS.search(text):
                    for cited in REFERENCE.findall(text):
                        tie(cited, ref)
        for ref, item in sorted(every.items()):
            if ref in decisions:
                continue
            for entry in item["thread"]:
                text = entry.get("text") or ""
                if ILLUSTRATES.search(text):
                    for cited in REFERENCE.findall(text):
                        tie(ref, cited)
                        break

    def link_answers(self, folder: Path, ids: dict[str, str]) -> None:
        """An answer names the message it answers by id, as the store does."""
        for path in sorted((folder / "events").glob("*.json")):
            record = read_json(path)
            moment = record.pop("answers_moment", None)
            if moment is None:
                continue
            if moment in ids:
                record["answers"] = ids[moment]
            write_json(path, record)

    def made_by(self, folder: Path) -> str | None:
        """The commit that made a version's folder in the old layout."""
        relative = folder.relative_to(self.project.root).as_posix()
        found = self.project.git(
            "log", "--diff-filter=A", "--format=%H", "-1", "--", relative, check=False
        )
        return found.strip() or None

    def at(self, commit: str, path: str) -> bytes | None:
        result = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=self.project.root,
            capture_output=True,
        )
        return result.stdout if result.returncode == 0 else None


# A decision's message naming the asset items that show it, and an asset item's naming its decision.
SCREENSHOTS = re.compile(r"^\s*(screenshots?|assets?|shown in|see)\b", re.IGNORECASE)
ILLUSTRATES = re.compile(r"\billustrates\b", re.IGNORECASE)
REFERENCE = re.compile(r"\[?\b([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*)\b\]?")


def moment_stamp(moment: str) -> str:
    """An event file's stamp from a moment, to the second: `20261111T163015`."""
    parsed = parse_moment(moment)
    if parsed is None:
        return "19700101T000000"
    return parsed.astimezone(UTC).strftime("%Y%m%dT%H%M%S")
