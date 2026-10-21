"""The owner's page (`nock web`): the decisions agents recorded, reviewed in
place — accepted, rejected, noted, or sent to an agent to elaborate. Local,
and only while `nock web` runs."""

from __future__ import annotations

import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from nock.commands import schema_of
from nock.decisions import Change, Decisions, Review
from nock.errors import Error, NotFoundError
from nock.schema import validate

PAGE = Path(__file__).resolve().with_name("web.html")


class Word(TypedDict):
    """What the owner says about a decision on the page."""

    review: NotRequired[Review]
    note: NotRequired[str | None]
    elaborate: NotRequired[bool]


class Server(ThreadingHTTPServer):
    def __init__(self, decisions: Decisions, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.decisions = decisions

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def run(self, open_browser: bool) -> None:
        print(f"nock: {self.address} (Ctrl-C to stop)", flush=True)
        if open_browser:
            webbrowser.open(self.address)
        try:
            self.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.server_close()


class Handler(BaseHTTPRequestHandler):
    """`GET /` the page, `GET /decisions` every decision with the tags in use,
    `POST /decisions/N` the owner's word on one."""

    @property
    def decisions(self) -> Decisions:
        assert isinstance(self.server, Server)
        return self.server.decisions

    def do_GET(self) -> None:
        if self.path == "/":
            self.send(HTTPStatus.OK, PAGE.read_bytes(), "text/html")
        elif self.path == "/decisions":
            decisions = self.decisions
            self.send_json(HTTPStatus.OK, {"decisions": decisions.all(), "tags": decisions.tags()})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such page"})

    def do_POST(self) -> None:
        number = self.path.removeprefix("/decisions/")
        if not number.isdigit():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "no such decision"})
            return
        decisions = self.decisions
        try:
            word = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            validate(word, schema_of(Word))
            change = Change(number=int(number), **word)
            decision, _ = decisions.edit(change)
        except json.JSONDecodeError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        except Error as error:
            status = (
                HTTPStatus.NOT_FOUND if isinstance(error, NotFoundError) else HTTPStatus.BAD_REQUEST
            )
            self.send_json(status, {"error": str(error)})
            return
        if word.get("elaborate"):
            decisions.elaborate_in_background(int(number))
        self.send_json(HTTPStatus.OK, decision)

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
