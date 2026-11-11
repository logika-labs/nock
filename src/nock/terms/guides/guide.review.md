---
term: guide.review
aliases: []
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
a name, a line on why it exists, and a thread. Topics are files in the
repository, `.nock/shared/topics/`, one event per file, and agents write them
with their own tools; nock checks each file, fills in when and who, and
commits it on its own. An agent looks for the topic of what it is doing, or
opens one:

```sh
$ .nock/nock search "charge sweep"
$ cat .nock/shared/topics/charge-sweep/events/new.json
{"kind": "created", "description": "The nightly sweep of failed charges, for the payments rework."}
```

A topic says where its work stands with a **state** (planned, active, review,
done or abandoned) and a **status**, a free line the agent keeps current, each
a `state` event:

```json
{"kind": "state", "state": "active", "status": "requeueing dead charges"}
{"kind": "state", "status": "waiting for the gate on main"}
{"kind": "state", "state": "review", "status": "built; 3 decisions to judge"}
```

Review means the work is built and only your verdicts remain. Each change is
kept in the topic's thread with its moment and who wrote it, so the history
stays. The primer asks every agent to keep its topic current, and a session
that worked in a topic without ever saying where it stands is stopped once, at
the end of its turn, and asked to. A topic gets a **priority** too
(`"priority": 1`), which orders your list. A done topic takes no new decisions
until it is revived (`"state": "active", "revived": true, "note": "why it is
back"`), with its history kept. Each topic is also written out whole, for
agents to read, in `.nock/local/views/`.

That is all the tracking there is, and it's enough: you see what is under way,
what waits on you, and what is finished, and you can search all of it.

## Decisions and their assets

Into a topic go **decisions**. A decision is bare: a short title, a
description under it, and its answer, written for someone who knows what the
system does but not how it's built, with the alternatives really weighed and
why not, and whether it is done or a todo. It holds the **assets** that show
what it looks like:

- a **project file**: a path in the repository, linked at the commit that last
  changed it, so versions compare: a skill, a prompt, a page of copy;
