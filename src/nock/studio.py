"""The owner's page (`nock studio`): one local server, a tab for each thing
nock keeps for the owner: the topics agents put their work in, each item (a
decision, project files, something made to show part of the project) looked
at, compared, accepted or rejected and talked over in its thread, with a bar
to search them or ask about them. Local, and only while `nock studio` runs.

A tab is a `Tab` in `TABS`: its name is its address on the page (`#NAME`) and
its routes on the server (`/NAME/…`); its page is the fragment
`pages/NAME.html` (markup, style and a script that registers it with the
studio, `pages/studio.html`, whose look is `pages/studio.css`). While nobody has answered whether nock shares
its usage report, the page asks under the title; the settings in the menu
change the answer later; `POST /usage` records either. The page polls
`/notifications` to tell the owner when a topic is their turn (`nock.notify`)."""

from __future__ import annotations

import html
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from nock.chats import Chats, Kind
from nock.commands import schema_of
from nock.configuration import with_table_settings
from nock.errors import ConflictError, Error, NotFoundError, UsageError
from nock.notify import ICON, Notifications, Watching
from nock.project import Project
from nock.schema import validate
from nock.timeline import Event, Timeline
from nock.topics import (
    ATTACHMENTS,
    Author,
    Topics,
    Verdict,
    attachment_name,
    chat_state,
    entry_name,
    in_order,
    kind_of,
    latest_files,
    occurrences,
    state_of,
)
from nock.topics import Word as Verdicted
from nock.transcription import HINT, Transcription
from nock.usage import QUESTION, Answer, Usage, sharing
from nock.utils import now, read_json, write_json

PACKAGE = Path(__file__).resolve().parent
# Set across a restart, so the browser is not opened a second time.
RESTARTED = "NOCK_STUDIO_RESTARTED"
# What each kind of chat is doing while its answer is being written.
WORK = {
    Kind.CHAT: "a chat is answering",
    Kind.TIDY: "Tidy up is running",
    Kind.ADDRESS: "Address my comments is running",
}
PAGES = PACKAGE / "pages"
SHELL = PAGES / "studio.html"
LOOK = PAGES / "studio.css"
# Views' look: what nock's own pages use, for a view laying out an asset's variants.
VIEW_LOOK = PAGES / "view.css"


def code_moment() -> int:
    """When nock's code last changed on disk. The pages are read at each
    request but the code only at start, so a studio left running across an
    update serves new pages to old routes: the page offers to restart it."""
    return max(path.stat().st_mtime_ns for path in PACKAGE.glob("*.py"))


class Tab:
    """One tab: what it answers on `GET /NAME/ROUTE` and `POST /NAME/ROUTE`
    (JSON both ways; a nock `Error` is the HTTP error)."""

    name = ""
    title = ""
    # The routes whose POST body is a file as it is (an `Upload`), not JSON.
    raw: tuple[str, ...] = ()

    def __init__(self, project: Project) -> None:
        self.project = project

    def fragment(self) -> str:
        return (PAGES / f"{self.name}.html").read_text()

    def get(self, route: str) -> Any:
        raise NotFoundError("no such page")

    def post(self, route: str, body: Any) -> Any:
        raise NotFoundError("no such page")


# How much of a text file Search reads: enough for any document, not a log.
SEARCHED_BYTES = 256 * 1024


def spoken(vtt: str) -> str:
    """A WebVTT file's words, as its captions show them: no header, cue
    numbers or timings."""
    return " ".join(
        line
        for line in vtt.splitlines()
        if line.strip()
        and "-->" not in line
        and not line.startswith("WEBVTT")
        and not line.strip().isdigit()
    )


def talk_of(thread: list[dict[str, Any]]) -> list[str]:
    """A thread's messages as the owner reads them, without nock's own notes:
    each one's text and the names of the files it carries."""
    return [
        " ".join([entry["text"], *(file["name"] for file in entry.get("attachments", []))])
        for entry in thread
        if not entry.get("kind")
    ]


@dataclass(frozen=True)
class Raw:
    """A file a tab answers with as it is, not as JSON."""

    path: Path


@dataclass(frozen=True)
class Html:
    """A page a tab answers with, made for the request."""

    text: str


class Judged(TypedDict):
    """The owner's verdict on the page: on an item (`ref`), or on every open item of a topic."""

    ref: NotRequired[str]
    topic: NotRequired[str]
    verdict: Verdict


class Replied(TypedDict):
    """The owner's message in an item's thread (`ref`) or a topic's, with the
    files uploaded for it (their tokens)."""

    ref: NotRequired[str]
    topic: NotRequired[str]
    text: str
    attachments: NotRequired[list[str]]


class Token(TypedDict):
    token: str


@dataclass(frozen=True)
class Upload:
    """A request's body as it is, not JSON: a file the owner dropped into a
    chat, or a recording; its name from `?name=`."""

    name: str
    kind: str
    length: int
    stream: io.BufferedIOBase


