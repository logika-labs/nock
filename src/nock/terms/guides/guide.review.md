---
term: guide.review
aliases: [guide.work, guide.reviewing, guide.topics, guide.items, guide.chat, guide.chatting, guide.threads, guide.tidy, guide.tidy-up, guide.tidier, guide.consult, guide.map, guide.consulting]
description: Agents put their work before you in topics and never wait; you review it when it suits you
---

# Review on your time

An agent at work makes calls all the time. Most are routine, some are real
choices: requeue dead charges or failed ones too, refund the whole order or
the item, three takes on a subject line. The obvious design is to have the
agent stop and ask. It doesn't scale: you become the bottleneck, every agent
idles until you answer, and you answer in a hurry, out of context.

nock turns it around. The agent goes ahead, and puts what it chose, or what it
made, before you in a queue. You look at it when it suits you, all at once,
with the context there. A verdict you give reaches the agent that did the work,
and a choice you accept becomes part of the project's memory, which later
agents consult before they change anything.

## Topics

The queue isn't a task manager. Its unit is a **topic**: a piece of work, with
a name, a line on why it exists, and a thread. An agent looks for the topic of
what it is doing, or opens one:

```sh
$ .nock/nock topics list --query "charge sweep"
$ .nock/nock topics create '{"name": "charge-sweep",
    "description": "The nightly sweep of failed charges, for the payments rework."}'
```

A topic says where its work stands with a **state** (planned, active, review,
done or abandoned) and a **status**, a free line the agent keeps current:

```sh
$ .nock/nock topics update charge-sweep '{"state": "active", "status": "requeueing dead charges"}'
$ .nock/nock topics update charge-sweep '{"status": "waiting for the gate on main"}'
$ .nock/nock topics update charge-sweep '{"state": "review", "status": "built; 3 decisions to judge"}'
```

Review means the work is built and only your verdicts remain. Each change is
kept in the topic's thread with its moment and who wrote it, so the history
stays. The primer asks every agent to keep its topic current, and a session
that worked in a topic without ever saying where it stands is stopped once, at
the end of its turn, and asked to. A topic gets a **priority** too
(`'{"priority": 1}'`), which orders your list. A done topic takes no new items
until it is revived, `--revive "why it is back"`, which sets it active again
with its history kept.

That is all the tracking there is, and it's enough: you see what is under way,
what waits on you, and what is finished, and you can search all of it.

## Items

Into a topic go **items**. An item is bare, a title and one asset in each of its
versions, of three kinds:

- a **decision**: the answer, written for someone who knows what the system
  does but not how it's built, the alternatives really weighed and why not,
  and whether it is done or a todo, with the project files it concerns;
- a **project file**: a path in the repository, copied as it is when the
  version is made, so versions compare: a skill, a prompt, a page of copy;
