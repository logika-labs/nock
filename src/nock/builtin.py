"""nock's own commands and checks, registered through the same decorators a
project's tools use — they are tools too."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, NotRequired, TypedDict

from nock.checks import Checks
from nock.commands import Option
from nock.consolidate import Consolidation
from nock.consult import Consultant, Consultation
from nock.errors import Error, ExitCode, Failed, UsageError
from nock.fixtures import Shell
from nock.generators import Catalogs, Generators
from nock.git import Git
from nock.processes import Output
from nock.project import Project
from nock.questions import Draft, Lesson, Questions, Server, State, said
from nock.reflect import Record, Reflection, tool_rows
from nock.render import Problem
from nock.schema import check_schema
from nock.sessions import Sessions
from nock.setup import Installer, Upgrader, wired_events
from nock.telemetry import UNRECORDED_VARIABLE
from nock.templates import SYNTAX, Library
from nock.tools import NATIVE_EVENTS, check, command

BRIEFS = Path(__file__).resolve().parent / "briefs"
EXAMPLE_DEADLINE = 300


# --- working -------------------------------------------------------------------


@command(name="check")
def check_command(
    project: Project,
    names: list[str] | None = None,
    *,
    fix: Annotated[bool, Option(help="Run each command check's `fix` first.")] = False,
) -> None:
    """Run the checks — all of them, or those named; prints nothing when all pass.
    Exit 1: the code is wrong. 42 (or 54/55): the machine is."""
    verdict = Checks(project).run(names or None, fix=fix)
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


@command
def guide() -> str:
    """How to write a tool, a check, a hook or a generator."""
    return Library(BRIEFS).render("_framework.md").rstrip()


# --- telemetry -------------------------------------------------------------------


@command
def calls(
    project: Project,
    *,
    tool: Annotated[str | None, Option(help="Only this command's calls.")] = None,
    failed: Annotated[bool, Option(help="Only calls that did not exit 0.")] = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
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


@command
def stats(
    project: Project,
    *,
    since: Annotated[
        str | None, Option(help="An ISO date; the default is the last reflection round.")
    ] = None,
) -> list[dict[str, Any]]:
    """Each command's use since the last reflection round: calls, failures,
    duration, how much it printed."""
    window = since if since is not None else Reflection(project).window().since
    keys = (
        "tool",
        "calls",
        "sessions",
        "said_no",
        "usage_errors",
        "machine_errors",
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


@command
def query(project: Project, sql: str) -> list[dict[str, Any]]:
    """Read the telemetry with SQL (read-only). Tables: calls, runs, sessions,
    prompts, events — `.nock/nock reflect material` explains them."""
    return project.store.query(sql)


@command
def sessions(project: Project, *, limit: int = 15) -> list[dict[str, Any]]:
    """Recent Claude Code sessions in this project: what each was, what it cost."""
    Sessions(project).catch_up()
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
            "cost": round(row["cost"], 2) if row["cost"] else None,
        }
        for row in rows
    ]


# --- reflection ---------------------------------------------------------------------


@command(name="due", group="reflect")
def reflect_due(project: Project) -> str | bool:
    """Whether a reflection round is due; exit 1 when it is not."""
    return Reflection(project).due() or False


@command(name="material", group="reflect")
def reflect_material(project: Project) -> str:
    """What a round reads: the work, the telemetry, the last round's expectations."""
    return Reflection(project).material()


@command(name="record", group="reflect")
def reflect_record(project: Project, record: Record) -> str:
    """Record the round, at its end (the `/reflect` skill): what changed, why,
    and what each change should do by the next round. Commit it with the work."""
    path = Reflection(project).record(record)
    return f"recorded {path.relative_to(project.here)}"


# --- questions ---------------------------------------------------------------------


@command
def ask(project: Project, question: Draft) -> list[str]:
    """Ask the owner what the code, the documents and earlier answers cannot
    settle — a decision that is theirs to make. Meanwhile take the option you
    recommend, say so in your work, and keep going; the owner answers on
    `.nock/nock questions page`, and the answer reaches this session."""
    number, problem = Questions(project).ask(question)
    return [f"asked question {number}", *([problem] if problem else [])]


@command(name="list", group="questions")
def questions_list(
    project: Project,
    *,
    state: Annotated[
        State | None, Option(help="Only questions in this state; the default is all but closed.")
    ] = None,
) -> list[dict[str, Any]]:
    """The questions, and where each stands: open waits on the owner, pending
    on an agent."""
    return [
        {
            "number": question["number"],
            "state": question["state"],
            "priority": question["priority"],
            "title": question["title"],
            "owner": said(question) if question["state"] == State.PENDING else None,
        }
        for question in Questions(project).all()
        if (question["state"] == state if state else question["state"] != State.CLOSED)
    ]


