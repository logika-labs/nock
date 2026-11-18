"""The owner's page (`nock studio`): one local server for one page. Its front
lists the tasks (topics, in nock's files: the word the owner reads is
`topics.WORD`), each with what waits on the owner and what it holds; a task
opens on its review, the page its agent composed from blocks, told as a story
or listed flat, with its decisions, proposals and assets, their notes and its
one chat. The page polls `/api/stamp` and reads again when the store moved,
so it updates as agents write; `/notifications` tells the owner when a task
is their turn (`nock.notify`), and the history is `nock.timeline`'s. Rounds
that are due show as hints; Run starts one in the background (`nock.runs`).

`GET /` is the page (`pages/studio.html` with `pages/studio.css` and
`pages/app.js` put in); `/api/…` its JSON, a nock `Error` becoming 404 or 400.
Local, and only while `nock studio` runs."""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from nock.errors import ConflictError, Error, NotFoundError, UsageError
from nock.inbox import listeners
from nock.notify import ICON, Notifications, Watching
from nock.project import Project
from nock.runs import Runs
from nock.shared import MEMORY_LIMIT, kind_of
from nock.timeline import Timeline
from nock.topics import MEMORY_TASK, WORD, WORDS, Status, Topics, entry_name, pending, target_of
from nock.usage import QUESTION, Answer, Usage, sharing

PACKAGE = Path(__file__).resolve().parent
# Set across a restart in place, so the studio does not open the browser again.
RESTARTED = "NOCK_STUDIO_RESTARTED"
PAGES = PACKAGE / "pages"
SHELL = PAGES / "studio.html"
LOOK = PAGES / "studio.css"
APP = PAGES / "app.js"
# The look an html block is served with: nock's styles, for what agents write.
VIEW_LOOK = PAGES / "view.css"
# What an html block may say to the page (`window.nock`): leave a note on
# itself, accept or reject a proposal, size itself.
BRIDGE = """<script>
(() => {
  const say = (message) => parent.postMessage({nock: true, ...message}, "*");
  window.nock = Object.assign(window.nock || {}, {
    note: (text, quote) => say({action: "note", text: String(text || ""), quote: quote ? String(quote) : undefined}),
    accept: (item) => say({action: "verdict", item: String(item), verdict: "accepted"}),
    reject: (item) => say({action: "verdict", item: String(item), verdict: "rejected"}),
    open: (address) => say({action: "open", address: String(address)}),
  });
  const size = () => say({action: "size", height: document.documentElement.scrollHeight});
  addEventListener("load", size);
  new ResizeObserver(size).observe(document.documentElement);
})();
</script>"""
MESSAGE_ID = re.compile(r"^[0-9a-f]{8}$")
# The largest text file the page is given whole, for a doc, an excerpt or a diff.
TEXT_LIMIT = 512 * 1024


def code_moment() -> int:
    """When nock's code last changed on disk: a studio left running across an
    update offers to restart."""
    return max(path.stat().st_mtime_ns for path in PACKAGE.glob("*.py"))


@dataclass(frozen=True)
class Raw:
    """A file answered as it is, typed by `name` (media is kept by hash)."""

    path: Path
    name: str = ""


@dataclass(frozen=True)
class Html:
    text: str


@dataclass(frozen=True)
class Upload:
    """A request's body as it is: a file the owner dropped into the chat."""

    name: str
    kind: str
    length: int
    stream: io.BufferedIOBase


def attachment_name(name: str) -> str:
    """A file's name as kept: its last part, nothing that walks out of a folder."""
    base = Path(name.replace("\\", "/")).name.strip() or "file"
    return re.sub(r"[^\w.\- ]", "_", base)[:120] or "file"


class Uploads:
    """Files dropped into a chat's composer, kept on this machine
    (`.nock/local/studio/uploads/TOKEN/NAME`) until the message they go with
    is sent."""

    def __init__(self, project: Project) -> None:
        self.directory = project.local / "studio" / "uploads"
        shutil.rmtree(self.directory, ignore_errors=True)

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
        return {"token": path.parent.name, "name": path.name, "bytes": path.stat().st_size}

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