class Uploads:
    """The files dropped into a chat's composer, kept on this machine
    (`.nock/local/studio/uploads/TOKEN/NAME`) until the message they go with
    is sent, which moves them beside its thread; a withdrawn message's come
    back here, to send again. What was never sent is forgotten when the
    studio starts again."""

    def __init__(self, project: Project) -> None:
        self.directory = project.local / "studio" / "uploads"
        shutil.rmtree(self.directory, ignore_errors=True)

    def record(self, path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            head = handle.read(65536)
        return {
            "token": path.parent.name,
            "name": path.name,
            "type": kind_of(path.name, head),
            "bytes": path.stat().st_size,
        }

    def stage(self, upload: Upload) -> dict[str, Any]:
        path = self.directory / secrets.token_hex(8) / attachment_name(upload.name)
        path.parent.mkdir(parents=True)
        left = upload.length
        with path.open("wb") as file:
            while left > 0:
                chunk = upload.stream.read(min(left, 1 << 20))
                if not chunk:
                    break
                file.write(chunk)
                left -= len(chunk)
        return self.record(path)

    def adopt(self, path: Path, name: str) -> dict[str, Any]:
        """A file kept elsewhere, copied here under its NAME to be sent again."""
        target = self.directory / secrets.token_hex(8) / attachment_name(name)
        target.parent.mkdir(parents=True)
        shutil.copy2(path, target)
        return self.record(target)

    def path(self, token: str) -> Path:
        folder = self.directory / token
        if not re.fullmatch(r"[0-9a-f]{16}", token) or not folder.is_dir():
            raise NotFoundError(f"no upload {token}: drop the file again")
        files = [entry for entry in folder.iterdir() if entry.is_file()]
        if not files:
            raise NotFoundError(f"no upload {token}: drop the file again")
        return files[0]

    def discard(self, token: str) -> None:
        shutil.rmtree(self.path(token).parent)

    def sent(self, tokens: list[str]) -> None:
        """Remove what is left of these uploads, once their files are kept beside the thread."""
        for token in tokens:
            shutil.rmtree(self.directory / token, ignore_errors=True)


class Where(TypedDict):
    """An item's thread (`ref`) or a topic's."""

    ref: NotRequired[str]
    topic: NotRequired[str]


class Preferred(TypedDict):
    """The owner's preferred variant of a decision's asset, in one of its
    versions; without `name`, none."""

    ref: str
    version: int
    name: NotRequired[str]
    asset: NotRequired[str]


class Question(TypedDict):
    question: str


class Seen:
    """When the owner last looked at each chat, kept on this machine
    (`.nock/local/studio/seen.json`): what the agent said since is new."""

    def __init__(self, project: Project) -> None:
        self.path = project.local / "studio" / "seen.json"
        self.lock = threading.Lock()

    def all(self) -> dict[str, str]:
        return read_json(self.path) if self.path.is_file() else {}

    def look(self, where: str) -> None:
        with self.lock:
            write_json(self.path, {**self.all(), where: now()})


class Asking:
    """The one question being asked at a time: a `nock topics ask` run in its
    own process, so it is cancelled by stopping it."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.question: str | None = None
        self.started: str | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.output = project.local / "answers" / "studio.json"
        self.cancelled = False

    def start(self, question: str) -> dict[str, Any]:
        if not question.strip():
            raise UsageError("the question is empty")
        if self.process is not None and self.process.poll() is None:
            raise UsageError("a question is being answered: wait for it, or cancel it")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with self.output.open("wb") as output:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "nock", "topics", "ask", question.strip(), "--json"],
                cwd=self.project.here,
                env={**os.environ, "PYTHONPATH": str(PACKAGE.parent)},
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.question, self.started, self.cancelled = question.strip(), now(), False
        return self.state() or {}

    def cancel(self) -> dict[str, Any]:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.cancelled = True
        return self.state() or {}

    def state(self) -> dict[str, Any] | None:
        if self.process is None:
            return None
        said = {"question": self.question, "started": self.started}
        if self.cancelled:
            return {**said, "running": False, "problem": "cancelled"}
        if self.process.poll() is None:
            return {**said, "running": True}
        text = self.output.read_text() if self.output.is_file() else ""
        if self.process.returncode == 0:
            try:
                answered = json.loads(text)
            except json.JSONDecodeError:
                answered = {"answer": text.strip(), "items": []}
            return {**said, "running": False, **answered}
        return {
            **said,
            "running": False,
            "problem": text.strip()[-600:] or "the agent gave no answer",
        }


class TopicsTab(Tab):
    """`GET /topics` every topic with its items (each version's decision and
    files), where each chat stands (`chat`: pending, unseen), the question
    being asked and whether the recorder can transcribe; `GET
    /topics/file/TOPIC/SLUG/N/NAME` one of a version's files, as it is,
    `/attachment/TOPIC[/SLUG]/PATH` one a message carries, `/upload/TOKEN`
    one dropped into a composer; `POST /topics/judge` the owner's verdict on
    an item or a whole topic, `/prefer` their preferred option of an item,
    `/upload?name=NAME` a file for the message being written (its body as it
    is), `/upload/discard` takes it out, `/reply` their message in a chat
    with its files, `/withdraw` takes it back while it waits for its answer
    (its files uploaded again), `/seen` records that they looked at a chat,
    `/transcribe` a recording made text (`nock.transcription`), `/ask` a
    question about the topics (one at a time), `/ask/cancel` stops it; `GET
    /topics/ask` where the question stands; `GET /topics/view/TOPIC/SLUG/N/NAME`
    a version's view with nock's look (`view.css`), or a file beside it."""

    name = "topics"
    title = "Topics"
    raw = ("upload", "transcribe")

    def __init__(self, project: Project) -> None:
        super().__init__(project)
        self.topics = Topics(project)
        # The studio's chats, for the threads Address now answers: set by the studio.
        self.chats: Chats | None = None
        self.asking = Asking(project)
        self.seen = Seen(project)
        self.uploads = Uploads(project)
        self.texts: dict[Path, tuple[int, str]] = {}

    def fragment(self) -> str:
        look = (PAGES / "topics.css").read_text() + (PAGES / "chat.css").read_text()
        return f"<style>\n{look}</style>\n" + super().fragment()

    def get(self, route: str) -> Any:
        if not route:
            transcription = Transcription(self.project)
            return {
                "topics": self.everything(),
                "ask": self.asking.state(),
                "transcription": {
                    "enabled": transcription.enabled,
                    **({} if transcription.enabled else {"hint": HINT}),
                },
            }
        parts = urllib.parse.unquote(route).split("/")
        if parts[0] == "upload" and len(parts) == 2:
            return Raw(self.uploads.path(parts[1]))
        if parts[0] == "attachment" and ATTACHMENTS in parts[2:4]:
            slug = None if parts[2] == ATTACHMENTS else parts[2]
            return Raw(self.topics.attachment(parts[1], slug, "/".join(parts[3 if slug else 2 :])))
        if parts[0] == "ask" and len(parts) == 1:
            return {"ask": self.asking.state()}
        if parts[0] == "search":
            return self.search("/".join(parts[1:]))
        if parts[0] == "view.css":
            return Raw(VIEW_LOOK)
        if parts[0] == "view" and len(parts) >= 6 and parts[4].isdigit():
            return self.view(parts[1], parts[2], parts[3], int(parts[4]), "/".join(parts[5:]))
        if parts[0] != "file" or len(parts) < 6 or not parts[4].isdigit():
            raise NotFoundError("no such page")
        return Raw(
            self.topics.file(parts[1], parts[2], parts[3], int(parts[4]), "/".join(parts[5:]))
        )

    def search(self, query: str) -> dict[str, Any]:
        """What the Search field finds, in what the owner sees: a topic by its
        name, description, status and thread; an item by its title, its
        description, its decision, its files' names, the text of its text
        files, its videos' captions, and its thread (a thread's messages with
        the names of the files they carry) — never a recipe, a `from`, a ref
        or nock's own notes (a split, a revival, a task kept as a note).
        Ranked as `topics list --query` ranks (`Topics.score`): what holds
        every word first, more often higher, then what holds all but one, and
        so on down. `topics` are those whose own words hold every word (shown
        whole); `items` every item holding at least one word itself, the
        strongest first, its topic's words counting too; `order` the topics
        by their strongest match."""
        wanted = query.lower().split()
        if not wanted:
            return {"topics": [], "items": [], "order": []}
        topics, items, best = [], [], {}
        for name in self.topics.names():
            record = self.topics.topic(name)
            around = " ".join(
                [
                    record.get("description") or "",
                    self.topics.current_description(record),
                    record.get("status") or "",
                    *talk_of(record["thread"]),
                ]
            ).lower()
            heading = name.replace("-", " ")
            points = self.topics.score(wanted, heading, around)
            if points >= len(wanted) * 1000:
                topics.append(name)
                best[name] = points
            for item in self.topics.items(name):
                own = self.seen_in(item)
                if not any(occurrences(word, own) for word in wanted):
                    continue
                scored = self.topics.score(wanted, item["title"], f"{own} {heading} {around}")
                items.append((scored, f"{name}/{item['slug']}"))
                best[name] = max(best.get(name, 0), scored)
        items.sort(key=lambda pair: -pair[0])
        order = sorted(best, key=lambda name: -best[name])
        return {"topics": topics, "items": [ref for _, ref in items], "order": order}

    def seen_in(self, item: dict[str, Any]) -> str:
        """An item's words as the owner sees them, lowercased; the text files
        of its latest version read once per change."""
        shown = self.topics.shown(item)
        decision = (shown["versions"][-1].get("decision") or {}) if shown["versions"] else {}
        parts = [item["title"], item.get("description") or "", *talk_of(item["thread"])]
        if decision:
            parts.append(decision.get("answer") or "")
            for entry in decision.get("alternatives") or []:
                parts += [entry.get("option") or "", entry.get("why_not") or ""]
        latest = [file for asset in shown["assets"] for file in latest_files(asset)]
        parts += [asset["title"] for asset in shown["assets"]]
        for file in latest:
            parts.append(file["name"])
            if file.get("type") == "text":
                parts.append(self.text_of(Path(file["where"])))
            if file.get("captions_where"):
                parts.append(spoken(self.text_of(Path(file["captions_where"]))))
        return " ".join(parts).lower()

    def text_of(self, path: Path) -> str:
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return ""
        kept = self.texts.get(path)
        if kept is None or kept[0] != stamp:
            data = path.read_bytes()[:SEARCHED_BYTES]
            kept = (stamp, data.decode("utf-8", errors="replace"))
            self.texts[path] = kept
        return kept[1]

    def view(self, topic: str, slug: str, asset: str, version: int, name: str) -> Any:
        """An asset version's view, with nock's look and the asset's files
        named for it (`window.nock.assets`); any other name, the version's
        file beside it, so a view reaches them by relative addresses."""
        item = self.topics.item(f"{topic}/{slug}")
        held = self.topics.asset(item, asset)
        record = next((entry for entry in held["versions"] if entry["version"] == version), None)
        views = (record or {}).get("views", [])
        if not any(entry["name"] == name for entry in views):
            return Raw(self.topics.file(topic, slug, asset, version, name))
        page = self.topics.file(topic, slug, asset, version, name).read_text(errors="replace")
        assets = [
            {
                "name": entry_name(entry),
                "type": entry["type"],
                "title": held["title"],
                "address": urllib.parse.quote(entry_name(entry)),
                "preferred": (held.get("preferred") or {}).get("name") == entry_name(entry),
            }
            for entry in (record or {}).get("files", [])
        ]
        given = json.dumps({"assets": assets, "title": item["title"]}).replace("</", "<\\/")
        head = (
            '<link rel="stylesheet" href="/topics/view.css">'
            f"<script>window.nock = {given};</script>"
        )
        at = page.lower().find("<head>")
        return Html(page[: at + 6] + head + page[at + 6 :] if at >= 0 else head + page)

    def everything(self) -> list[dict[str, Any]]:
        found = []
        seen = self.seen.all()
        addressing = self.chats.addressing() if self.chats is not None else set()
        for name in self.topics.names():
            record = self.topics.topic(name)
            items = self.topics.items(name)
            found.append(
                {
                    **record,
                    "current": self.topics.current_description(record),
                    "state": str(state_of(record, items)),
                    "active": self.topics.activity(record, items),
                    "counts": self.topics.counts(items),
                    "chat": {
                        **chat_state(record["thread"], seen.get(name)),
                        "addressing": name in addressing,
                    },
                    "items": [
                        {
                            **self.topics.shown(item),
                            "chat": {
                                **chat_state(
                                    item["thread"], seen.get(item["ref"]), item.get("decided")
                                ),
                                "addressing": item["ref"] in addressing,
                            },
                        }
                        for item in items
                    ],
                }
            )
        return in_order(found)

    def post(self, route: str, body: Any) -> Any:
        if route == "upload":
            return self.uploads.stage(body)
        if route == "transcribe":
            audio = body.stream.read(body.length)
            return {"text": Transcription(self.project).transcribe(audio, body.kind)}
        if route == "upload/discard":
            validate(body, schema_of(Token))
            self.uploads.discard(body["token"])
            return {"discarded": body["token"]}
        if route == "judge":
            validate(body, schema_of(Judged))
            word = Verdicted(verdict=body["verdict"])
            if "ref" in body:
                return {"judged": [self.topics.judge(body["ref"], word)[0]["ref"]]}
            if "topic" in body:
                return {"judged": self.topics.judge_topic(body["topic"], word)[0]}
            raise UsageError("give `ref` or `topic`")
        if route == "reply":
            validate(body, schema_of(Replied))
            where = body.get("ref") or body.get("topic")
            if not where:
                raise UsageError("give `ref` or `topic`")
            tokens = body.get("attachments", [])
            files = [self.uploads.path(token) for token in tokens]
            if "ref" in body:
                self.topics.update_item(
                    body["ref"], None, reply=body["text"], author=Author.OWNER, attachments=files
                )
            else:
                self.topics.update_topic(
                    body["topic"], {}, reply=body["text"], author=Author.OWNER, attachments=files
                )
            self.uploads.sent(tokens)
            return {"replied": where}
        if route == "withdraw":
            validate(body, schema_of(Where))
            back: list[dict[str, Any]] = []
            text = self.topics.withdraw(
                body.get("ref"),
                body.get("topic"),
                keep=lambda path, entry: back.append(self.uploads.adopt(path, entry["name"])),
            )
            return {"text": text, **({"attachments": back} if back else {})}
        if route == "seen":
            validate(body, schema_of(Where))
            if "ref" in body:
                where = self.topics.item(body["ref"])["ref"]
            elif "topic" in body:
                where = self.topics.topic(body["topic"])["name"]
            else:
                raise UsageError("give `ref` or `topic`")
            self.seen.look(where)
            return {"seen": where}
        if route == "prefer":
            validate(body, schema_of(Preferred))
            item, _ = self.topics.prefer(
                body["ref"], body["version"], body.get("name"), body.get("asset")
            )
            held = next(
                (
                    asset
                    for asset in item["assets"]
                    if asset["name"] == body.get("asset")
                    or (body.get("asset") is None and asset.get("variants"))
                ),
                None,
            )
            return {"preferred": (held or {}).get("preferred")}
        if route == "ask":
            validate(body, schema_of(Question))
            return self.asking.start(body["question"])
        if route == "ask/cancel":
            return self.asking.cancel()
        raise NotFoundError("no such page")


# The Timeline's filters: each a few kinds of event (`timeline.Event`).
FILTERS = {
    "answers": (Event.ANSWERED, Event.MESSAGE),
    "review": (Event.ITEM, Event.VERSION),
    "topics": (Event.TOPIC, Event.STATE, Event.STATUS, Event.REVIVED),
}
# How many events the Timeline shows before More.
SHOWN_EVENTS = 60


class TimelineTab(Tab):
    """`GET /timeline?query=Q&filter=F&limit=N`: the timeline's events
    (`nock.timeline`), the newest first — or, searched, the strongest match
    first — those of filter F (answers, review, topics), the first N, with
    how many each filter holds. Ask goes to the topics tab's `/topics/ask`."""

    name = "timeline"
    title = "Timeline"

    def __init__(self, project: Project) -> None:
        super().__init__(project)
        self.timeline = Timeline(project)

    def fragment(self) -> str:
        look = (PAGES / "timeline.css").read_text()
        return f"<style>\n{look}</style>\n" + super().fragment()

    def get(self, route: str) -> Any:
        if route.split("?")[0]:
            raise NotFoundError("no such page")
        asked = urllib.parse.parse_qs(route.partition("?")[2])
        query = asked.get("query", [""])[0]
        chosen = asked.get("filter", ["all"])[0]
        limit = asked.get("limit", [""])[0]
        events = self.timeline.matching(self.timeline.events(), query)
        counts = {"all": len(events)}
        for name, kinds in FILTERS.items():
            counts[name] = sum(1 for event in events if event["kind"] in kinds)
        if chosen in FILTERS:
            events = [event for event in events if event["kind"] in FILTERS[chosen]]
        shown = int(limit) if limit.isdigit() else SHOWN_EVENTS
        return {"events": events[:shown], "total": len(events), "counts": counts}