@command(name="show", group="questions")
def questions_show(project: Project, number: int) -> dict[str, Any]:
    """One question in full: its context, options, and the owner's input or the answer."""
    return Questions(project).get(number)


@command(name="answer", group="questions")
def questions_answer(
    project: Project,
    number: int,
    answer: str,
    *,
    touches: Annotated[
        list[str] | None, Option(help="A file the decision governs, as a path or glob (repeats).")
    ] = None,
    supersedes: Annotated[
        list[int] | None, Option(help="A decided question this one overturns (repeats).")
    ] = None,
) -> list[str]:
    """Close a question: ANSWER is the decision in its own words, the owner's
    comment folded in, so that it reads on its own later. Name the files it
    governs, so that an edit to one shows it, and what it overturns. Then act
    on it, and commit what it changed with the work."""
    problem = Questions(project).answer(number, answer, touches, supersedes)
    return [f"answered question {number}", *([problem] if problem else [])]


@command(name="record", group="questions")
def questions_record(project: Project, lesson: Lesson) -> list[str]:
    """Record a lesson: what the work taught, as a question decided at once,
    so that the map can cite it. Part of a consolidation round."""
    number, problem = Questions(project).record(lesson)
    return [f"recorded lesson {number}", *([problem] if problem else [])]


@command(name="rewrite", group="questions")
def questions_rewrite(project: Project, number: int, question: Draft) -> list[str]:
    """Say a question again, with what the owner found missing: its context,
    options and recommendation rewritten. It is open again."""
    problem = Questions(project).rewrite(number, question)
    return [f"rewrote question {number}", *([problem] if problem else [])]


@command(name="elaborate", group="questions")
def questions_elaborate(project: Project, number: int) -> dict[str, Any]:
    """Have an agent elaborate on a question, as the owner asked: it reads the
    project and rewrites the question. The page runs this itself."""
    outcome = Questions(project).elaborate(number)
    if not outcome["elaborated"]:
        raise Failed(f"question {number} was not elaborated", outcome)
    return outcome


@command(name="page", group="questions")
def questions_page(
    project: Project,
    *,
    port: Annotated[int, Option(help="0 picks a free one.")] = 8765,
    open_page: Annotated[bool, Option("--open", help="Open it in the browser.")] = False,
) -> None:
    """Serve the owner's page, where questions are answered, until stopped."""
    Server(Questions(project), port).run(open_page)


# --- consulting -----------------------------------------------------------------------


@command
def consult(project: Project, consultation: Consultation) -> str:
    """Before something serious — a feature, a migration, a redesign, a change
    of course, or when stuck — have a fresh agent read the project's
    decisions and documents and reframe the task: what it really asks, the
    decisions that bear on it, what could go wrong. Waits for the answer, a
    few minutes; not for routine edits."""
    return Consultant(project).consult(consultation)


# --- consolidation ------------------------------------------------------------------


@command(name="record", group="consolidate")
def consolidate_record(project: Project) -> str:
    """Record the round, at its end (the `/consolidate` skill): the decisions it
    covered, and when — the next round starts from there. Commit it with the map."""
    path = Consolidation(project).finish()
    return f"recorded {path.relative_to(project.root)}"


@command(name="due", group="consolidate")
def consolidate_due(project: Project) -> str | bool:
    """Whether a consolidation round is due; exit 1 when it is not."""
    return Consolidation(project).due() or False


@command(name="material", group="consolidate")
def consolidate_material(project: Project) -> str:
    """What a round reads: the decisions since the last one, every standing
    decision, and the map."""
    return Consolidation(project).material()


# --- generators -----------------------------------------------------------------------


class Binding(TypedDict):
    template: str
    """A file under the catalog's templates/."""
    file: str
    """The output, relative to the repository."""
    tag: NotRequired[str]
    """Render only the entries whose `tags` include it."""


@command(name="write", group="gen")
def gen_write(project: Project) -> list[str]:
    """Write every generated file that has fallen out of step."""
    return [str(path.relative_to(project.here)) for path in Generators(project).write()]