- a **derived file**: something made to show part of the project, such as a
  screenshot of an email, a rendered page, a video of a flow or a PDF, with the
  project files it shows (`from`), the condition it shows (`when`: "the payment
  lapsed") and a `recipe` to make it again.

```sh
.nock/shared/topics/charge-sweep/decisions/requeue-dead-only/
  events/…json                     {"kind": "created", "title": "The sweep requeues dead charges only"}
  versions/1/decision.json         {"answer": "…", "alternatives": [{"option": "…", "why_not": "…"}]}
  assets/lapsed-email/
    events/…json                   {"kind": "created", "title": "The lapsed payment email"}
    versions/1/assets.json         {"files": [{"kind": "derived", "name": "lapsed.png", "from": […],
                                    "when": "the payment lapsed", "recipe": {"command": "…"}}]}
```

A file that needs your eye but holds no real choice gets a plain decision,
"Review: the lapsed payment email", holding it. **Before and after** are two
versions of one asset: version 1 the before (rendered from git history, say),
version 2 the after, and the studio compares them side by side or with a
toggle; that is how a change is reviewed. **Variants** are for "pick one of
these": takes on one thing, such as three banners, in one asset version with
`"variants": true`, for you to star the one you prefer; the decision is
accepted only once each asset with variants has one starred. An asset may also
hold **views**, HTML pages with nock's look that lay its variants out, such as
each favicon at three sizes.

A decision is recorded only when a later reader would ask "why": a choice
between real alternatives you haven't already made, a deliberate
simplification, a reading of something ambiguous, or, as a todo, something
that should be done and isn't yet. Carrying out your explicit instruction is
not a decision; the instruction is the record. And what only you can settle,
while you are away, is recorded as the answer the agent proposes ("Refunds
never exceed the charge"), the others as its alternatives, and the agent
carries on with it.

Everything is kept in the main checkout's `.nock/shared/`, one file per
event, committed whichever worktree wrote it, so you see it at once; pictures,
videos and other media go in `.nock/shared/media/` by their content, which
the project may commit, put under git LFS or ignore. Every event keeps who
wrote it, down to the subagent.

## Reviewing in Topics

`nock studio` serves your page on your machine, and its **Topics** tab is the
queue. Each topic is a row: its name and status, what it holds ("4 decisions ·
9 assets"), its verdicts ("3 open · 12 accepted"), its state and how long ago
it moved. It opens in place, its items in two sections: decisions as bubbles
that open on the answer and its alternatives, and assets as a grid of cards or
a list of rows. A card shows the asset (the preferred variant, else the first),
its state at the top right (accepted, rejected, a star for a variant preferred,
or how many variants wait for one), and along its foot as much of its title
and description as fits, then when it last changed and its chat; hovering it
shows the whole title and description.

An asset opens in a viewer, one size whatever it holds; its chat icon opens
it with its chat beside it. **Compare** puts two versions side by
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

The **Timeline** tab shows the same topics as a feed of notifications, the
newest first: an agent answered you, an item came up for review or a new
version of one, a topic opened, changed state or status, or came back. Each
card says what happened beside its topic's name, then a title and a few lines
of description, and an asset's pictures and videos; a topic's status changes
in a row are one card. A card leads to the thing itself, opened: the item in
the viewer, the chat with the answer; its topic's name opens the topic.
Hovered, a decision waiting for you offers Accept and Reject, and an answer
Reply. A dot marks what came since you last looked. It searches and asks as
Topics does, and its filters keep the answers, what is for review, or the
topics' own changes.

You don't have to keep looking. When a topic is your turn again (it moved to
review, an agent answered you, or an item you rejected has a new version),
nock tells you once, however many items the burst brought, on the desktop, or
in the studio while it is open (its settings turn on the browser's
notifications for when it is away), and a click opens what it tells of. These
are the Timeline's own events. `notifications = false` turns it off.

## Verdicts

The verdict is the decision's: accepting it accepts its assets' current
versions; rejecting it asks for rework, as its thread says; dropping it
closes it, nothing to rework. An agent may write a verdict too (Tidy up drops
what is stale), and each says who wrote it, so you can reverse one. The
session that recorded a decision hears your verdict or message the next time
you type there, once; `nock inbox` gives any agent what you said that waits
on one. A new version of the decision or of one of its assets opens it again,
with its history beside it to compare. And when a later session edits a file
a decision's asset holds or shows, it's told which decision, the first time.

## Chatting

Every word goes through a chat: a topic's, a decision's, a file's, each
opened by the icon beside it. You leave a question on a decision, a comment on
a screenshot; your message waits for the agent's answer, and the agent answers
in that thread, with a new version when the comment asks for one.
Files dropped into a chat go with your message, and the microphone records
what you say and has it made text, by a Whisper server you name in the studio's
settings, for you to edit before you send.

You don't have to wait for a session to answer. Under your waiting message,
**Address now** sends an agent to answer it at once. **Address my
comments**, over the chat's composer while comments wait ("Address my 3
comments"), starts an agent that answers them all, each in its own thread, as
an agent working the threads would: a reply, a new version of the item, a
change to the project's files checked with the project's gate. It gives no
verdict and commits no code; the changes are left for you to look at.

**The chat** beside the settings gear talks with a headless agent session
in the project, from every tab. It reads the topics, the items and nock's docs,
and changes nothing. Chats are your conversations, not the project's records:
they stay on your machine, never committed.

## Tidy up

The topics get messy: items filed under the wrong topic, two topics that are one,
one that sprawls, statuses gone stale. **Tidy up**, at the end of the filters'
line, sends an agent to reorganize it, after a short confirm. It moves misplaced
items, merges near-duplicate topics and splits sprawling ones, sets each
topic's state and status from what is there, drops stale or superseded items
with a comment (it never accepts, nor asks for rework), and gives the open
topics a priority, a reason in each status. Its changes land as one commit,
"Topics tidied up: …", and **Undo** reverts it.

## The map and consulting

A queue of verdicts is also a record: what was chosen, what was rejected, and
why. nock turns it into the project's memory.

**The map**, `.nock/shared/map.md`, says what the topics and items mean for
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