TABS: tuple[type[Tab], ...] = (TopicsTab, TimelineTab)


class Said(TypedDict):
    """The owner's message in the studio's chat: in chat `id`, or a new one,
    with the files uploaded for it (their tokens)."""

    id: NotRequired[str]
    text: str
    attachments: NotRequired[list[str]]


class Thread(TypedDict):
    """The one thread Address now answers: an item's (`ref`) or a topic's;
    neither, every thread where the owner's comment waits."""

    ref: NotRequired[str]
    topic: NotRequired[str]


class Which(TypedDict):
    """One of the studio's chats."""

    id: str


class ChatRoutes(Tab):
    """The studio's chat (`chats.Chats`), which no tab owns: the page shows
    it on every tab, from its button beside the settings. `GET /chat` every
    chat in a line, the latest first; `GET /chat/search/QUERY` the chats
    holding every word of it; `GET /chat/ID` one, with the answer
    being written; `POST /chat/send` the owner's message (a new chat without
    `id`), `/stop` stops the answer, `/leave` names the chat the owner
    leaves for a new one, `/tidy` starts Tidy up, `/undo` reverts its commit,
    `/address` starts Address my comments (with `ref` or `topic`, Address now: that one thread);
    `GET /chat/file/ID/PATH` a file a message carries. Files go up as in
    every chat (`topics/upload`), and are kept beside the chat."""

    name = "chat"
    title = "Chat"

    def __init__(self, project: Project, uploads: Uploads) -> None:
        super().__init__(project)
        self.chats = Chats(project)
        self.uploads = uploads

    def get(self, route: str) -> Any:
        if not route:
            return {"chats": self.chats.listing()}
        identifier, _, rest = urllib.parse.unquote(route).partition("/")
        if identifier == "file":
            chat, _, path = rest.partition("/")
            return Raw(self.chats.attachment(chat, path))
        if identifier == "search":
            return {"chats": self.chats.search(rest)}
        return self.chats.shown(identifier)

    def post(self, route: str, body: Any) -> Any:
        if route == "send":
            validate(body, schema_of(Said))
            tokens = body.get("attachments") or []
            files = [self.uploads.path(token) for token in tokens]
            shown = self.chats.send(body.get("id"), body["text"], files)
            self.uploads.sent(tokens)
            return shown
        if route == "tidy":
            return self.chats.tidy()
        if route == "address":
            validate(body, schema_of(Thread))
            return self.chats.address(body.get("ref") or body.get("topic"))
        actions = {"stop": self.chats.stop, "leave": self.chats.leave, "undo": self.chats.undo}
        if route in actions:
            validate(body, schema_of(Which))
            return actions[route](body["id"])
        raise NotFoundError("no such page")