def text(body: dict[str, Any], key: str, required: bool = True) -> str:
    value = body.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise UsageError(f"`{key}` is a string")
    return value


class Api:
    """The page's JSON: what it reads (`get`) and what the owner does (`post`)."""

    def __init__(self, project: Project, runs: Runs) -> None:
        self.project = project
        self.topics = Topics(project)
        self.runs = runs
        self.uploads = Uploads(project)

    # --- reading ------------------------------------------------------------------

    def stamp(self) -> str:
        """What changes whenever anything the page shows does: the store's
        commits and uncommitted files, the runs, the notifications."""
        git = self.project.git
        head = git("log", "-1", "--format=%H", "--", ".nock/shared", check=False).strip()
        status = git(
            "--no-optional-locks", "status", "--porcelain", "--", ".nock/shared", check=False
        )
        runs = self.runs.directory
        moved = max((path.stat().st_mtime_ns for path in runs.glob("*.json")), default=0)
        live = sum(len(progress.lines) for progress in self.runs.progress.values())
        return f"{head}:{hash(status)}:{moved}:{live}"

    def get(self, route: str, query: dict[str, list[str]]) -> Any:
        parts = [urllib.parse.unquote(part) for part in route.split("/") if part]
        if parts == ["stamp"]:
            return {"stamp": self.stamp()}
        if parts == ["topics"]:
            return self.front()
        if len(parts) == 2 and parts[0] == "topic":
            return self.whole(parts[1])
        if parts[:1] == ["asset"] and len(parts) >= 4 and parts[3].isdigit():
            topic, name, version = parts[1], parts[2], int(parts[3])
            asset = self.topics.asset(topic, name)
            found = self.topics.version_of(asset, version)
            if len(parts) == 5:
                return Raw(self.topics.companion(topic, name, found, parts[4]), parts[4])
            return Raw(self.topics.located(topic, name, found), entry_name(found["file"]))
        if parts[:1] == ["html"] and len(parts) == 4 and parts[2].isdigit():
            path = self.topics.html_block(parts[1], int(parts[2]), parts[3])
            return Html(self.html(path))
        if parts[:1] == ["attachment"] and len(parts) >= 3:
            name = "/".join(parts[2:])
            return Raw(self.topics.attachment(parts[1], name), name)
        if parts == ["history"]:
            topic = (query.get("topic") or [None])[0]
            return {"events": Timeline(self.project).events(topic, limit=200)}
        if parts == ["runs"]:
            return {"runs": self.runs.listing()}
        if len(parts) == 2 and parts[0] == "run":
            return {"run": self.runs.turn(parts[1])}
        if parts == ["rounds"]:
            from nock.rounds import listing

            return {"rounds": listing(self.project)}
        if parts == ["settings"]:
            return self.settings()
        if parts == ["memory"]:
            return self.memory()
        raise NotFoundError("no such page")

    def front(self) -> dict[str, Any]:
        """Every task with what waits on the owner and what it holds; the two
        counts (active tasks, items pending for the owner) and their lists;
        the rounds due; the runs."""
        from nock.rounds import hints

        tasks = []
        pending_items = []
        for row in self.topics.rows():
            name = row["name"]
            items = self.topics.items(name)
            review = self.topics.current_review(name)
            tasks.append(
                {
                    **row,
                    "summary": review["summary"] if review else "",
                    "items": [
                        {
                            "slug": item["slug"],
                            "ref": item["ref"],
                            "title": item["title"],
                            "means": item["means"],
                            "status": item["status"],
                            "proposed": item["proposed"],
                        }
                        for item in items
                        if item["status"] != Status.REJECTED
                    ],
                    "assets": [
                        {"name": asset["name"], "title": asset["title"]}
                        for asset in self.topics.assets(name)
                    ],
                }
            )
            if row["state"] in ("done", "abandoned"):
                continue
            for item in items:
                if item["status"] == Status.OPEN:
                    pending_items.append(
                        {
                            "topic": name,
                            "kind": "proposal",
                            "slug": item["slug"],
                            "title": item["title"],
                        }
                    )
            if review and not row["reviewed"]:
                pending_items.append(
                    {
                        "topic": name,
                        "kind": "review",
                        "slug": None,
                        "title": review["summary"] or f"The review of {name}",
                    }
                )
        active = [task for task in tasks if task["state"] in ("active", "planned")]
        return {
            "word": WORD,
            "words": WORDS,
            "project": self.project.root.name,
            "stamp": self.stamp(),
            "tasks": tasks,
            "active": [
                {"topic": task["name"], "title": task["status"] or task["description"]}
                for task in active
            ],
            "pending": pending_items,
            "hints": hints(self.project),
            "runs": [run for run in self.runs.listing(limit=10) if run.get("kind") == "round"],
            "listening": listeners(self.project),
        }

    def whole(self, name: str) -> dict[str, Any]:
        """A task whole: its record, its items, its assets (each version's file,
        its address, its text when small), its review (every version), its
        chat with each message's notes, its unsent notes, its runs."""
        topics = self.topics
        topic = topics.topic(name)
        row = topics.row(name)
        assets = []
        for asset in topics.assets(name):
            versions = []
            for version in asset["versions"]:
                entry = version["file"]
                file_name = entry_name(entry)
                path = topics.located(name, asset["name"], version)
                kind = entry.get("type") or kind_of(file_name, b"")
                shown: dict[str, Any] = {
                    "version": version["version"],
                    "moment": version["moment"],
                    "role": version.get("role"),
                    "name": file_name,
                    "type": kind,
                    "kind": entry.get("kind"),
                    "from": entry.get("from") or [],
                    "when": entry.get("when"),
                    "recipe": entry.get("recipe"),
                    "address": f"/api/asset/{name}/{asset['name']}/{version['version']}",
                }
                for role in ("captions", "poster"):
                    if entry.get(role):
                        shown[role] = f"{shown['address']}/{entry[role]}"
                if (
                    kind in ("text", "html")
                    and path.is_file()
                    and path.stat().st_size <= TEXT_LIMIT
                ):
                    shown["text"] = path.read_text(errors="replace")
                versions.append(shown)
            assets.append({**asset, "versions": versions})
        review = topics.review(name)
        current = review["versions"][-1] if review["versions"] else None
        thread = []
        for entry in topic["thread"]:
            if entry.get("kind") == "message":
                entry = {
                    **entry,
                    "carried": topics.carried(topic, entry),
                    "attachments": [
                        {**file, "address": f"/api/attachment/{name}/{file['path']}"}
                        for file in entry.get("attachments", [])
                    ],
                }
            thread.append(entry)
        notes = [{**note, "target": target_of(note, current)} for note in topic["notes"]]
        return {
            "word": WORD,
            "topic": {**topic, "thread": thread, "notes": notes},
            "row": row,
            "items": topics.items(name),
            "assets": assets,
            "review": review,
            "reviewed": topics.reviewed(topic),
            "waiting": bool(pending(topic["thread"])),
            "runs": [run for run in self.runs.listing(limit=50) if run.get("topic") == name],
            "listening": listeners(self.project),
        }

    def memory(self) -> dict[str, Any]:
        """The memory as it stands, what holds it back, and the owner's notes
        on its lines (kept in the task `memory`, with its chat)."""
        path = self.topics.memory
        notes = []
        if MEMORY_TASK in self.topics.names():
            topic = self.topics.topic(MEMORY_TASK)
            notes = [
                {**note, "target": target_of(note)}
                for note in topic["notes"]
                if note["on"].get("memory")
            ]
        return {
            "text": path.read_text() if path.is_file() else "",
            "path": str(path.relative_to(self.project.root)),
            "limit": MEMORY_LIMIT,
            "problems": [str(problem) for problem in self.topics.memory_problems()],
            "notes": notes,
            "task": MEMORY_TASK,
        }

    def html(self, path: Path) -> str:
        """An html block with nock's look and the bridge put in its head."""
        page = path.read_text(errors="replace")
        head = f"<style>{VIEW_LOOK.read_text()}</style>{BRIDGE}"
        if re.search(r"<head[^>]*>", page, re.IGNORECASE):
            return re.sub(
                r"(<head[^>]*>)",
                lambda found: found.group(1) + head,
                page,
                count=1,
                flags=re.IGNORECASE,
            )
        return f"<!doctype html><html><head><meta charset='utf-8'>{head}</head><body>{page}</body></html>"

    def settings(self) -> dict[str, Any]:
        answer = sharing(self.project)
        return {
            "share": {Answer.YES: True, Answer.NO: False}.get(answer),
            "question": QUESTION,
            "notifications": Notifications(self.project).enabled,
        }

    # --- what the owner does ------------------------------------------------------

    def post(self, route: str, body: Any) -> Any:
        parts = [part for part in route.split("/") if part]
        if parts == ["upload"]:
            return self.uploads.stage(body)
        if not isinstance(body, dict):
            raise UsageError("the body is a JSON object")
        if parts == ["upload", "discard"]:
            self.uploads.discard(text(body, "token"))
            return {"discarded": body["token"]}
        if parts == ["memory"]:
            self.topics.edit_memory(text(body, "text", required=False))
            return self.memory()
        if parts == ["note"]:
            on = body.get("on")
            if body.get("topic") == MEMORY_TASK:
                self.topics.memory_task()
            if not isinstance(on, dict):
                raise UsageError("`on` says what the note is on: item, asset, block")
            identifier = body.get("id")
            if identifier is not None and not MESSAGE_ID.match(str(identifier)):
                raise UsageError("`id` is 8 lowercase hexadecimal digits")
            return {
                "note": self.topics.note(
                    text(body, "topic"),
                    on,
                    text(body, "text", required=False),
                    replaces=body.get("replaces") or None,
                    identifier=identifier,
                )
            }
        if parts == ["send"]:
            topic = text(body, "topic")
            identifier = body.get("id")
            if identifier is not None and not MESSAGE_ID.match(str(identifier)):
                raise UsageError("`id` is 8 lowercase hexadecimal digits")
            tokens = body.get("attachments") or []
            files = [
                {"path": str(self.uploads.path(token)), "name": self.uploads.path(token).name}
                for token in tokens
            ]
            message = self.topics.send(
                topic, text(body, "text", required=False), files, identifier=identifier
            )
            for token in tokens:
                shutil.rmtree(self.uploads.directory / token, ignore_errors=True)
            return {"message": message, "run": self.answer(topic)}
        if parts == ["verdict"]:
            item = self.topics.judge(text(body, "ref"), text(body, "verdict"))
            return {"item": item}
        if parts == ["done"]:
            topic = text(body, "topic")
            done = self.topics.done(topic)
            return {**done, "run": self.answer(topic) if done["sent"] else None}
        if parts == ["runs", "stop"]:
            return {"run": self.runs.stop(text(body, "id"))}
        if parts == ["rounds", "run"]:
            return {"run": self.runs.round(text(body, "name"))}
        if parts == ["rounds", "snooze"]:
            from nock.rounds import snooze

            return {"round": snooze(self.project, text(body, "name"), body)}
        if parts == ["rounds", "set"]:
            from nock.rounds import configure

            return {"round": configure(self.project, text(body, "name"), body)}
        raise NotFoundError("no such page")

    def answer(self, topic: str) -> dict[str, Any] | None:
        """The message just sent, answered now; what stops it is said, not raised."""
        try:
            return self.runs.answer(topic)
        except (ConflictError, UsageError) as error:
            return {"problem": str(error)}


