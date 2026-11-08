"""nock's own commands and checks, registered through the same decorators a
project's tools use — they are tools too."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from nock.asking import Answer, Asker
from nock.checks import Checks
from nock.commands import Group, Option, read_record, schema_of
from nock.comparison import Comparison, Query
from nock.configuration import Confirm
from nock.consult import Advice, Consultant, Consultation
from nock.docs import Docs
from nock.errors import Error, ExitCode, Failed, UsageError
from nock.evaluation import SCENARIOS, Evaluations, Import, Run, Scenario
from nock.fixtures import Shell
from nock.generators import Catalogs, Generators
from nock.kinds import DEFAULT, KINDS
from nock.migration import Migration
from nock.processes import Output
from nock.project import Project
from nock.reflect import Record, Reflection, Round, tool_rows
from nock.render import Problem
from nock.reports import Reports
from nock.results import Results
from nock.schema import check_schema, validate
from nock.sessions import Sessions
from nock.setup import (
    PERMISSION,
    RETIRED_PERMISSIONS,
    Installer,
    Upgrader,
    ours,
    permission_rules,
    wanted_permissions,
    wired_events,
)
from nock.share import Request as ShareRequest
from nock.share import Sharing
from nock.status import Standing
from nock.studio import Studio
from nock.telemetry import UNRECORDED_VARIABLE
from nock.templates import SYNTAX
from nock.tools import NATIVE_EVENTS, Tool, check, command
from nock.topics import (
    SHORT,
    ItemChange,
    ItemDraft,
    State,
    TopicChange,
    TopicDraft,
    Topics,
    Word,
    verdict_of,
)
from nock.usage import QUESTION, Moment, Usage


class StudioOptions(TypedDict):
    port: NotRequired[int]
    """0 picks a free one."""
    open: NotRequired[bool]
    """Open it in the browser."""


EXAMPLE_DEADLINE = 300


# --- working -------------------------------------------------------------------


@command(name="check")
def check_command(
    project: Project,
    names: list[str] | None = None,
    *,
    fix: Annotated[bool, Option(help="Run each command check's `fix` first.")] = False,
    changed: Annotated[
        bool,
        Option(
            help="Only the checks the branch's changes (since the main branch, committed or not) can affect."
        ),
    ] = False,
) -> None:
    """Run the checks — all of them, or those named; prints nothing when all pass.
    Exit 1: the code is wrong. 42 (or 54/55): the machine is. `--changed` runs
    only those the changes since the main branch can affect, by each check's
    `paths`."""
    verdict = Checks(project).run(names or None, fix=fix, changed=changed)
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
    prompts, events — a round's material explains them. The transcripts are
    read up to now first."""
    Sessions(project).catch_up()
    return project.store.query(sql)


@command
def sessions(project: Project, *, limit: int = 15) -> list[dict[str, Any]]:
    """Recent Claude Code sessions in this project: what each was, its role
    (interactive, headless or the one nock dispatched it as), its tokens and
    what they would cost at API prices (unknown when its model is unpriced)."""
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
            "api_cost": round(row["cost"], 2) if row["cost"] is not None else "unknown",
        }
        for row in rows
    ]


# --- where things stand ------------------------------------------------------------


@command
def status(project: Project) -> dict[str, Any]:
    """Where the project stands with nock: whether a reflection round is due,
    the open items by topic, what waits on an agent in the topics (threads
    where the owner wrote last, rejected items), a round summary not yet
    shared, and whether a newer nock is out."""
    return Standing(project).collect()


@command
def studio(
    project: Project,
    options: StudioOptions = {},  # noqa: B006
) -> None:
    """Serve the owner's page, a tab for each thing to look at — the topics
    and their items, the evaluations — until stopped (port
    8765 unless OPTIONS say otherwise)."""
    if Usage(project).ask(Moment.STUDIO):
        print(f"nock: {QUESTION} The page asks too; answer there.", flush=True)
    Studio(project, options.get("port", 8765)).run(options.get("open", False))


# --- topics and items ----------------------------------------------------------------


def not_committed(result: dict[str, Any], problem: str | None) -> dict[str, Any]:
    if problem:
        result["not_committed"] = problem
    return result


def answered(record: dict[str, Any], reply: str | None) -> dict[str, Any]:
    """`answered`, when the reply answered the owner's waiting message: the
    page shows them it is in, and opens their chat again."""
    if reply is not None and record["thread"] and "answers" in record["thread"][-1]:
        return {"answered": record["thread"][-1]["answers"]}
    return {}


