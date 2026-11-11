"""The owner's chats on the page carry files: dropped into a composer they are
uploaded at once, sent with the message they go with, kept beside its thread
and committed (a large one stays on this machine), and every agent reading
the thread is given their paths; a recording is made text by the Whisper
server the project names, a stand-in here, and nothing is sent without one."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from nock.hooks import HookRunner
from nock.project import Project
from nock.status import Standing
from nock.topics import Topics

from .conftest import git
from .test_topics import DECISION, page, post, run, submit

__all__ = ["page"]

PICTURE = b"\x89PNG\r\n\x1a\n" + bytes(200)


def upload(address: str, name: str, data: bytes) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{address}topics/upload?name={urllib.request.quote(name)}",
        data=data,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def fetch(address: str, route: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(f"{address}topics/{route}") as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def search(address: str, query: str) -> Any:
    with urllib.request.urlopen(f"{address}topics/search/{urllib.parse.quote(query)}") as response:
        found = json.loads(response.read())
    return {"topics": found["topics"], "items": found["items"]}


def test_the_owner_s_files_go_with_their_message_beside_its_thread_for_agents_to_read(
    project: Project, page: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ref = submit(project.root)
    slug = ref.split("/")[1]
    monkeypatch.setattr("nock.topics.LARGE", 1000)
    shot = upload(page, "shot.png", PICTURE)
    notes = upload(page, "../notes.txt", b"Use Postgres.\n")
    film = upload(page, "film.webm", bytes(2000))
    assert (shot["name"], shot["type"], shot["bytes"]) == ("shot.png", "image", 208)
    assert notes["name"] == "notes.txt" and notes["type"] == "text"
    status, preview = fetch(page, f"upload/{shot['token']}")
    assert status == 200 and preview == PICTURE
    status, _ = post(page, "upload/discard", {"token": film["token"]})
    assert status == 200 and fetch(page, f"upload/{film['token']}")[0] == 404
    film = upload(page, "film.webm", bytes(2000))

    tokens = [shot["token"], notes["token"], film["token"]]
    status, _ = post(page, "reply", {"ref": ref, "text": "See these.", "attachments": tokens})
    assert status == 200
    (said,) = Topics(project).item(ref)["thread"]
    attached = said["attachments"]
    assert [(entry["name"], entry["type"]) for entry in attached] == [
        ("shot.png", "image"),
        ("notes.txt", "text"),
        ("film.webm", "video"),
    ]
    folder = attached[0]["path"].rsplit("/", 1)[0]
    assert folder.startswith("attachments/") and attached[0]["bytes"] == 208
    # Every file a message carries is media, kept by its content.
    media = project.root / ".nock" / "shared" / "media"
    assert (media / attached[0]["sha256"]).read_bytes() == PICTURE
    assert (media / attached[2]["sha256"]).stat().st_size == 2000
    assert git(project.root, "status", "--porcelain") == ""
    assert f".nock/shared/media/{attached[1]['sha256']}" in git(project.root, "ls-files")
    assert not any((project.local / "studio" / "uploads").iterdir())
    status, served = fetch(page, f"attachment/orders/{slug}/{attached[1]['path']}")
    assert status == 200 and served == b"Use Postgres.\n"
    assert fetch(page, f"attachment/orders/{slug}/attachments/{folder}/other.txt")[0] == 404
    status, refused = post(page, "reply", {"ref": ref, "text": "x", "attachments": ["0" * 16]})
    assert status == 404 and "drop the file again" in refused["error"]

    shown = run(project.root, "items", "show", ref)["thread"][0]["attachments"]
    assert [Path(entry["where"]).read_bytes()[:4] for entry in shown[:2]] == [
        PICTURE[:4],
        b"Use ",
    ]
    awaiting = run(project.root, "topics", "list")["summary"]["awaiting_you"]
    assert awaiting["owner_wrote_last"] == [ref]
    assert awaiting["attachments"] == {ref: [entry["where"] for entry in shown]}

    standing = Standing(project)
    assert f"- answer in {ref} (attached: {shown[0]['where']}," in "\n".join(
        standing.lines(standing.collect())
    )

    prompt = HookRunner(project, {"session_id": "s1"}).handle("UserPromptSubmit")
    assert prompt is not None
    told = prompt["hookSpecificOutput"]["additionalContext"]
    assert f"[{ref}] Orders live in SQLite — open: See these." in told
    assert f"attached (Read them): {shown[0]['where']}" in told

    # A topic's chat carries files too, and a message of files alone says nothing else.
    sheet = upload(page, "plan.txt", b"The plan.\n")
    status, _ = post(
        page, "reply", {"topic": "orders", "text": "", "attachments": [sheet["token"]]}
    )
    assert status == 200
    thread = run(project.root, "topics", "show", "orders")["thread"]
    (entry,) = [entry for entry in thread if entry.get("attachments")]
    assert entry["text"] == "" and Path(entry["attachments"][0]["where"]).read_text() == (
        "The plan.\n"
    )
    assert entry["attachments"][0]["path"].startswith("attachments/")
    status, served = fetch(page, f"attachment/orders/{entry['attachments'][0]['path']}")
    assert status == 200 and served == b"The plan.\n"
    # Search finds a message's files by name, in an item's thread and a topic's.
    assert search(page, "notes.txt") == {"topics": [], "items": [ref]}
    assert search(page, "plan.txt") == {"topics": ["orders"], "items": []}
    status, empty = post(page, "reply", {"ref": submit(project.root), "text": " "})
    assert status == 400 and "empty" in empty["error"]


def test_a_withdrawn_message_s_files_come_back_to_be_sent_again(
    project: Project, page: str
) -> None:
    ref = submit(project.root)
    shot = upload(page, "shot.png", PICTURE)
    post(page, "reply", {"ref": ref, "text": "Look.", "attachments": [shot["token"]]})
    path = Topics(project).item(ref)["thread"][0]["attachments"][0]["path"]
    status, taken = post(page, "withdraw", {"ref": ref})
    assert status == 200 and taken["text"] == "Look."
    (back,) = taken["attachments"]
    assert back["name"] == "shot.png" and back["token"] != shot["token"]
    assert Topics(project).item(ref)["thread"] == []
    assert git(project.root, "status", "--porcelain") == ""
    status, _ = post(
        page, "reply", {"ref": ref, "text": "Look again.", "attachments": [back["token"]]}
    )
    assert status == 200
    again = Topics(project).item(ref)["thread"][0]["attachments"][0]
    assert again["path"] == path
    assert (project.root / ".nock" / "shared" / "media" / again["sha256"]).read_bytes() == PICTURE


def test_an_item_may_be_called_attachments(project: Project) -> None:
    # Items live under `items/`, beside nothing else of their topic's.
    ref = submit(project.root, {**DECISION, "title": "Attachments"})
    assert ref == "orders/attachments"


class Whisper(BaseHTTPRequestHandler):
    """A stand-in for a Whisper server: what it was sent, and its answer."""

    asked: list[dict[str, Any]] = []
    status = 200
    answer = b'{"text": " Orders live in Postgres. "}'

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Whisper.asked.append({"path": self.path, "headers": dict(self.headers), "body": body})
        self.send_response(Whisper.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(Whisper.answer)

    def log_message(self, format: str, *arguments: Any) -> None:
        pass


@pytest.fixture
def whisper() -> Iterator[str]:
    Whisper.asked, Whisper.status = [], 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), Whisper)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def transcribe(address: str, audio: bytes) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{address}topics/transcribe",
        data=audio,
        headers={"Content-Type": "audio/webm;codecs=opus"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def configure(project: Project, studio: str) -> None:
    local = project.local / "config.toml"
    local.write_text(f"{local.read_text()}[studio]\n{studio}")


def test_a_recording_is_made_text_by_the_whisper_server_configured_and_by_none_without_one(
    project: Project, page: str, whisper: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with urllib.request.urlopen(f"{page}topics") as response:
        off = json.loads(response.read())["transcription"]
    assert off["enabled"] is False and "transcribe_url" in off["hint"]
    status, refused = transcribe(page, b"audio")
    assert status == 400 and "transcribe_url" in refused["error"] and Whisper.asked == []

    configure(project, f'transcribe_url = "{whisper}"\ntranscribe_key_variable = "WHISPER_KEY"\n')
    status, unset = transcribe(page, b"audio")
    assert status == 400 and "WHISPER_KEY" in unset["error"] and Whisper.asked == []
    monkeypatch.setenv("WHISPER_KEY", "sk-test")
    status, said = transcribe(page, b"OggS-recorded-audio")
    assert status == 200 and said == {"text": "Orders live in Postgres."}
    (asked,) = Whisper.asked
    assert asked["path"] == "/v1/audio/transcriptions"
    assert asked["headers"]["Authorization"] == "Bearer sk-test"
    assert asked["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    body = asked["body"]
    assert b'name="model"\r\n\r\nwhisper-1\r\n' in body
    assert b'name="response_format"\r\n\r\njson\r\n' in body
    assert b'name="file"; filename="recording.webm"\r\nContent-Type: audio/webm\r\n\r\n' in body
    assert b"OggS-recorded-audio" in body
    with urllib.request.urlopen(f"{page}topics") as response:
        assert json.loads(response.read())["transcription"] == {"enabled": True}

    Whisper.status, Whisper.answer = 500, b'{"error": "model not loaded"}'
    status, failed = transcribe(page, b"audio")
    assert (
        status == 400
        and "answered 500" in failed["error"]
        and "model not loaded" in failed["error"]
    )
    project.local.joinpath("config.toml").write_text(
        project.local.joinpath("config.toml")
        .read_text()
        .replace(whisper, f"{whisper}/v1/audio/transcriptions")
        .replace('transcribe_key_variable = "WHISPER_KEY"\n', 'transcribe_model = "small"\n')
    )
    Whisper.status, Whisper.answer = 200, b'{"text": "Hi."}'
    assert transcribe(page, b"audio") == (200, {"text": "Hi."})
    assert b'name="model"\r\n\r\nsmall\r\n' in Whisper.asked[-1]["body"]
    assert "Authorization" not in Whisper.asked[-1]["headers"]