@command(name="new", group="gen", epilog=SYNTAX)
def gen_new(project: Project, name: str, schema: dict[str, Any]) -> str:
    """Start a catalog: a list the code is generated from (error codes, flags,
    strings). SCHEMA is the JSON schema of one entry; then put templates in
    `.nock/generators/NAME/templates/` and bind each to the file it renders."""
    check_schema(schema)
    catalog = Catalogs(project).new(name, schema)
    return f"created {catalog.directory.relative_to(project.here)}"


@command(name="add", group="gen")
def gen_add(project: Project, name: str, entry: dict[str, Any]) -> list[str]:
    """Add an entry (with its `key`) to a catalog; re-renders its files."""
    return relative(project, Catalogs(project).get(name).add(entry))


@command(name="set", group="gen")
def gen_set(project: Project, name: str, key: str, change: dict[str, Any]) -> list[str]:
    """Change an entry's fields (null removes one); re-renders its files."""
    return relative(project, Catalogs(project).get(name).set(key, change))


@command(name="rm", group="gen")
def gen_remove(project: Project, name: str, key: str) -> list[str]:
    """Remove an entry; re-renders its files."""
    return relative(project, Catalogs(project).get(name).remove(key))


@command(name="show", group="gen")
def gen_show(project: Project, name: str | None = None) -> Any:
    """Every generator — or one catalog: its schema, entries and outputs."""
    if name is not None:
        return Catalogs(project).get(name).summary()
    found: list[dict[str, Any]] = [
        {
            "generator": catalog.name,
            "kind": "catalog",
            "entries": len(catalog.entries()),
            "files": " ".join(binding.file for binding in catalog.bindings()),
        }
        for catalog in Catalogs(project).all()
    ]
    found += [
        {"generator": entry.name, "kind": "function", "entries": None, "files": entry.path}
        for entry in project.registry.generators
    ]
    return found


@command(name="bind", group="gen")
def gen_bind(project: Project, name: str, binding: Binding) -> list[str]:
    """Bind one of a catalog's templates to the file it renders."""
    return relative(project, Catalogs(project).get(name).bind(dict(binding)))


@command(name="unbind", group="gen")
def gen_unbind(project: Project, name: str, file: str) -> list[str]:
    """Stop rendering a file from a catalog (the file stays)."""
    return relative(project, Catalogs(project).get(name).unbind(file))


def relative(project: Project, paths: list[Path]) -> list[str]:
    return [
        str(path.relative_to(project.here)) if path.is_relative_to(project.here) else str(path)
        for path in paths
    ]


# --- setup ------------------------------------------------------------------------------


@command
def init(
    *, source: Annotated[str | None, Option(help="Where upgrades come from.")] = None
) -> list[str]:
    """Install nock into this repository — vendored into `.nock/`, wired into
    Claude Code — or re-wire it. Safe to run again."""
    report = Installer(Path.cwd()).install(source)
    return report.lines()


@command
def upgrade(
    project: Project,
    *,
    source: Annotated[str | None, Option(help="A git URL or a local checkout.")] = None,
    force: Annotated[bool, Option(help="Replace the core, losing local edits to it.")] = False,
) -> list[str]:
    """Upgrade the vendored core, keeping local edits to it (a three-way merge)."""
    return Upgrader(project).upgrade(source, force).lines()


# --- nock's own checks ---------------------------------------------------------------------


@check(name="nock-tools")
def tools_load_and_examples_run(project: Project, root: Path) -> list[str]:
    """Every tool loads, and every example a tool gives runs without being
    called wrong or breaking."""
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


@check(name="nock-generators")
def generated_files_in_step(project: Project, root: Path) -> list[str]:
    """Every catalog's entries fit its schema, and no generated file has drifted."""
    problems = []
    for catalog in Catalogs(project).all():
        problems += catalog.problems()
    problems += [
        f"{path} has drifted from its generator — `.nock/nock gen write`"
        for path in Generators(project).drifted(root)
    ]
    return problems


@check(name="nock-map")
def decisions_hold(project: Project, root: Path) -> list[Problem]:
    """Every question the map cites is a standing decision, and every file a
    decision touches still exists."""
    questions = Questions(project)
    listed = Git(root)("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    files = [file for file in listed if (root / file).exists()]
    return questions.citation_problems() + questions.stale_touches(files)


@check(name="nock-wiring")
def hooks_wired(project: Project) -> list[str]:
    """Every event a hook listens to is wired into Claude Code."""
    wired = wired_events(project.here)
    return [
        f"a hook listens to {entry.event} ({entry.source}) but Claude Code does not send it — `.nock/nock init` wires it"
        for entry in project.registry.hooks
        if NATIVE_EVENTS[entry.event] not in wired
    ]
