"""The owner's page (`nock studio`): one local server, a tab for each thing
nock keeps for the owner: the decisions agents recorded,
reviewed in place, and the evaluations, read from their files. Local, and only while `nock studio` runs.

A tab is a `Tab` in `TABS`: its name is its address on the page (`#NAME`) and
its routes on the server (`/NAME/…`); its page is the fragment
`pages/NAME.html` (markup, style and a script that registers it with the
studio, `pages/studio.html`, whose look is `pages/studio.css`). While nobody has answered whether nock shares
its usage report, the page asks under the title; the settings in the menu
change the answer later; `POST /usage` records either."""

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
from nock.comparison import Comparison, Query
from nock.decisions import Change, Decisions, Review
from nock.errors import Error, NotFoundError
from nock.evaluation import Evaluations, Run
from nock.project import Project
from nock.results import Results
from nock.schema import validate
from nock.usage import QUESTION, Answer, Usage, sharing

PAGES = Path(__file__).resolve().with_name("pages")
SHELL = PAGES / "studio.html"
LOOK = PAGES / "studio.css"


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


class Draft(TypedDict):
    """A dry run asked for on the page: its targets and budget, nothing run."""

    targets: NotRequired[list[str]]
    budget: NotRequired[float]


class EvalsTab(Tab):
    """`GET /evals` every scenario as Snakemake and its result files have it —
    the rule graph, each rule's outputs current, stale and failed, their
    numbers; `POST /evals/NAME/dry` what a run would compute and restore, and
    why; `POST /evals/NAME/compare` a comparison. Nothing here runs a step or
    writes a file."""

    name = "evals"
    title = "Evaluations"

    def __init__(self, project: Project) -> None:
        super().__init__(project)
        self.evaluations = Evaluations(project)

    def get(self, route: str) -> Any:
        if route:
            raise NotFoundError("no such page")
        return {"scenarios": [self.page(name) for name in self.evaluations.names()]}

    def page(self, name: str) -> dict[str, Any]:
        scenario = self.evaluations.scenario(name)
        try:
            graph = scenario.rulegraph()
            outputs, metrics = Results(scenario).run(
                [
                    "SELECT rule, path, parameters, state, why, cost_usd, seconds, error"
                    " FROM outputs ORDER BY rule, path",
                    "SELECT path, metric, value FROM metrics",
                ]
            )
        except Error as error:
            return {"name": name, "problem": str(error)}
        numbers: dict[str, dict[str, float]] = {}
        for row in metrics.get("rows", []):
            numbers.setdefault(row["path"], {})[row["metric"]] = row["value"]
        return {
            "name": name,
            "snakefile": (scenario.directory / "Snakefile").read_text(),
            "graph": graph,
            "outputs": [
                {**row, "metrics": numbers.get(row["path"], {})} for row in outputs.get("rows", [])
            ],
        }

    def post(self, route: str, body: Any) -> Any:
        name, _, action = route.partition("/")
        if name not in self.evaluations.names():
            raise NotFoundError(f"no scenario {name}")
        if action == "dry":
            validate(body, schema_of(Draft))
            plan = Run(self.evaluations.scenario(name), body.get("targets", []), body.get("budget"))
            refused = plan.refusal()
            return {
                "jobs": plan.lines(),
                "summary": plan.summary(),
                **({"refused": refused} if refused else {}),
            }
        if action == "compare":
            validate(body, schema_of(Query))
            return Comparison(self.project).compare(Query(**{**body, "scenario": name}))
        raise NotFoundError("no such page")


TABS: tuple[type[Tab], ...] = (DecisionsTab, EvalsTab)


class Choice(TypedDict):
    """The owner's answer on the page to whether nock shares its usage report."""

    share: bool


class Studio(ThreadingHTTPServer):
    def __init__(self, project: Project, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.project = project
        self.tabs = {tab.name: tab(project) for tab in TABS}

    def question(self) -> str:
        """Under the title while nobody has answered: a slim line asking, with
        Share and Don't share; what the report holds is in the settings."""
        if sharing(self.project)[0] is not Answer.UNANSWERED:
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
        answer = sharing(self.project)[0]
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
            '          <div class="setting"><span id="share-label">Share usage reports</span>'
            f' <span class="state" id="share-state">{said}</span>'
            ' <button type="button" class="switch" role="switch" id="share-switch"'
            f' aria-checked="{str(answer is Answer.YES).lower()}" aria-labelledby="share-label">'
            "<span></span></button></div>\n"
            '          <p class="hint">Weekly at most, counts and categories only: never code,'
            " paths, names or what decisions say.</p>\n"
            f"          <details><summary>What it holds</summary><p>{html.escape(QUESTION)}</p></details>\n"
            "        </div>\n"
            "      </div>"
        )

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
        if open_browser:
            webbrowser.open(self.address)
        try:
            self.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.server_close()


class Handler(BaseHTTPRequestHandler):
    """`GET /` the page; `POST /usage` the owner's answer on sharing; `/NAME/ROUTE`
    goes to the tab named."""

    @property
    def studio(self) -> Studio:
        assert isinstance(self.server, Studio)
        return self.server

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/":
            self.send(HTTPStatus.OK, self.studio.page(), "text/html")
            return
        self.answer(lambda tab, route: tab.get(route))

    def do_POST(self) -> None:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except json.JSONDecodeError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if self.path == "/usage":
            try:
                self.send_json(HTTPStatus.OK, self.studio.answer(body))
            except Error as error:
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
