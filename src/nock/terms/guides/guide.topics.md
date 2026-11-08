---
term: guide.topics
aliases: [guide.items]
description: Topics, items and their kinds, verdicts, refs and where it is all kept
---

# Topics and items

Agents put their work before the owner in topics, and the owner looks at it
afterwards. Nothing waits on the owner: the agent goes ahead, and what it
submitted says what it chose, or shows what it made.

## Topics

A **topic** is a piece of work: a name, a short description of why it exists
and as part of what work, and a thread. An agent looks for the topic of what
it is doing, or opens one:

```sh
$ .nock/nock topics list --query "charge sweep"
$ .nock/nock topics create '{"name": "charge-sweep",
    "description": "The nightly sweep of failed charges, for the payments rework."}'
```

## Items

An **item** is bare: a title, and in each of its versions one asset, of
three kinds:

- a **decision**, nock's own JSON: the answer (markdown, for someone who
  knows what the system does but not how it is built), the alternatives
  really weighed, and done or todo — with the project files it concerns,
  if any;
- a **project file**, a path in the repository, copied as it is when the
  version is made, so versions compare;
- a **derived file**, made to show part of the project — a screenshot of an
  email, a video of a flow, a rendered page, a PDF — with `from` (the project
  files it shows), `when` (the condition it shows: "the payment lapsed") and
  a `recipe` to make it again (a command, an instruction for an agent, or
  both).

Several files are several items. The one exception is **options**: variants
of one asset (three takes on one banner, of one type), submitted with
`"options": true`, shown side by side; the owner may mark one preferred, which
is recorded (`items show` has `preferred`, its version and name) and changes
nothing else. Options are never unrelated files.

```sh
$ .nock/nock items create charge-sweep '{"title": "The sweep requeues dead charges only",
    "decision": {"answer": "The nightly sweep picks up charges whose job died, not ones still retrying…",
                 "alternatives": [{"option": "Requeue failed and dead jobs",
                                   "why_not": "failed jobs are on their backoff; it doubles the attempts"}]}}'
$ .nock/nock items create charge-sweep '{"title": "The lapsed payment email",
    "derived": [{"path": "out/lapsed.png", "from": ["billing/emails/lapsed.py"],
                 "when": "the payment lapsed",
                 "recipe": {"command": "uv run python dev/render.py lapsed --output out/"}}]}'
$ .nock/nock items create charge-sweep '{"title": "The lapsed email's subject line", "options": true,
    "derived": [{"path": "out/subject-a.png"}, {"path": "out/subject-b.png"}, {"path": "out/subject-c.png"}]}'
```

A decision is submitted only when a later reader would ask "why": a choice
between real alternatives the owner hasn't already made, a deliberate
simplification, a reading of something ambiguous, or, as a todo, something
that should be done and is not yet. Carrying out the owner's explicit
instruction is not a decision (the instruction is the record), nor is a
routine implementation detail. What only the owner can settle, when they are
not there to ask, is a decision whose title is the answer the agent proposes
("Refunds never exceed the charge"), the other answers its alternatives; the
agent carries on with it. An item has no notes: anything else the agent has
to say goes in the thread, when asked.

## Where the work stands

A topic's progress is its own: a **state** — planned, active (a new topic's),
done or abandoned — and a **status**, a free line on where the work is, which
the agent sets as it works. Each change is a status entry in the topic's
thread, with its moment and who wrote it, so the history stays; the current
state and status sit in `topic.json`. Work an orchestrating agent dispatches
is tracked so too, on the topic it serves.

```sh
$ .nock/nock topics update charge-sweep '{"state": "active", "status": "requeueing dead charges"}'
$ .nock/nock topics update charge-sweep '{"status": "waiting for the gate on main"}'
$ .nock/nock topics update charge-sweep '{"state": "done"}'
```

A change of state without a status clears the status. The primer asks every
agent to set its topic active with a status when it starts, update the status
at milestones and set it done or abandoned when it finishes; a session that
did its own work in a topic (opened it, or submitted, versioned or answered an
item there; not a migration, not a verdict) and never set where it stands is
stopped once, at the end of its turn, and asked to (`reminders = false` turns
that off).

## Who wrote it, and where it is kept