class Studio(ThreadingHTTPServer):
    def __init__(self, project: Project, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.project = project
        self.started = code_moment()
        # Tells one run of the studio from the next, which a restart keeps in the same process.
        self.instance = secrets.token_hex(8)
        self.runs = Runs(project, self.instance)
        self.api = Api(project, self.runs)
        self.restarting = False
        self.notifications = Notifications(project)
        self.notifications.started(self.address)

    def standing(self) -> dict[str, Any]:
        """`GET /restart`: whether the code changed since the studio started,
        what a restart would cut off, and which run of the studio answers."""
        busy = [
            run["title"]
            for run in self.runs.listing()
            if run["status"] == "running" and run["id"] in self.runs.progress
        ]
        return {"stale": code_moment() != self.started, "busy": busy, "instance": self.instance}

    def restart(self) -> None:
        busy = self.standing()["busy"]
        if busy:
            raise ConflictError(f"{', '.join(busy)}: restart once it is done, or it is cut off")
        self.restarting = True
        threading.Thread(target=self.shutdown, daemon=True).start()

    def notified(self, query: str) -> dict[str, Any]:
        """`GET /notifications?after=ID&seen=SEEN`: the page's poll, saying how
        it is watched (`Watching`), answered with what was notified after ID."""
        asked = urllib.parse.parse_qs(query)
        try:
            seen = Watching(asked.get("seen", [""])[0])
        except ValueError:
            seen = Watching.UNWATCHED
        self.notifications.watched(seen)
        after = asked.get("after", [""])[0]
        return self.notifications.since(int(after) if after.isdigit() else None)

    def answer_usage(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("share"), bool):
            raise UsageError('`{"share": true}` or false')
        return Usage(self.project).answer(body["share"], "studio")

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def page(self) -> bytes:
        asked = sharing(self.project) is Answer.UNANSWERED
        return (
            SHELL.read_text()
            .replace("<!-- nock:styles -->", f"<style>\n{LOOK.read_text()}</style>")
            .replace("<!-- nock:app -->", f"<script>\n{APP.read_text()}</script>")
            .replace("<!-- nock:word -->", WORD)
            .replace('data-ask-usage="false"', f'data-ask-usage="{str(asked).lower()}"')
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
    """`GET /` the page; `/icon.png` nock's logo; `/restart` whether the code
    changed, `POST /restart` starts it again in place; `/notifications` the
    page's poll; `POST /usage` the owner's answer on sharing; `/api/…` the
    page's JSON (`Api`)."""

    @property
    def studio(self) -> Studio:
        assert isinstance(self.server, Studio)
        return self.server

    def do_GET(self) -> None:
        address = urllib.parse.urlsplit(self.path)
        if address.path == "/":
            self.send(HTTPStatus.OK, self.studio.page(), "text/html")
            return
        if address.path == "/restart":
            self.send_json(HTTPStatus.OK, self.studio.standing())
            return
        if address.path == "/icon.png":
            self.send_file(ICON)
            return
        if address.path == "/notifications":
            self.send_json(HTTPStatus.OK, self.studio.notified(address.query))
            return
        if address.path.startswith("/api/"):
            query = urllib.parse.parse_qs(address.query)
            self.answer(lambda: self.studio.api.get(address.path.removeprefix("/api/"), query))
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such page"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        address = urllib.parse.urlsplit(self.path)
        body: Any
        if address.path == "/api/upload":
            query = urllib.parse.parse_qs(address.query)
            kind = self.headers.get("Content-Type", "")
            body = Upload(query.get("name", ["file"])[0], kind, length, self.rfile)
        else:
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
        if address.path == "/restart":
            try:
                self.studio.restart()
            except Error as error:
                self.send_json(HTTPStatus.CONFLICT, {"error": str(error)})
                return
            self.send_json(HTTPStatus.OK, {"restarting": True})
            return
        if address.path == "/usage":
            self.answer(lambda: self.studio.answer_usage(body))
            return
        if address.path.startswith("/api/"):
            self.answer(lambda: self.studio.api.post(address.path.removeprefix("/api/"), body))
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such page"})

    def answer(self, call: Any) -> None:
        try:
            value = call()
        except Error as error:
            status = (
                HTTPStatus.NOT_FOUND if isinstance(error, NotFoundError) else HTTPStatus.BAD_REQUEST
            )
            self.send_json(status, {"error": str(error)})
            return
        if isinstance(value, Raw):
            if not value.path.is_file():
                self.send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": f"{value.name or value.path.name} is missing on this machine"},
                )
                return
            self.send_file(value.path, value.name)
            return
        if isinstance(value, Html):
            self.send(HTTPStatus.OK, value.text.encode(), "text/html")
            return
        self.send_json(HTTPStatus.OK, value)

    def send_file(self, path: Path, name: str = "") -> None:
        """A file as it is; a byte range of it when asked, so a video seeks."""
        size = path.stat().st_size
        kind = mimetypes.guess_type(name or path.name)[0] or "application/octet-stream"
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
