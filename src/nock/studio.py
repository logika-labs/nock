"""The owner's page (`nock studio`): one local server, a tab for each thing
nock keeps for the owner — today the decisions and questions agents recorded,
reviewed in place. Local, and only while `nock studio` runs.

A tab is a `Tab` in `TABS`: its name is its address on the page (`#NAME`) and
its routes on the server (`/NAME/…`); its page is the fragment
`pages/NAME.html` (markup, style and a script that registers it with the
studio, `pages/studio.html`)."""

from __future__ import annotations

import html
import json
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from nock.commands import schema_of
from nock.decisions import Change, Decisions, Review
from nock.errors import Error, NotFoundError
from nock.project import Project
from nock.schema import validate

PAGES = Path(__file__).resolve().with_name("pages")
SHELL = PAGES / "studio.html"


class Tab:
    """One tab: what it answers on `GET /NAME/ROUTE` and `POST /NAME/ROUTE`
    (JSON both ways; a nock `Error` is the HTTP error)."""

    name = ""
    title = ""

    def __init__(self, project: Project) -> None:
        self.project = project

    def fragment(self) -> str:
        return (PAGES / f"{self.name}.html").read_text()

    def get(self, route: str) -> Any:
        raise NotFoundError("no such page")

    def post(self, route: str, body: Any) -> Any:
        raise NotFoundError("no such page")


class Word(TypedDict):
    """What the owner says about a decision on the page."""

    review: NotRequired[Review]
    note: NotRequired[str | None]
    elaborate: NotRequired[bool]


class DecisionsTab(Tab):
    """`GET /decisions` every decision with the tags in use, `POST
    /decisions/N` the owner's word on one: a review, a note, or elaborate."""

    name = "decisions"
    title = "Decisions"

    def __init__(self, project: Project) -> None:
        super().__init__(project)
        self.decisions = Decisions(project)

    def get(self, route: str) -> Any:
        if route:
            raise NotFoundError("no such page")
        return {"decisions": self.decisions.all(), "tags": self.decisions.tags()}

    def post(self, route: str, body: Any) -> Any:
        if not route.isdigit():
            raise NotFoundError("no such decision")
        validate(body, schema_of(Word))
        decision, _ = self.decisions.edit(Change(number=int(route), **body))
        if body.get("elaborate"):
            self.decisions.elaborate_in_background(int(route))
        return decision


TABS: tuple[type[Tab], ...] = (DecisionsTab,)


class Studio(ThreadingHTTPServer):
    def __init__(self, project: Project, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.tabs = {tab.name: tab(project) for tab in TABS}

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def page(self) -> bytes:
        """The shell with every tab's link and panel in it, the first tab open."""
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
            shell.replace("<!-- nock:tabs -->", links)
            .replace("<!-- nock:panels -->", panels)
            .encode()
        )

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
    """`GET /` the page; `/NAME/ROUTE` goes to the tab named."""

    @property
    def studio(self) -> Studio:
        assert isinstance(self.server, Studio)
        return self.server

    def do_GET(self) -> None:
        if self.path == "/":
            self.send(HTTPStatus.OK, self.studio.page(), "text/html")
            return
        self.answer(lambda tab, route: tab.get(route))

    def do_POST(self) -> None:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except json.JSONDecodeError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.answer(lambda tab, route: tab.post(route, body))

    def answer(self, call: Callable[[Tab, str], Any]) -> None:
        name, _, route = self.path.split("?")[0].removeprefix("/").partition("/")
        tab = self.studio.tabs.get(name)
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
        self.send_json(HTTPStatus.OK, value)

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