class Choice(TypedDict):
    """The owner's answer on the page to whether nock shares its usage report."""

    share: bool


class RecorderSettings(TypedDict):
    """Where the recorder sends what the owner says, set in the settings."""

    transcribe_url: str
    """A Whisper server speaking OpenAI's `/v1/audio/transcriptions`; empty, off."""
    transcribe_model: str
    transcribe_key_variable: str
    """The name of the environment variable holding its key, never the key."""


TRANSCRIPTION = ("transcribe_url", "transcribe_model", "transcribe_key_variable")
# What a key variable may be called: an environment variable's name, never a key.
VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")


class Studio(ThreadingHTTPServer):
    def __init__(self, project: Project, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.project = project
        self.tabs = {tab.name: tab(project) for tab in TABS}
        # What the page asks the server: each tab's routes, and the chat's.
        topics = self.tabs[TopicsTab.name]
        assert isinstance(topics, TopicsTab)
        chat = ChatRoutes(project, topics.uploads)
        topics.chats = chat.chats
        self.routes: dict[str, Tab] = {**self.tabs, chat.name: chat}
        self.chats = chat.chats
        self.asking = topics.asking
        self.started = code_moment()
        # Tells one run of the studio from the next, which a restart keeps in the same process.
        self.instance = secrets.token_hex(8)
        self.restarting = False
        self.notifications = Notifications(project)
        self.notifications.started(self.address)

    def standing(self) -> dict[str, Any]:
        """`GET /restart`: whether the code changed since the studio started,
        what a restart would cut off (an answer being written, a question
        being asked), and which run of the studio answers."""
        busy = [WORK[Kind(self.chats.load(key)["kind"])] for key in list(self.chats.turns)]
        if self.chats.naming:
            busy.append("a chat is being named")
        if (self.asking.state() or {}).get("running"):
            busy.append("a question is being asked")
        return {"stale": code_moment() != self.started, "busy": busy, "instance": self.instance}

    def restart(self) -> None:
        """`POST /restart`: stop serving, then `run` starts the studio again
        in this process with the same arguments, on the same port. Refused
        while something runs that it would cut off."""
        busy = self.standing()["busy"]
        if busy:
            raise ConflictError(f"{', '.join(busy)}: restart once it is done, or it is cut off")
        self.restarting = True
        # Not from the handler's own thread: shutdown waits for the serving loop.
        threading.Thread(target=self.shutdown, daemon=True).start()

    def notified(self, query: str) -> dict[str, Any]:
        """`GET /notifications?after=ID&seen=SEEN`: the page's poll, saying how
        it is watched (`Watching`, which decides whether a notification goes to it
        or to the desktop), answered with what was notified after ID."""
        asked = urllib.parse.parse_qs(query)
        try:
            seen = Watching(asked.get("seen", [""])[0])
        except ValueError:
            seen = Watching.UNWATCHED
        self.notifications.watched(seen)
        after = asked.get("after", [""])[0]
        return self.notifications.since(int(after) if after.isdigit() else None)

    def question(self) -> str:
        """Under the title while nobody has answered: a slim line asking, with
        Share and Don't share; what the report holds is in the settings."""
        if sharing(self.project) is not Answer.UNANSWERED:
            return ""
        return (
            '    <div class="notice" id="usage" role="region" aria-label="Usage reports">\n'
            "      <p>May nock share a weekly usage report with its makers?</p>\n"
            '      <p class="choices"><button type="button" data-share="true">Share</button>'
            ' <button type="button" data-share="false">Don\'t share</button>'
            ' <button type="button" class="quiet" data-settings>What it holds</button></p>\n'
            "    </div>"
        )

    def settings(self) -> str:
        """The settings behind the gear in the menu: whether nock shares its
        usage report, as a switch that gives the same answer the question
        does, and what the report holds."""
        answer = sharing(self.project)
        said = {Answer.YES: "On", Answer.NO: "Off", Answer.UNANSWERED: "Not answered"}[answer]
        return (
            '      <div class="settings">\n'
            '        <button type="button" class="gear" aria-label="Settings" aria-expanded="false"'
            ' aria-controls="settings">'
            '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd"'
            ' d="M6.6 1h2.8l.4 1.9 1.2.7 1.8-.6 1.4 2.4-1.4 1.3v1.4l1.4 1.3-1.4 2.4-1.8-.6-1.2.7'
            "-.4 1.9H6.6l-.4-1.9-1.2-.7-1.8.6-1.4-2.4L3.2 8.7V7.3L1.8 6l1.4-2.4 1.8.6 1.2-.7z"
            'M8 10.2a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4z"/></svg></button>\n'
            '        <div class="popover" id="settings" role="dialog" aria-label="Settings" hidden>\n'
            '          <details class="group" id="sharing" open><summary><span>Sharing</span>'
            f' <span class="state" id="share-state">{said}</span></summary>\n'
            '          <div class="setting"><span id="share-label">Share usage reports</span>'
            ' <button type="button" class="switch" role="switch" id="share-switch"'
            f' aria-checked="{str(answer is Answer.YES).lower()}" aria-labelledby="share-label">'
            "<span></span></button></div>\n"
            '          <p class="hint">Weekly at most, counts and categories only: never code,'
            " paths, names or what items say.</p>\n"
            f'          <details class="holds"><summary>What it holds</summary><p>{html.escape(QUESTION)}</p></details>\n'
            "          </details>\n"
            f"{self.alerts()}"
            f"{self.transcription()}"
            "        </div>\n"
            "      </div>"
        )

    def alerts(self) -> str:
        """Whether this browser shows nock's notifications while the page is
        away: the browser is asked only when the owner turns them on here."""
        if not self.notifications.enabled:
            return (
                '          <details class="group" id="alerts"><summary><span>Notifications</span>'
                ' <span class="state">Off</span></summary>\n'
                '            <p class="hint"><code>notifications = false</code> in nock\'s config.</p></details>\n'
            )
        return (
            '          <details class="group" id="alerts" data-enabled><summary>'
            '<span id="alerts-label">Notifications</span>'
            ' <span class="state" id="alerts-state">Off</span></summary>\n'
            '            <p class="hint">In this browser, when a topic is your turn again: here while'
            " the studio is in front of you, from the browser while it is away, on the desktop"
            " when no page is open. The Timeline holds every one.</p>\n"
            '            <button type="button" class="save" id="alerts-allow">Turn on</button>\n'
            "          </details>\n"
        )

    def transcription(self) -> str:
        """The recorder's Whisper server, beside the sharing switch: kept in
        this machine's `.nock/local/config.toml`, never committed."""
        settings = self.project.configuration
        value = {
            key: html.escape(str(settings.get(f"studio.{key}") or "")) for key in TRANSCRIPTION
        }
        return (
            '          <details class="group"><summary><span id="transcription-label">Transcription</span>'
            ' <span class="state" id="transcription-state">'
            f"{'On' if value['transcribe_url'] else 'Off'}</span></summary>\n"
            '          <form class="fields" id="transcription" aria-labelledby="transcription-label">\n'
            '            <label>Whisper server <input name="transcribe_url" type="url" spellcheck="false"'
            ' placeholder="https://api.openai.com/v1" autocomplete="off"'
            f' value="{value["transcribe_url"]}"></label>\n'
            '            <label>Model <input name="transcribe_model" spellcheck="false" placeholder="whisper-1"'
            f' autocomplete="off" value="{value["transcribe_model"]}"></label>\n'
            '            <label>Key variable <input name="transcribe_key_variable" spellcheck="false"'
            ' placeholder="OPENAI_API_KEY" autocomplete="off" pattern="[A-Za-z_][A-Za-z0-9_]*"'
            f' value="{value["transcribe_key_variable"]}"></label>\n'
            '            <p class="hint">The recorder in every chat sends what you say there. The key'
            " variable names the environment variable holding the key, never the key. Kept on"
            " this machine, not committed.</p>\n"
            '            <button type="submit" class="save">Save</button>\n'
            "          </form></details>\n"
        )

    def configure(self, body: Any) -> dict[str, Any]:
        """The recorder's settings from the page, written to this machine's
        `.nock/local/config.toml` under `[studio]`."""
        validate(body, schema_of(RecorderSettings))
        values = {key: str(body[key]).strip() for key in TRANSCRIPTION}
        variable = values["transcribe_key_variable"]
        if variable and not VARIABLE.fullmatch(variable):
            raise UsageError(
                "the key variable is the name of an environment variable (OPENAI_API_KEY),"
                " never the key itself"
            )
        url = values["transcribe_url"]
        if url and not re.match(r"https?://", url):
            raise UsageError("the Whisper server is an http:// or https:// address")
        path = self.project.local / "config.toml"
        text = path.read_text() if path.is_file() else ""
        path.write_text(with_table_settings(text, "studio", values))
        self.project.__dict__.pop("configuration", None)
        return values

    def answer(self, body: Any) -> dict[str, Any]:
        validate(body, schema_of(Choice))
        return Usage(self.project).answer(body["share"], "studio")

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def page(self) -> bytes:
        """The shell with its look and every tab's link and panel in it, the
        first tab open."""
        links = "\n".join(
            f'      <a href="#{tab.name}" data-tab-link="{tab.name}">{html.escape(tab.title)}</a>'
            for tab in self.tabs.values()
        )
        panels = "\n".join(
            f'<section data-tab-panel="{tab.name}" hidden>\n{tab.fragment()}</section>'
            for tab in self.tabs.values()
        )
        shell = SHELL.read_text()
        return (
            shell.replace("<!-- nock:styles -->", f"<style>\n{LOOK.read_text()}</style>")
            .replace("<!-- nock:tabs -->", links)
            .replace("<!-- nock:panels -->", panels)
            .replace("<!-- nock:notice -->", self.question())
            .replace("<!-- nock:settings -->", self.settings())
            .encode()
        )

    def run(self, open_browser: bool) -> None:
        print(f"nock: {self.address} (Ctrl-C to stop)", flush=True)
        if open_browser and not os.environ.pop(RESTARTED, ""):
            webbrowser.open(self.address)
        try:
            self.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.server_close()
            if not self.restarting:
                self.notifications.path.unlink(missing_ok=True)
        if self.restarting:
            print("nock: restarting the studio", flush=True)
            os.environ[RESTARTED] = "1"
            os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


class Handler(BaseHTTPRequestHandler):
    """`GET /` the page; `GET /icon.png` nock's logo, for the notifications; `GET /restart` whether the code changed since it
    started and what is running, `POST /restart` starts it again in place;
    `GET /notifications` the page's poll for what to tell the owner;
    `POST /usage` the owner's answer on sharing, `/settings`
    the recorder's server; `/NAME/ROUTE`
    goes to the tab named, `/chat/ROUTE` to the chat."""

    @property
    def studio(self) -> Studio:
        assert isinstance(self.server, Studio)
        return self.server

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/":
            self.send(HTTPStatus.OK, self.studio.page(), "text/html")
            return
        if self.path == "/restart":
            self.send_json(HTTPStatus.OK, self.studio.standing())
            return
        if self.path == "/icon.png":
            self.send_file(ICON)
            return
        address = urllib.parse.urlsplit(self.path)
        if address.path == "/notifications":
            self.send_json(HTTPStatus.OK, self.studio.notified(address.query))
            return
        self.answer(lambda tab, route: tab.get(route))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        address = urllib.parse.urlsplit(self.path)
        name, _, route = address.path.removeprefix("/").partition("/")
        tab = self.studio.tabs.get(name)
        body: Any
        if tab is not None and route in tab.raw:
            query = urllib.parse.parse_qs(address.query)
            kind = self.headers.get("Content-Type", "")
            body = Upload(query.get("name", ["file"])[0], kind, length, self.rfile)
        else:
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
        if self.path == "/restart":
            try:
                self.studio.restart()
            except Error as error:
                self.send_json(HTTPStatus.CONFLICT, {"error": str(error)})
                return
            self.send_json(HTTPStatus.OK, {"restarting": True})
            return
        if self.path in ("/usage", "/settings"):
            take = self.studio.answer if self.path == "/usage" else self.studio.configure
            try:
                self.send_json(HTTPStatus.OK, take(body))
            except Error as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.answer(lambda tab, route: tab.post(route, body))

    def answer(self, call: Callable[[Tab, str], Any]) -> None:
        address, _, query = self.path.partition("?")
        name, _, route = address.removeprefix("/").partition("/")
        if name == TimelineTab.name and not route:
            route = f"?{query}"
        tab = self.studio.routes.get(name)
        if tab is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such page"})
            return
        try:
            value = call(tab, route)
        except Error as error:
            status = (
                HTTPStatus.NOT_FOUND if isinstance(error, NotFoundError) else HTTPStatus.BAD_REQUEST
            )
            self.send_json(status, {"error": str(error)})
            return
        if isinstance(value, Raw):
            self.send_file(value.path)
            return
        if isinstance(value, Html):
            self.send(HTTPStatus.OK, value.text.encode(), "text/html")
            return
        self.send_json(HTTPStatus.OK, value)

    def send_file(self, path: Path) -> None:
        """A file as it is; a byte range of it when asked, so a video seeks."""
        size = path.stat().st_size
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/json", "image/svg+xml"):
            kind += "; charset=utf-8"
        asked = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        start, end = 0, size - 1
        if asked and size and (asked.group(1) or asked.group(2)):
            if asked.group(1):
                start = int(asked.group(1))
                end = min(int(asked.group(2) or end), end)
            else:
                start = max(size - int(asked.group(2)), 0)
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with path.open("rb") as file:
            file.seek(start)
            left = end - start + 1 if size else 0
            while left > 0:
                chunk = file.read(min(left, 1 << 20))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except ConnectionError:
                    # The browser stops a video's download once it has what it shows.
                    return
                left -= len(chunk)

    def send_json(self, status: HTTPStatus, value: Any) -> None:
        self.send(status, json.dumps(value).encode(), "application/json")

    def send(self, status: HTTPStatus, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *arguments: Any) -> None:
        pass