- a **derived file**: something made to show part of the project, such as a
  screenshot of an email, a rendered page, a video of a flow or a PDF, with the
  project files it shows (`from`), the condition it shows (`when`: "the payment
  lapsed") and a `recipe` to make it again.

```sh
$ .nock/nock items create charge-sweep '{"title": "The sweep requeues dead charges only",
    "decision": {"answer": "The nightly sweep picks up charges whose job died, not ones still retrying…",
                 "alternatives": [{"option": "Requeue failed and dead jobs",
                                   "why_not": "failed jobs are on their backoff; it doubles the attempts"}]}}'
$ .nock/nock items create charge-sweep '{"title": "The lapsed payment email",
    "derived": [{"path": "out/lapsed.png", "from": ["billing/emails/lapsed.py"],
                 "when": "the payment lapsed",
                 "recipe": {"command": "uv run python dev/render.py lapsed --output out/"}}]}'
```

Several files are several items, with one exception: **options**, variants of
one asset, such as three takes on a banner, submitted with `"options": true`
and shown side by side, for you to star the one you prefer.

A decision is submitted only when a later reader would ask "why": a choice
between real alternatives you haven't already made, a deliberate
simplification, a reading of something ambiguous, or, as a todo, something
that should be done and isn't yet. Carrying out your explicit instruction is
not a decision; the instruction is the record. And what only you can settle,
while you are away, is submitted as the answer the agent proposes ("Refunds
never exceed the charge"), the others as its alternatives, and the agent
carries on with it.

Everything is kept in the main checkout's `.nock/topics/`, committed whichever
worktree wrote it, so you see it at once; a file over 20 MB stays on the
machine, uncommitted. Every record keeps who wrote it, down to the subagent.

## Reviewing in Work

`nock studio` serves your page on your machine, and its **Work** tab is the
queue. Each topic is a row: its name and status, what it holds ("4 decisions ·
6 images · 3 texts"), its verdicts ("3 open · 12 accepted"), its state and how
long ago it moved. It opens in place, its items in sections: decisions as
bubbles that open on the answer and its alternatives; pictures as a line of
thumbnails; texts as a line of previews; options as one card.

A picture or a text opens in a viewer. **Compare** puts two versions side by
side, a text as a line diff with the changed words marked, a picture zoomed
and panned in step with its other version, so you can check a detail. A video
plays with its captions, and two versions play together. ← and → step through
the topic.

Above the list, **Search** filters as you type, across names, statuses,
decisions, threads, file names and the text of text files, and opens what it
finds. **Ask** sends a question to a fresh agent that reads the topics and
answers with the items it relied on. The filters keep what matters at hand:
**Needs me** (topics in review, open items, chats answered since you looked),
**Waiting on agent**, **Todo** and **Active**; done topics and dropped items
stay hidden until you show them.

You don't have to keep looking. When a topic is your turn again (it moved to
review, an agent answered you, or an item you rejected has a new version),
nock tells you once, however many items the burst brought: "checkout is ready for
review: 3 decisions, 2 files", on the desktop, or in the studio while it is
open (its settings turn on the browser's notifications for when it is away),
and a click opens the topic. `notifications = false` turns it off.

## Verdicts

Each item takes your verdict:

| | open | accepted | rejected | dropped |
|---|---|---|---|---|
| **a decision, done** | done; please check | it stands | rework it | closed: nothing to rework |
| **a decision, todo** | worth doing later? | on the backlog | do not do it | do not do it |
| **files** | please look | it stands | make it again | closed: nothing to remake |

**Accept all** and **Reject all** close a topic at once. A rejection asks for
rework, unless you drop the item: superseded, nothing to rework. If you'd rather
stay in the terminal, `/nock-triage` goes through the open items with you one at
a time in a session.

The session that submitted an item hears your verdict or message the next time
you type there, once. An agent that reworks an item adds a **version**, and the
item is open again, with its history beside it for you to compare. And when a
later session edits a file an item holds or shows, it's told which item, the
first time.

## Chatting

Every word goes through a chat: a topic's, a decision's, a file's, each
opened by the icon beside it. You leave a question on a decision, a comment on
a screenshot; your message waits for the agent's answer, and the agent answers
in that thread (`--reply`), with a new version when the comment asks for one.
Files dropped into a chat go with your message, and the microphone records
what you say and has it made text, by a Whisper server you name in the studio's
settings, for you to edit before you send.

You don't have to answer each comment in its own session. **Address my
comments**, over the chat's composer while comments wait ("Address my 3
comments"), starts an agent that answers them all, each in its own thread, as
an agent working the threads would: a reply, a new version of the item, a
change to the project's files checked with the project's gate. It gives no
verdict and commits no code; the changes are left for you to look at.

**The chat** beside the settings gear talks with a headless Claude Code session
in the project, from every tab. It reads the topics, the items and nock's docs,
and changes nothing. Chats are your conversations, not the project's records:
they stay on your machine, never committed.

## Tidy up

Work gets messy: items filed under the wrong topic, two topics that are one,
one that sprawls, statuses gone stale. **Tidy up**, at the end of the filters'
line, sends an agent to reorganize it, after a short confirm. It moves misplaced
items, merges near-duplicate topics and splits sprawling ones, sets each
topic's state and status from what is there, drops stale or superseded items
with a comment (it never accepts, nor asks for rework), and gives the open
topics a priority, a reason in each status. Its changes land as one commit,
"Work tidied up: …", and **Undo** reverts it.

## The map and consulting

A queue of verdicts is also a record: what was chosen, what was rejected, and
why. nock turns it into the project's memory.

**The map**, `.nock/topics/map.md`, says what the topics and items mean for
the work: when each matters and how they bear on each other. Each reflection
round rewrites it, within three rules: triggers, not facts ("if you touch X,
then Y, because Z [charge-sweep/dead-charges-only]"); a rejected option comes
with what would make it viable again; and what was inferred rather than read
is marked so. A check fails when the map cites an item that doesn't exist.

**Consulting** is how an agent reads it. Before it changes code, unless the task
is really straightforward, it asks:

```sh
$ .nock/nock consult '{"intent": "Move orders to Postgres.", "context": "SQLite locks under load."}'
```

A fresh agent is given the map, the project's tools and checks, and reads the
topics and items about what the work touches. It changes nothing, and takes
the intent as given. It advises in a few lines: first, plainly, an accepted
decision the intent goes against; then what the items mean for the work (what
to keep to, a rejected option it would bring back, a todo it could close), the
topic to submit into, the tools that do its steps, a choice it's about to make
that should be submitted, and the checks to pass. Or it says that nothing in
nock bears on it. Every item, tool and check it names is checked to exist.

So the decision you accepted a month ago reaches the agent about to undo it,
and your product's direction holds across sessions that start knowing nothing.
`consult.enabled = false` turns it off.