def listed(rows: list[Any], full: bool, summary: dict[str, Any] | None) -> dict[str, Any]:
    """A list as `list` prints it: the summary first and the list cut short,
    or with `--full` the whole list and no summary."""
    if full or summary is None:
        return {"rows": rows}
    result: dict[str, Any] = {"summary": summary, "rows": rows[:SHORT]}
    if len(rows) > SHORT:
        result["more"] = f"{len(rows) - SHORT} more — `--full` lists them all"
    return result


@command(name="list", group="topics")
def topics_list(
    project: Project,
    *,
    query: Annotated[str | None, Option(help="Plain words, ranked by how well they match.")] = None,
    state: Annotated[
        State | None,
        Option(help="Only the topics in this state: planned, active, done, abandoned."),
    ] = None,
    full: Annotated[bool, Option(help="The whole list, without the summary.")] = False,
) -> dict[str, Any]:
    """The topics, newest activity first, each with its state and status and
    its open, accepted and rejected counts — or those matching QUERY, the
    best first (topic names and descriptions, statuses, item titles,
    decisions, threads, file paths, conditions); `--state` keeps one state.
    Without `--full`, first a summary: the open items by topic, and what waits
    on you — threads where the owner wrote last (with the paths of the files
    their last message carries, to read), items they rejected. Look at it
    when you start and before you finish."""
    topics = Topics(project)
    names = topics.search_topics(query) if query else topics.names()
    rows = [topics.row(name) for name in names]
    if state is not None:
        rows = [row for row in rows if row["state"] == state]
    if not query:
        rows.sort(key=lambda row: row["active"], reverse=True)
    return listed(rows, full, topics.summary())


@command(name="create", group="topics")
def topics_create(project: Project, topic: TopicDraft) -> dict[str, Any]:
    """Open a topic for a piece of work: a name and why it exists, as part of
    what work; its `state` active (the default) or planned, and its `status`,
    where the work is in a line. Look for an existing one first (`topics list
    --query …`): what you are doing may already have its topic, and a done
    one that comes back is revived, not made again."""
    record, problem = Topics(project).create_topic(topic)
    return not_committed({"name": record["name"]}, problem)


@command(name="update", group="topics")
def topics_update(
    project: Project,
    topic: str,
    change: TopicChange = {},  # noqa: B006
    *,
    reply: Annotated[
        str | None,
        Option(
            help="Add this message (markdown) to its thread: the one answer to the owner's"
            " waiting message, when there is one."
        ),
    ] = None,
    revive: Annotated[
        str | None,
        Option(help="Bring a done or abandoned topic back, active, saying why (markdown)."),
    ] = None,
) -> dict[str, Any]:
    """Keep a topic's progress current — its `state` (planned, active, done,
    abandoned) and its `status`, where the work is in a line:
    `{"status": "waiting for the gate on main"}`, `{"state": "done"}` — each
    change kept in its thread; change its name or description; answer in its
    thread; or revive it when it was done or abandoned and the work comes
    back: active again, the note saying why it is back and reading as its
    description from then on."""
    record, problem = Topics(project).update_topic(topic, change, reply, revive)
    return not_committed(
        {
            "name": record["name"],
            "state": record["state"],
            **({"status": record["status"]} if record.get("status") else {}),
            **answered(record, reply),
        },
        problem,
    )


@command(name="delete", group="topics")
def topics_delete(project: Project, topic: str) -> dict[str, Any]:
    """Delete an empty topic; git keeps it."""
    problem = Topics(project).delete_topic(topic)
    return not_committed({"deleted": topic}, problem)


@command(name="show", group="topics")
def topics_show(project: Project, topic: str) -> dict[str, Any]:
    """A topic: its state and status, its description, its items (the newest
    first), its thread — each entry with the session that wrote it, and its
    parent session for a subagent's; each file a message carries with
    `where`, its path to read."""
    topics = Topics(project)
    record = topics.topic(topic)
    return {
        **topics.row(topic),
        "items": [topics.item_row(item) for item in topics.items(topic)],
        "thread": topics.thread_shown(record["thread"], record["name"]),
    }


