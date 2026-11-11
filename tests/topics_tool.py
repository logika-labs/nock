"""The topics and items commands nock had before agents wrote the store's
files themselves, kept as a project's tool for the tests: they drive `Topics`
through nock's real CLI, as the tests always have."""

from __future__ import annotations

from typing import Annotated, Any

import nock
from nock.commands import Option, read_record, schema_of
from nock.errors import PolicyError
from nock.migration import Migration
from nock.project import Project
from nock.schema import validate
from nock.topics import (
    SHORT,
    TIDIER,
    ItemChange,
    ItemDraft,
    State,
    TopicChange,
    TopicDraft,
    Topics,
    Verdict,
    Word,
    in_order,
    verdict_of,
)
from nock.usage import Moment, Usage


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


@nock.command(name="list", group="topics")
def topics_list(
    project: Project,
    *,
    query: Annotated[str | None, Option(help="Plain words, ranked by how well they match.")] = None,
    state: Annotated[
        State | None,
        Option(help="Only the topics in this state: planned, active, review, done, abandoned."),
    ] = None,
    full: Annotated[bool, Option(help="The whole list, without the summary.")] = False,
) -> dict[str, Any]:
    """The topics in the owner's order (by `priority`, then newest activity
    first), each with its state and status and
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
        rows = in_order(rows)
    return listed(rows, full, topics.summary())


@nock.command(name="create", group="topics")
def topics_create(project: Project, topic: TopicDraft) -> dict[str, Any]:
    """Open a topic for a piece of work: a name and why it exists, as part of
    what work; its `state` active (the default), planned or review, and its `status`,
    where the work is in a line. Look for an existing one first (`topics list
    --query …`): what you are doing may already have its topic, and a done
    one that comes back is revived, not made again."""
    record, problem = Topics(project).create_topic(topic)
    return not_committed({"name": record["name"]}, problem)


@nock.command(name="update", group="topics")
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
    """Keep a topic's progress current — its `state` (planned, active, review
    once it is built and only the owner's verdicts remain, done, abandoned)
    and its `status`, where the work is in a line:
    `{"status": "waiting for the gate on main"}`, `{"state": "review"}` — each
    change kept in its thread; change its name or description; answer in its
    thread; or revive it when it was done or abandoned and the work comes
    back: active again, the note saying why it is back and reading as its
    description from then on. `{"priority": 1}` puts it first in the
    owner's order (0 takes its place away)."""
    record, problem = Topics(project).update_topic(topic, change, reply, revive)
    return not_committed(
        {
            "name": record["name"],
            "state": record["state"],
            **({"status": record["status"]} if record.get("status") else {}),
            **({"priority": record["priority"]} if record.get("priority") else {}),
            **answered(record, reply),
        },
        problem,
    )


@nock.command(name="delete", group="topics")
def topics_delete(project: Project, topic: str) -> dict[str, Any]:
    """Delete an empty topic; git keeps it."""
    problem = Topics(project).delete_topic(topic)
    return not_committed({"deleted": topic}, problem)


@nock.command(name="show", group="topics")
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


@nock.command(name="judge", group="topics")
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


@nock.command(name="migrate", group="topics")
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


@nock.command(name="list", group="items")
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


@nock.command(name="create", group="items")
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


@nock.command(name="update", group="items")
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


@nock.command(name="delete", group="items")
def items_delete(project: Project, item: str) -> dict[str, Any]:
    """Delete an open item the owner has not written on — one that should not
    have been submitted; git keeps it."""
    problem = Topics(project).delete_item(item)
    return not_committed({"deleted": item}, problem)


@nock.command(name="show", group="items")
def items_show(project: Project, item: str) -> dict[str, Any]:
    """An item: its verdict, every version (its decision, each file and where
    it is kept), its thread — each with the session that wrote it, and its
    parent session for a subagent's; each file a message carries with
    `where`, its path to read. ITEM is `topic/slug`, or an earlier
    decision's number."""
    topics = Topics(project)
    return topics.shown(topics.item(item))


@nock.command(name="judge", group="items")
def items_judge(project: Project, item: str, word: Word) -> dict[str, Any]:
    """The owner's verdict on an item — accepted, or rejected: reworked as
    the thread says, or with `"rework": false` dropped, closed with nothing to
    rework (superseded, say) — with their comment in its thread. Only on the
    owner's word: `/nock-triage` runs it with them. Tidy up only drops."""
    topics = Topics(project)
    if project.current_role() == TIDIER and verdict_of(word) is not Verdict.DROPPED:
        raise PolicyError(
            'Tidy up only drops (`"verdict": "rejected", "rework": false`): accepting,'
            " and asking for rework, are the owner's alone"
        )
    record, problem = topics.judge(item, word)
    topics.tell_writer([record["ref"]])
    if project.current_role() == TIDIER:
        return {"ref": record["ref"], "verdict": record["verdict"]}
    result = not_committed({"ref": record["ref"], "verdict": record["verdict"]}, problem)
    ask(project, result, Moment.REVIEW)
    return result


def ask(project: Project, result: dict[str, Any], moment: Moment) -> None:
    """Whether nock may share its usage report, asked of the owner the first
    time they engage with it here, while nobody has answered."""
    question = Usage(project).ask(moment)
    if question:
        result["ask_the_owner"] = question