Every record — a topic's creation, an item's versions, a verdict, a message, a
status entry — keeps who wrote it: `session`, `role` and, for a subagent,
`parent`, the session that dispatched it (its `session` the subagent's id,
its `role` the subagent's type). Claude Code gives a subagent's commands its
parent's session id and nothing of their own, so nock's before-tool hook
notes each `.nock/nock` command about to run with the subagent running it
(the hook input's `agent_id`), and the command, running, claims the note
that matches it. A session nock dispatches (a consultant, the studio's Ask)
is told its parent directly. `topics show` and `items show` print them.

An item's ref is `topic/slug`, the slug made from its title (or given as
`"slug"`), unique in the topic. Everything lives in the main checkout's
`.nock/topics/TOPIC/` — the topic's `topic.json`, each item's `SLUG/item.json`
and its versions' files in `SLUG/N/` — written and committed there whichever
worktree wrote it, so the owner sees it at once; a file over 20 MB (most
videos) stays on the machine, under `.nock/local/topics/`, uncommitted, and
the record says so (`"local": true`).

## Verdicts

| | open | accepted | rejected | dropped |
|---|---|---|---|---|
| **a decision, done** | done; please check | it stands | rework it | closed: nothing to rework |
| **a decision, todo** | worth doing later? | on the backlog | do not do it | do not do it |
| **files** | please look | it stands | make it again | closed: nothing to remake |

- **Verdicts are the owner's.** In the studio, or in a session with
  `/nock-triage`, which goes through the open items with the owner one at a
  time (`nock items judge REF '{"verdict": "accepted"|"rejected", "comment":
  …}'`, or `nock topics judge TOPIC …` for every open item of a topic; Claude
  Code asks the owner before each). A comment goes into the item's thread;
  on the page the owner's words go through the chat instead.
- **A rejection asks for rework, unless it is dropped.** `"rework": false`
  with rejected (the page's Drop) drops the item: superseded, say, nothing to
  rework. It is closed — decided in its topic's counts, in no list of what
  waits on an agent, news to no session — and the page marks it with a muted
  cross. A new version reopens it like any other.
- **Work changes an item.** `nock items update REF '{…}'` changes an open
  item in place. `--version '{…}'` adds a version — what it leaves out
  carried over, project files copied again as they are now — and reopens a
  decided item: an accepted or rejected one changes only so. `{"topic":
  "OTHER"}` moves an item, whatever its verdict, to another existing topic —
  re-filing, not editing: its versions, files and thread go with it, its
  slug is kept (suffixed if taken there), and its old ref and decision
  number still resolve, so citations of it hold. `items delete
  REF` removes only an open item the owner has not written on; `topics delete`
  only an empty topic; git keeps both.
- **A done topic comes back.** A done or abandoned topic takes no new items
  (its items' versions, verdicts and threads go on) until it is revived,
  `nock topics update TOPIC --revive "why it is back"`, which sets it active
  again. The note reads as its description from then on, the revival in its
  chat, its items newest first, the earlier rounds after them: the same
  topic, its history kept.
- **The session that submitted it hears.** When the owner next types there,
  the prompt hook tells it their verdict or message, once — never what that
  session recorded itself (a `judge` it ran on the owner's word), and nothing
  on a dropped item. The submitter is whoever made a version of the item; a
  migration keeps the sessions the earlier records name, never its own.
- **An edit shows the items about a file.** The first time a session edits a
  file an item holds, or a derived file shows (`from`), the edit hook names
  the item.

## Listing and reading

How the two sides talk in the threads is in [Chatting](#chatting).


`nock topics list` and `nock items list [TOPIC]` start with a summary — the
open items by topic, and what waits on the agent: threads where the owner
wrote last, items they rejected — then the list, cut short; `--full` prints
the whole list and no summary. `--query "words"` ranks by plain full text
across topic names and descriptions, item titles, decisions, threads, file
paths and `when` conditions; `topics list --state active` keeps one state,
each row with its state and status. `topics show TOPIC` has its items and thread,
`items show REF` every version, each file and where it is kept, and the
thread. Agents look at it when they start and before they finish. Once a
day (sooner when something new calls) a session the human starts says
"N new in Topics (emails: 2, pricing: 1)" and what waits on it; `nock status`
says it all in full.

## From an earlier nock

A project an earlier nock set up has `.nock/decisions/` and `.nock/review/`:
`nock upgrade` (it runs `nock init`, which does it) moves them into topics
once, in one commit — each decision a decision item (its number kept as an
alias, so `items show 170` and the map's `[D170]` still find it), each review
item an item of derived files with its versions and recipe, each old tag a
topic (an item with several goes to its first; one with none to `general`),
notes and the owner's feedback thread messages, verdicts kept — and drops
the `[decisions]` tags from `.nock/config.toml`. A project running nock from
source runs `nock topics migrate`. What the owner said before the migration counts
as told, so no session hears it as news; a project that migrated before
that runs `nock topics migrate --mark-seen` once. The same commands split, once,
an item from before one asset per item that holds several files: it keeps its
first file (a decision, its decision and the project files it concerns) and
its ref, and each other file becomes an item `SLUG-FILE` with the versions
that hold it, numbered as they were, the verdict kept and the thread copied,
opened by a note that says so.