@command(name="judge", group="topics", confirm=True)
def topics_judge(project: Project, topic: str, word: Word) -> dict[str, Any]:
    """The owner's verdict on every open item of a topic (`"rework": false`
    with rejected drops them), with their comment in its thread. Only on the
    owner's word: `/nock-triage` runs it with them."""
    topics = Topics(project)
    judged, problem = topics.judge_topic(topic, word)
    topics.tell_writer(judged)
    result = not_committed({"judged": judged, "verdict": str(verdict_of(word))}, problem)
    ask(project, result, Moment.REVIEW)
    return result


@command(name="ask", group="topics")
def topics_ask(project: Project, question: str) -> dict[str, Any]:
    """Have a fresh agent answer a question about the topics (`nock studio`'s
    Ask runs this): the answer, in markdown, and the items it relied on."""
    return Asker(project).ask(question)


@command(name="answer", group="topics")
def topics_answer(project: Project, answer: Answer) -> str:
    """The asked agent's answer, submitted; only an agent the studio's Ask dispatched runs this."""
    return Asker(project).submit(answer)


@command(name="migrate", group="topics")
def topics_migrate(
    project: Project,
    *,
    mark_seen: Annotated[
        bool,
        Option(
            help="Already migrated: mark everything the owner has said so far as told"
            " (local state only), so the hooks announce only what is said from now on."
        ),
    ] = False,
) -> dict[str, Any]:
    """Move an earlier nock's decisions and review items into topics, once:
    each tag a topic (untagged: `general`), verdicts and notes kept, and
    counted as told already. `init` and `upgrade` run it; a project running
    nock from source runs it by hand."""
    return Migration(project).run(mark_seen=mark_seen)


@command(name="list", group="items")
def items_list(
    project: Project,
    topic: str | None = None,
    *,
    query: Annotated[str | None, Option(help="Plain words, ranked by how well they match.")] = None,
    full: Annotated[bool, Option(help="The whole list, without the summary.")] = False,
) -> dict[str, Any]:
    """The items (of TOPIC), newest first, each with its verdict — or those
    matching QUERY, the best first. Without `--full`, first a summary: the
    open items by topic, and what waits on you."""
    topics = Topics(project)
    if topic:
        topics.topic(topic)
    if query:
        found = topics.search_items(query, topic)
    else:
        found = topics.items(topic) if topic else topics.every()
        found.sort(key=lambda item: item["updated"], reverse=True)
    return listed([topics.item_row(item) for item in found], full, topics.summary())


@command(name="create", group="items")
def items_create(project: Project, topic: str, item: ItemDraft) -> dict[str, Any]:
    """Put an item before the owner, in its topic: a title and what it holds —
    a `decision` (the answer, the alternatives you weighed, done or todo),
    project `files` (paths in the repository, copied as they are now), or
    `derived` files (made to show part of the project: a screenshot of an
    email, with what it comes `from`, `when` it applies, and a `recipe` to
    make it again). Bare: no notes; say more in the thread only when asked.
    Record a decision only when a later reader would ask "why" — a choice
    between real alternatives, a deliberate simplification, a reading of
    something ambiguous, a todo you leave; never the owner's own instruction
    or a routine detail. The owner gives the verdict later: carry on."""
    record, problem = Topics(project).create_item(topic, item)
    return not_committed({"ref": record["ref"]}, problem)


def parsed_version(version: str | None) -> ItemChange | None:
    if version is None:
        return None
    value = read_record(version)
    validate(value, schema_of(ItemChange))
    return value


@command(name="update", group="items")
def items_update(
    project: Project,
    item: str,
    change: ItemChange = {},  # noqa: B006
    *,
    version: Annotated[
        str | None,
        Option(help="JSON: a new version (what it leaves out is carried over); reopens the item."),
    ] = None,
    reply: Annotated[
        str | None,
        Option(
            help="Add this message (markdown) to its thread: the one answer to the owner's"
            " waiting message, when there is one."
        ),
    ] = None,
) -> dict[str, Any]:
    """Change an open item in place (its title, decision, files), add a new
    version — project files copied again as they are now, a decided item
    reopened — or answer in its thread. An accepted or rejected item changes
    only by a new version; any item moves to another existing topic
    (`{"topic": "OTHER"}`), its old ref kept as an alias. Rework a rejected item as a new version; when the
    owner is away, say briefly in the thread what changed, unless the new
    version says it. Progress is the topic's: `topics update TOPIC
    '{"status": …}'`."""
    record, problem = Topics(project).update_item(
        item, change or None, parsed_version(version), reply
    )
    return not_committed(
        {
            "ref": record["ref"],
            "verdict": record["verdict"],
            "versions": len(record["versions"]),
            **answered(record, reply),
        },
        problem,
    )


