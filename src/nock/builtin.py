"""nock's own commands and checks, registered through the same decorators a
project's tools use — they are tools too."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Annotated, Any

from nock.checks import Checks
from nock.commands import Group, Option
from nock.configuration import Confirm, scope_of, with_key
from nock.consult import Consultant
from nock.docs import Docs
from nock.errors import Error, ExitCode, Failed, UsageError
from nock.fixtures import Shell
from nock.generators import Catalogs, Generators
from nock.harnesses import NATIVE_EVENTS
from nock.inbox import Inbox
from nock.processes import Output
from nock.project import Project
from nock.reflect import FIT, Reflection, tool_rows
from nock.render import Problem
from nock.reports import Reports
from nock.rounds import named, protocols
from nock.rounds import submit as submit_round
from nock.sessions import Sessions
from nock.setup import (
    PERMISSION,
    Installer,
    Upgrader,
    ours,
    permission_rules,
    wanted_permissions,
    wired_events,
)
from nock.share import Request as ShareRequest
from nock.share import Sharing
from nock.shared import SETTINGS, Shared, by_for
from nock.status import Standing
from nock.studio import Studio
from nock.telemetry import UNRECORDED_VARIABLE
from nock.tools import Tool, check, command
from nock.topics import (
    SHORT,
    Topics,
)
from nock.usage import QUESTION, Answer, Moment, Usage, sharing
from nock.utils import payload

EXAMPLE_DEADLINE = 300


# --- working -------------------------------------------------------------------


@command(name="check")
def check_command(
    project: Project,
    names: list[str] | None = None,
    *,
    fix: Annotated[bool, Option(help="Run each command check's `fix` first.")] = False,
    all: Annotated[
        bool,
        Option(help="Every check, not only those the branch's changes can affect: the full gate."),
    ] = False,
) -> None:
    """Run the checks the branch's changes (since the main branch, committed or
    not) can affect, by each check's `paths`; `--all` runs every one, and
    names run exactly those. Prints nothing when all pass. Exit 1: the code is
    wrong. 42 (or 54/55): the machine is."""
    verdict = Checks(project).run(names or None, fix=fix, changed=not all and not names)
    if verdict.exit_code == ExitCode.SUCCESS:
        return
    problems = verdict.problems()
    if verdict.exit_code == ExitCode.SUBJECT_FAILED:
        raise Failed(f"{len(problems)} problem(s)", problems)
    raise Error.for_exit_code(
        verdict.exit_code, "a check could not run — the machine, not the code", problems
    )


@command(name="run", rest="command")
def run_command(
    sh: Shell,
    command: list[str],
    *,
    deadline: Annotated[float | None, Option(help="Kill it after this many seconds.")] = None,
    silence: Annotated[
        float | None, Option(help="Kill it after this many seconds without output.")
    ] = None,
) -> Output:
    """Run any command supervised: bounded, logged, its output condensed (no
    colors or progress bars, repeated lines folded, long output cut to the
    end with the log's path). Exits with the command's code. For anything
    noisy or long: `.nock/nock run -- pytest -x`."""
    if not command:
        raise UsageError("nothing to run: `.nock/nock run -- COMMAND …`")
    return sh(command, check=False, deadline=deadline, silence=silence)


@command(examples=["tools", "tools.caching fixtures"])
def docs(terms: list[str] | None = None) -> str | dict[str, str]:
    """nock's documentation, a short article per term: how to write a tool, a
    check, a hook or a generator, and how decisions, consultation and
    reflection work. With no term, the terms; with several, each in turn."""
    documentation = Docs()
    if not terms:
        return documentation.index()
    return documentation.read(terms)


# --- telemetry -------------------------------------------------------------------


@command
def query(
    project: Project,
    what: str,
    *,
    tool: Annotated[str | None, Option(help="calls: only this command's.")] = None,
    failed: Annotated[bool, Option(help="calls: only those that did not exit 0.")] = False,
    limit: Annotated[int | None, Option(help="calls, sessions: how many.")] = None,
    since: Annotated[
        str | None, Option(help="stats: an ISO date; the default is the last reflection round.")
    ] = None,
) -> list[dict[str, Any]]:
    """Read the telemetry: WHAT is read-only SQL over its tables (calls, runs,
    sessions, prompts, events — a round's material explains them), or one of
    its views: `calls`, recent calls to nock, newest first; `stats`, each
    command's use since the last round; `sessions`, recent sessions with their
    role, tokens and cost at API prices. The transcripts are read up to now
    first."""
    if what == "calls":
        return calls(project, tool=tool, failed=failed, limit=limit or 20)
    if what == "stats":
        return stats(project, since=since)
    Sessions(project).catch_up()
    if what == "sessions":
        return sessions(project, limit=limit or 15)
    return project.store.query(what)


def calls(project: Project, *, tool: str | None, failed: bool, limit: int) -> list[dict[str, Any]]:
    """Recent calls to nock, newest first: how each was called and how it ended."""
    query = (
        "SELECT id, started, tool, arguments, exit_code, duration, output_bytes, error FROM calls"
    )
    conditions, parameters = [], []
    if tool:
        conditions.append("tool = ?")
        parameters.append(tool)
    if failed:
        conditions.append("exit_code != 0")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    rows = project.store.rows(query + " ORDER BY id DESC LIMIT ?", (*parameters, limit))
    return [
        {
            "id": row["id"],
            "started": (row["started"] or "")[:16].replace("T", " "),
            "call": " ".join([row["tool"], *map(shlex.quote, json_list(row["arguments"]))]),
            "exit": row["exit_code"],
            "seconds": row["duration"],
            "printed": row["output_bytes"],
            "error": row["error"],
        }
        for row in rows
    ]


def json_list(text: str | None) -> list[str]:
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def stats(project: Project, *, since: str | None) -> list[dict[str, Any]]:
    """Each command's use since the last reflection round: calls, failures,
    duration, how much it printed."""
    window = since if since is not None else Reflection(project).window().since
    keys = (
        "tool",
        "calls",
        "sessions",
        "failed",
        "refused",
        "broke",
        "median_seconds",
        "mean_bytes",
        "capped",
        "cached",
    )
    return [
        {key: row[key] for key in keys}
        for row in tool_rows(project, window)
        if row["calls"] or row["source"] != "nock"
    ]


def sessions(project: Project, *, limit: int) -> list[dict[str, Any]]:
    """Recent Claude Code sessions in this project: what each was, its role
    (interactive, headless or the one nock dispatched it as), its tokens and
    what they would cost at API prices (unknown when its model is unpriced)."""
    rows = project.store.rows("SELECT * FROM sessions ORDER BY started DESC LIMIT ?", (limit,))
    return [
        {
            "started": (row["started"] or "")[:16].replace("T", " "),
            "id": row["id"][:8],
            "role": row["role"],
            "title": (row["title"] or "")[:70],
            "prompts": row["prompts"],
            "tokens": sum(
                row[key] or 0
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                )
            ),
            "api_cost": round(row["cost"], 2) if row["cost"] is not None else "unknown",
        }
        for row in rows
    ]


# --- where things stand ------------------------------------------------------------


@command
def status(project: Project) -> dict[str, Any]:
    """Where the project stands with nock: whether a reflection round is due,
    the open decisions by topic, what waits on an agent (threads where the
    owner wrote last, rejected decisions, and `nock inbox` by kind), changes
    in `.nock/shared/` that don't hold, a round summary not yet shared,
    whether a newer nock is out, and its nudges for the session asking: files
    changed with no consultation, commits with nothing recorded in the
    topics, generated files edited by hand."""
    return Standing(project).collect(nudging=True)


@command
def studio(
    project: Project,
    *,
    port: Annotated[
        int | None, Option(help="The port: `studio.port` (8765) by default; 0 picks a free one.")
    ] = None,
    open: Annotated[bool, Option(help="Open it in the browser.")] = False,
) -> None:
    """Serve the owner's page, the topics with their decisions and assets,
    until stopped."""
    if Usage(project).ask(Moment.STUDIO):
        print(f"nock: {QUESTION} The page asks too; answer there.", flush=True)
    Studio(project, port if port is not None else project.configuration.get("studio.port")).run(
        open
    )


# --- the owner's first word -----------------------------------------------------------


def ask(project: Project, result: dict[str, Any], moment: Moment) -> None:
    """Whether nock may share its usage report, asked of the owner the first
    time they engage with it here, while nobody has answered."""
    question = Usage(project).ask(moment)
    if question:
        result["ask_the_owner"] = question


# --- consulting -----------------------------------------------------------------------


@command
def consult(
    project: Project,
    question: str | None = None,
    *,
    context: Annotated[str | None, Option(help="What you know already.")] = None,
    submit: Annotated[
        str | None, Option(help="The consultant's answer, as JSON; only the consultant's.")
    ] = None,
) -> str:
    """Have a fresh agent read the project and answer: what bears on a change
    you are about to make (when you are unsure, or it touches something with
    history), or a question about the topics (the studio's Ask); waits for it.
    `--submit JSON` is the consultant's own answer."""
    consultant = Consultant(project)
    if submit is not None:
        return consultant.submit(payload(submit))
    if not question or not question.strip():
        raise UsageError('say what you are about to do, or ask: `.nock/nock consult "…"`')
    return consultant.consult({"intent": question.strip(), "context": (context or "").strip()})


# --- the topics: found, and what the owner said --------------------------------------


@command
def search(
    project: Project,
    query: str,
    *,
    topic: Annotated[str | None, Option(help="Only this topic's decisions.")] = None,
) -> dict[str, Any]:
    """The topics and decisions matching QUERY, the strongest first: what holds
    every word, then all but one, and so on. Each with its view, the topic's
    page in `.nock/local/views/` to read."""
    topics = Topics(project)
    views = project.local / "views"
    names = [] if topic else topics.search_topics(query)
    items = topics.search_items(query, topic)
    return {
        "topics": [{"name": name, "view": str(views / f"{name}.md")} for name in names[:SHORT]],
        "decisions": [
            {
                "ref": item["ref"],
                "title": item["title"],
                "verdict": item["verdict"],
                "view": str(views / f"{item['topic']}.md"),
            }
            for item in items[:SHORT]
        ],
    }


@command
def inbox(
    project: Project,
    *,
    wait: Annotated[bool, Option(help="Wait until there is something.")] = False,
    deadline: Annotated[
        float | None, Option(help="Seconds to wait at most (`inbox.wait`, 540).")
    ] = None,
    all: Annotated[bool, Option(help="What you were shown already, too.")] = False,
) -> list[dict[str, Any]]:
    """What the owner said that no agent has addressed and you have not been
    shown: a message sent with Address now, the global chat, comments waiting
    in threads, verdicts — the most urgent first, yours first within each.
    `--wait` blocks until there is something (verdicts and comments once the
    owner has been quiet a minute, so a triage lands as one batch)."""
    found = Inbox(project)
    if wait:
        entries = found.wait(
            float(deadline if deadline is not None else project.configuration.get("inbox.wait")),
            float(project.configuration.get("inbox.settle")),
        )
    else:
        entries = found.entries(every=all)
    found.mark_shown(entries)
    return entries


# --- settings ------------------------------------------------------------------------


@command
def config(
    project: Project,
    key: str | None = None,
    value: str | None = None,
    *,
    local: Annotated[bool, Option(help="This machine's config, whatever the key.")] = False,
) -> Any:
    """Settings: bare, those nock writes, with their values and where each is
    kept; KEY, its value (`share`: also when it was asked and what a report
    carries); KEY VALUE, set it — the team's in `.nock/shared/settings.toml`
    (committed), the machine's in `.nock/local/config.toml`."""
    configuration = project.configuration
    if key is None:
        return [
            {"key": name, "value": configuration.get(name), "kept": SCOPE_FILES[scope]}
            for name, scope in sorted(writable_keys(configuration).items())
        ]
    scope = scope_of(key)
    if value is None:
        if key == "share":
            return Usage(project).standing()
        return {"key": key, "value": configuration.get(key)}
    if scope is None:
        raise UsageError(
            f"{key}: not a setting `nock config` writes — the code's settings are in"
            " .nock/config.toml, written by hand (`.nock/nock docs configuration`)"
        )
    parsed = toml_value(value)
    if key == "share":
        if not isinstance(parsed, bool):
            raise UsageError("share is true or false")
        return Usage(project).answer(parsed, "command")
    path = (
        project.local / "config.toml"
        if local or scope == "machine"
        else (project.root / ".nock" / "shared" / SETTINGS)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(with_key(path.read_text() if path.is_file() else "", key, parsed))
    if not local and scope == "team":
        Shared(project).settle(by_for(project), only=[path])
    project.__dict__.pop("configuration", None)
    return {"key": key, "value": project.configuration.get(key), "kept": str(path)}


SCOPE_FILES = {"team": ".nock/shared/settings.toml", "machine": ".nock/local/config.toml"}


def writable_keys(configuration: Any) -> dict[str, str]:
    """Every setting `nock config` writes, by its dotted key."""
    found: dict[str, str] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for name, inner in value.items():
                walk(f"{prefix}.{name}" if prefix else name, inner)
            return
        scope = scope_of(prefix)
        if scope:
            found[prefix] = scope

    walk("", configuration.values)
    found.setdefault("share", "team")
    return found


def toml_value(text: str) -> Any:
    """A value as TOML reads it — `true`, `8766`, `"x"` — else the text itself."""
    try:
        return tomllib.loads(f"value = {text}")["value"]
    except tomllib.TOMLDecodeError:
        return text


# --- reflection ---------------------------------------------------------------------


@command(name="reflect")
def reflect(
    project: Project,
    name: str | None = None,
    *,
    submit: Annotated[
        str | None, Option(help="A round's result, as JSON: its protocol, summary and changes.")
    ] = None,
) -> Any:
    """Reflection rounds. Bare, the catalogue: every protocol, whether it can
    run here and is adopted, when it is due and why, its last round and its
    skill. NAME starts a round (`nock.toolbox`), or every adopted one of a
    namespace at once (`nock`, `logika`), or picks up the one under way: what
    its lead does, its agents and their material, the files to write, the
    submit. `--submit JSON` checks a round's result and records it
    (`nock docs reflection.record`)."""
    if submit is not None:
        result = submit_round(project, payload(submit))
        shared = share_with_makers(project, result)
        if shared:
            result["shared"] = shared
        ask(project, result, Moment.ROUND)
        return result
    if name is None:
        return [protocol.standing() for protocol in protocols(project)]
    begun = [protocol.start() for protocol in named(project, name)]
    result: dict[str, Any] = (
        begun[0]
        if len(begun) == 1
        else {
            "do": f"{len(begun)} rounds at once: dispatch all their agents in one message, then"
            " write each round's files and submit each",
            "rounds": begun,
        }
    )
    ask(project, result, Moment.ROUND)
    return result


def share_with_makers(project: Project, result: dict[str, Any]) -> dict[str, Any] | None:
    """A round whose protocol names a shareable summary, sent to nock's
    makers when the owner said yes: vetted first, as `nock share` does."""
    if result["protocol"] != FIT or sharing(project) is not Answer.YES:
        return None
    try:
        return Sharing(project).share({"round": result["round"], "send": True})
    except Error as error:
        # The round stands recorded; its summary waits for `nock share`.
        return {"not_sent": str(error), "send": "`.nock/nock share` once that is fixed"}


@command(confirm=True)
def share(
    project: Project,
    request: ShareRequest = {},  # noqa: B006
) -> dict[str, Any]:
    """A round's summary as it would be shared, and where it would go: a fresh
    agent vets it first, rewriting whatever would identify the project. With
    `send`, send it to nock's makers, who alone read it. Send only when the
    owner says so."""
    return Sharing(project).share(request)


@command(confirm=True)
def report(
    project: Project,
    text: str | None = None,
    *,
    yes: Annotated[
        bool, Option(help="Send without asking: only on the user's explicit go-ahead.")
    ] = False,
) -> dict[str, Any]:
    """Send nock's makers what the user wrote — something nock lacks, or
    something broken or confusing — with nock's version and the platform,
    nothing from the repository. The text is the argument, or stdin. On a
    terminal it shows what would go and asks; with no terminal it sends only
    with --yes, which an agent passes only when the user said to send it.
    Answers the makers' reference id."""
    return Reports(project).report(text, yes)


# --- generators -----------------------------------------------------------------------


@command(name="gen")
def gen(
    project: Project,
    *,
    list: Annotated[
        bool, Option(help="Only list the generated files, and which are out of step.")
    ] = False,
) -> list[Any]:
    """Render every generated file and write those out of step; `--list`
    shows them all and changes nothing."""
    generators = Generators(project)
    if list:
        stale = set(generators.drifted(project.here))
        found: list[Any] = [
            {"file": binding.file, "from": catalog.name, "stale": binding.file in stale}
            for catalog in Catalogs(project).all()
            for binding in catalog.bindings()
        ]
        found += [
            {"file": entry.path, "from": entry.name, "stale": entry.path in stale}
            for entry in project.registry.generators
        ]
        return found
    return [str(path.relative_to(project.here)) for path in generators.write()]


# --- setup ------------------------------------------------------------------------------


@command(confirm=True)
def init(
    *, source: Annotated[str | None, Option(help="Where upgrades come from.")] = None
) -> list[str]:
    """Install nock into this repository — vendored into `.nock/`, wired into
    each agent harness it uses (Claude Code always; Codex and Cursor when the
    repository or PATH has them) — or re-wire it; says what it found, exactly
    what it changed, and the next step. Safe to run again."""
    return Installer(Path.cwd()).install(source)


@command(confirm=True)
def upgrade(
    project: Project,
    *,
    source: Annotated[
        str | None, Option(help="`pypi` (the default), a git URL or a local checkout.")
    ] = None,
    force: Annotated[bool, Option(help="Replace the core, losing local edits to it.")] = False,
    only_clean: Annotated[
        bool, Option(help="Upgrade only when the merge is clean; otherwise change nothing.")
    ] = False,
) -> list[str]:
    """Upgrade the vendored core to the latest release, keeping local edits to
    it (a three-way merge); then the upgraded core re-wires the project —
    primer, hooks, skills — as `nock init` does. A session start runs it with
    `--only-clean` when a newer release is out, unless `upgrade.auto` is off."""
    report = Upgrader(project).upgrade(source, force, only_clean)
    lines = report.lines()
    if report.conflicts:
        return [*lines, "resolve the conflicts, then `.nock/nock init` re-wires the project"]
    rewired = subprocess.run(
        [str(project.here / ".nock" / "nock"), "init"],
        cwd=project.here,
        capture_output=True,
        text=True,
        # The core just merged re-wires, not a checkout NOCK_SOURCE points at.
        env={name: value for name, value in os.environ.items() if name != "NOCK_SOURCE"},
    )
    if rewired.returncode != 0:
        raise Failed(
            "upgraded, but the new core could not re-wire the project",
            rewired.stderr.strip()[-600:],
        )
    return [*lines, *rewired.stdout.strip().splitlines()]


# --- nock's own checks ---------------------------------------------------------------------


@check(name="nock-tools", paths=[".nock/**"])
def tools_load_and_examples_run(project: Project, root: Path) -> list[str]:
    """Every tool loads, and every example a tool gives runs without being
    called wrong or breaking. A `confirm=True` tool's examples are only
    parsed against its arguments, never run: running them would set off
    what only the owner may, without asking."""
    problems = [f"does not load — {failure}" for failure in project.registry.failures]
    environment = {
        **os.environ,
        UNRECORDED_VARIABLE: "1",
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
    }
    for tool in project.registry.project_tools():
        try:
            tool.command.usage()
        except Exception as error:
            problems.append(
                f"{tool.command.path} ({tool.source}): its signature does not make a command: {error}"
            )
            continue
        for example in tool.command.examples:
            arguments = [*tool.command.path.split(), *shlex.split(example)]
            if tool.confirm:
                problems += example_parse_problems(tool, arguments)
                continue
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "nock", *arguments],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=EXAMPLE_DEADLINE,
                )
            except subprocess.TimeoutExpired:
                problems.append(
                    f"`{' '.join(arguments)}` ({tool.source}) ran past {EXAMPLE_DEADLINE}s"
                )
                continue
            if result.returncode >= 40:
                problems.append(
                    f"`{' '.join(arguments)}` ({tool.source}) exited {result.returncode}: {result.stderr.strip()[-600:]}"
                )
    return problems


def example_parse_problems(tool: Tool, arguments: list[str]) -> list[str]:
    """Whether an example of a tool that is never run calls it right."""
    group = Group("nock", "")
    group.add(tool.command)
    try:
        _, namespace = group.parse(arguments)
        tool.command.values(namespace)
    except Error as error:
        return [f"`{' '.join(arguments)}` ({tool.source}) is called wrong: {error}"]
    return []


@check(name="nock-generators")
def generated_files_in_step(project: Project, root: Path) -> list[str]:
    """Every catalog's entries fit its schema, and no generated file has drifted."""
    problems = []
    for catalog in Catalogs(project).all():
        problems += catalog.problems()
    problems += [
        f"{path} has drifted from its generator — `.nock/nock gen`"
        for path in Generators(project).drifted(root)
    ]
    return problems


@check(name="nock-map", paths=[".nock/**"])
def map_holds(project: Project) -> list[Problem]:
    """Every item the map of topics cites exists."""
    return Topics(project).citation_problems()


@check(name="nock-share", paths=[".nock/**"])
def summary_names_nothing(project: Project) -> list[Problem]:
    """The round's shareable summary names nothing of the project: no paths,
    file names, the project's or its people's names, addresses or links."""
    rounds = Reflection(project).rounds
    name = rounds.current() or ((rounds.last() or {}).get("round"))
    return Sharing(project).problems(name) if name else []


@check(name="nock-wiring", paths=[".nock/**", ".claude/**"])
def hooks_wired(project: Project) -> list[str]:
    """Every event a hook listens to is wired into Claude Code; Claude Code
    asks the owner before an agent runs a command that needs their word
    (unless `permissions.confirm` is "allow"), allows each of the toolbox's
    other commands, and allows nothing broader."""
    wired = wired_events(project.here)
    asked = permission_rules(project.here, "ask")
    allowed = permission_rules(project.here, "allow")
    wanted, wanted_asked = wanted_permissions(project)
    return (
        [
            f"a hook listens to {entry.event} ({entry.source}) but Claude Code does not send it — `.nock/nock init` wires it"
            for entry in project.registry.hooks
            if NATIVE_EVENTS[entry.event] not in wired
        ]
        + [
            f"`{tool.command.path}` needs the owner's word ({tool.source}) but Claude Code would run it unasked — `.nock/nock init` wires it"
            for tool in project.registry.tools
            if PERMISSION.format(path=tool.command.path) in wanted_asked
            and PERMISSION.format(path=tool.command.path) not in asked
        ]
        + [
            f'Claude Code asks before `{rule.removeprefix("Bash(.nock/nock ").removesuffix(":*)")}` although `permissions.confirm` is "allow" — `.nock/nock init` allows it'
            for rule in sorted(asked)
            if ours(rule) and project.configuration.confirm() is Confirm.ALLOW
        ]
        + [
            f"`{rule.removeprefix('Bash(').removesuffix(':*)')}` is not allowed yet, so Claude Code asks before each call — `.nock/nock init` allows it (it asks the owner)"
            for rule in wanted
            if rule not in allowed
        ]
    )