@command(name="delete", group="items")
def items_delete(project: Project, item: str) -> dict[str, Any]:
    """Delete an open item the owner has not written on — one that should not
    have been submitted; git keeps it."""
    problem = Topics(project).delete_item(item)
    return not_committed({"deleted": item}, problem)


@command(name="show", group="items")
def items_show(project: Project, item: str) -> dict[str, Any]:
    """An item: its verdict, every version (its decision, each file and where
    it is kept), its thread — each with the session that wrote it, and its
    parent session for a subagent's; each file a message carries with
    `where`, its path to read. ITEM is `topic/slug`, or an earlier
    decision's number."""
    topics = Topics(project)
    return topics.shown(topics.item(item))


@command(name="judge", group="items", confirm=True)
def items_judge(project: Project, item: str, word: Word) -> dict[str, Any]:
    """The owner's verdict on an item — accepted, or rejected: reworked as
    the thread says, or with `"rework": false` dropped, closed with nothing to
    rework (superseded, say) — with their comment in its thread. Only on the
    owner's word: `/nock-triage` runs it with them."""
    topics = Topics(project)
    record, problem = topics.judge(item, word)
    topics.tell_writer([record["ref"]])
    result = not_committed({"ref": record["ref"], "verdict": record["verdict"]}, problem)
    ask(project, result, Moment.REVIEW)
    return result


def ask(project: Project, result: dict[str, Any], moment: Moment) -> None:
    """Whether nock may share its usage report, asked of the owner the first
    time they engage with it here, while nobody has answered."""
    question = Usage(project).ask(moment)
    if question:
        result["ask_the_owner"] = question


# --- consulting -----------------------------------------------------------------------


@command
def consult(project: Project, consultation: Consultation) -> str:
    """Before you change code, have a fresh agent read the project for the
    decisions, tools and checks that bear on what you are about to do; waits
    for its advice."""
    return Consultant(project).consult(consultation)


@command
def advise(project: Project, advice: Advice) -> str:
    """The consultant's advice, submitted; only a consultant nock dispatched runs this."""
    return Consultant(project).submit(advice)


# --- reflection ---------------------------------------------------------------------


@command(name="reflect")
def reflect(project: Project) -> dict[str, Any]:
    """Start nock's own reflection round (the `/nock-reflect` skill), or pick
    up the one under way: writes what its three parts read, and says where
    the report and the shareable summary go. `nock reflect KIND` starts
    another kind (`nock docs reflection.kinds`)."""
    return started(project, DEFAULT(project))


@command(name="finish", group="reflect")
def reflect_finish(project: Project, record: Record) -> dict[str, Any]:
    """Finish nock's round: requires its report and summary, nock's checks to
    pass, then records what the toolbox part changed and what each change
    should do by the next round, and commits `.nock/`."""
    return DEFAULT(project).finish(record)


def started(project: Project, kind: Round) -> dict[str, Any]:
    begun = kind.start()
    ask(project, begun, Moment.ROUND)
    return begun


def kind_commands(kind: type[Round]) -> None:
    """`nock reflect KIND` and `nock reflect KIND finish JSON`, for a kind other than nock's."""

    def start_kind(project: Project) -> dict[str, Any]:
        return started(project, kind(project))

    def finish_kind(project: Project, record: Record) -> dict[str, Any]:
        return kind(project).finish(record)

    start_kind.__doc__ = (
        f"Start a {kind.title} (the `/{kind.skill}` skill), or pick up the one under way: "
        "writes what it reads, and says where its report goes."
    )
    finish_kind.__doc__ = (
        f"Finish the {kind.title}: requires its report and its checks to pass, records it, "
        "and commits it."
    )
    command(name=kind.kind, group="reflect")(start_kind)
    command(name="finish", group=f"reflect {kind.kind}")(finish_kind)


for _kind in KINDS.values():
    if not _kind.default:
        kind_commands(_kind)


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


@command
def usage(project: Project) -> dict[str, Any]:
    """What nock shares with its makers (`share`): the owner's answer
    (unanswered, yes or no), when this machine asked and recorded it, the
    reports sent, when the next goes, and exactly what it would carry."""
    return Usage(project).standing()


@command(name="share", group="usage")
def usage_share(project: Project, answer: Literal["yes", "no"]) -> dict[str, Any]:
    """Record the owner's answer to whether nock shares its weekly usage
    report: `share` in .nock/config.toml, committed, with when it was given.
    Only what the owner said, when they said it."""
    return Usage(project).answer(answer == "yes", "command")


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


@command(confirm=True)
def init(
    *, source: Annotated[str | None, Option(help="Where upgrades come from.")] = None
) -> list[str]:
    """Install nock into this repository — vendored into `.nock/`, wired into
    Claude Code — or re-wire it. Safe to run again."""
    report = Installer(Path.cwd()).install(source)
    return report.lines()


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
        f"{path} has drifted from its generator — `.nock/nock gen write`"
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
            f"Claude Code allows `{rule}`, which lets `.nock/nock run` take any command unasked — `.nock/nock init` narrows it"
            for rule in RETIRED_PERMISSIONS
            if rule in allowed
        ]
        + [
            f"`{rule.removeprefix('Bash(').removesuffix(':*)')}` is not allowed yet, so Claude Code asks before each call — `.nock/nock init` allows it (it asks the owner)"
            for rule in wanted
            if rule not in allowed
        ]
    )


# --- evaluations ---------------------------------------------------------------------------


@command(name="init", group="eval")
def eval_init(project: Project, scenario: str) -> list[str]:
    """Start a scenario in `evals/SCENARIO/`: a Snakefile with one cached
    rule, its step, nock's Snakemake profile, and the .gitignore and
    .gitattributes that commit the cache and leave results/ to each checkout."""
    return Evaluations(project).init(scenario)


@command(name="run", group="eval")
def eval_run(
    project: Project,
    targets: list[str] | None = None,
    *,
    scenario: Annotated[str | None, Option(help="The scenario; the only one by default.")] = None,
    dry: Annotated[
        bool, Option(help="Say what reruns and why, what the cache restores, and the estimate.")
    ] = False,
    budget: Annotated[
        float | None, Option(help="Refuse to start when computing is estimated to cost more (USD).")
    ] = None,
    cores: Annotated[int | None, Option(help="Override the profile's cores.")] = None,
    limit: Annotated[
        list[str] | None,
        Option(help="Override a resource's limit, NAME=N (repeat): `--limit stacks=6`."),
    ] = None,
    retry: Annotated[
        bool,
        Option(
            help="Compute the failed outputs again, and what was computed from them; "
            "each step can read its failed attempt (`step.previous`)."
        ),
    ] = False,
) -> Any:
    """Run a scenario's Snakefile with nock's profile — its default target, or
    TARGETS (output paths or rule names) — restoring from cache/ every output
    whose code, params and inputs match one computed anywhere, and computing
    the rest. A dry run first: what reruns and why, and the estimate from
    each rule's past cost.json; it refuses outputs that would share a cache
    entry, Git LFS pointers, and an estimate past the budget. `--retry` takes
    the failed out of the cache first (a dry run only says how many)."""
    evaluations = Evaluations(project)
    chosen = evaluations.scenario(scenario)
    if limit and any(not re.fullmatch(r"[\w-]+=\d+", item) for item in limit):
        raise UsageError("a limit is NAME=N, a resource and how much of it runs at once")
    if retry and dry:
        failed = [row for row in evaluations.prunable(chosen) if row["why"] == "failed"]
        return {"retry": len(failed), "say": "without --dry, they and what follows them run again"}
    retried = evaluations.retry(chosen) if retry else []
    plan = Run(chosen, targets or [], budget)
    if dry:
        refused = plan.refusal()
        return {
            "jobs": plan.lines(),
            **plan.summary(),
            **({"refused": refused} if refused else {}),
        }
    summary = plan.summary()
    if summary["to_compute"]:
        print(
            f"nock: {summary['to_compute']} job(s) to compute, {summary['from_cache']} from cache, "
            f"~${summary['estimated_cost_usd']:.2f}",
            file=sys.stderr,
            flush=True,
        )
    done = plan.execute(cores, limit)
    if retried:
        done["retried"] = sum(1 for row in retried if row["why"] == "failed")
    return done


@command(name="import", group="eval")
def eval_import(project: Project, record: Import) -> dict[str, Any]:
    """Put outputs computed elsewhere (another pipeline's results, say) into a
    scenario's cache, each under the entry its job would have, so a run
    restores them rather than computing them: its files cloned from a source
    directory, which is never moved or changed, with its metrics, cost and,
    for a failed output, its error. Refused when an output is no cached job of
    the targets; an output already in the cache is left as it is."""
    return Evaluations(project).load(record)


@command(name="show", group="eval")
def eval_show(project: Project, name: str | None = None) -> Any:
    """The scenarios; or one scenario's rules — outputs current, stale and
    failed, cost, time — with why the stale are stale and what the failed said."""
    evaluations = Evaluations(project)
    if name is None:
        return [
            show_scenario(evaluations.scenario(item), summary=True) for item in evaluations.names()
        ] or f"no scenarios yet: `nock eval init NAME` starts one in {SCENARIOS}/"
    return show_scenario(evaluations.scenario(name), summary=False)


def show_scenario(scenario: Scenario, summary: bool) -> dict[str, Any]:
    results = Results(scenario)
    rules, stale, failed = results.run(
        [
            "SELECT rule, count(*) AS outputs, count(*) FILTER (state = 'current') AS current,"
            " count(*) FILTER (state = 'stale') AS stale, count(*) FILTER (state = 'failed')"
            " AS failed, round(sum(cost_usd), 4) AS cost_usd, round(avg(seconds), 3)"
            " AS mean_seconds FROM outputs GROUP BY rule ORDER BY rule",
            "SELECT path, why FROM outputs WHERE state = 'stale' ORDER BY path",
            "SELECT path, error FROM outputs WHERE state = 'failed' ORDER BY path",
        ]
    )
    counts = {key: sum(row[key] for row in rules["rows"]) for key in ("current", "stale", "failed")}
    entries = [entry for entry in scenario.cache.iterdir()] if scenario.cache.is_dir() else []
    if summary:
        return {
            "scenario": scenario.name,
            **counts,
            "cache_entries": sum(1 for entry in entries if not entry.name.startswith(".")),
            "cost_usd": round(sum(row["cost_usd"] or 0 for row in rules["rows"]), 4),
        }
    result: dict[str, Any] = {"scenario": scenario.name, "rules": rules["rows"]}
    if stale["rows"]:
        result["stale"] = stale["rows"]
    if failed["rows"]:
        result["failed"] = failed["rows"]
    if not rules["rows"]:
        result["say"] = (
            "nothing under results/ yet: `nock eval run` computes it, or restores it from cache/"
        )
    elif stale["rows"] or failed["rows"]:
        result["say"] = (
            "`nock eval run` recomputes the stale; `nock eval prune` deletes the stale and failed "
            "from the cache, so a run computes the failed again"
        )
    return result


@command(name="query", group="eval")
def eval_query(
    project: Project,
    sql: str,
    *,
    scenario: Annotated[str | None, Option(help="The scenario; the only one by default.")] = None,
) -> list[dict[str, Any]]:
    """Read a scenario's results with SQL (DuckDB, read-only), loaded fresh from
    the files: outputs, metrics, diffs, and a table per rule with a column per
    parameter and metric (`nock docs eval.query`)."""
    return Results(Evaluations(project).scenario(scenario)).rows(sql)


@command(name="compare", group="eval")
def eval_compare(project: Project, query: Query) -> list[dict[str, Any]]:
    """Compare a rule's outputs by one parameter, holding the others fixed and
    pooling the repetitions: each mean with its bootstrap confidence interval
    (95 in 100), and the difference from the baseline, paired when the units match."""
    return Comparison(project).compare(query)


@command(name="prune", group="eval")
def eval_prune(
    project: Project,
    scenario: str | None = None,
    *,
    dry: Annotated[bool, Option(help="Say what would be deleted, and delete nothing.")] = False,
) -> list[dict[str, Any]] | str:
    """Delete stale and failed outputs from the cache — every scenario's, or
    SCENARIO's: the entries no current output of the default target is, and
    the failed, so a run computes them again."""
    rows = Evaluations(project).prune(scenario, dry)
    return rows or "nothing to prune"


@check(name="nock-eval", paths=[".nock/**", "evals/**"])
def evaluations_hold(project: Project) -> list[str]:
    """Every scenario has nock's profile, a Snakefile Snakemake reads, and
    rules cached by their wildcards."""
    return Evaluations(project).problems()
