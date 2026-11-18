---
term: guide.review
aliases: []
description: Agents put their work before you as tasks and never wait; you review each when it suits you
---

# Review on your time

An agent at work makes calls all the time. Most are routine, some matter to
you: requeue dead charges or failed ones too, refund the whole order or the
item. The obvious design is to have the agent stop and ask. It doesn't scale:
you become the bottleneck, every agent idles until you answer, and you answer
in a hurry, out of context.

nock turns it around. The agent goes ahead, and puts what it did before you
as a **task**: what it decided, what it proposes, the files that show it, and
a page telling the story. You look at it when it suits you, and you know at a
glance what changed, what it means for you, and what needs you.

## Tasks

A task is a stream of work, with a name, a line on why it exists, a **state**
(planned, active, review, done or abandoned), a **status** the agent keeps
current, and a **plan**: the steps it registered with their estimates,
marked started and done as it goes, so the task shows a progress bar, the
current step and the time left. Tasks are files in the repository,
`.nock/shared/topics/` (a task is a topic in nock's files), one event per
file; agents write them with their own tools, and nock checks each file,
fills in when and who, and commits it on its own.

A task holds three kinds of thing:

- **Decisions**: what the agent decided and carried on with. A title saying
  what was decided, and a line or three on what it means for you — what
  users see, what it costs, what is now harder — and maybe why. No
  alternatives, no essay.
- **Proposals**: what the agent wants done and would not do on its own. The
  same, plus roughly what it takes. You **accept** one (the agent carries it
  out at its next look at its inbox, and it then reads as a decision, with
  what was done) or **reject** it (it is dropped from the review, kept in the
  history). Nothing else takes a verdict.
- **Assets**: files, versioned. A project file is linked at the commit that
  last changed it; a derived file (a screenshot, a rendered page, a video) is
  kept with how to make it again. Version 1 the before, version 2 the after:
  the review shows them as a diff.

```sh
.nock/shared/topics/charge-sweep/
  events/…json                       {"kind": "created", "description": "The nightly sweep of failed charges."}
                                     {"kind": "plan", "steps": [{"title": "Requeue logic", "estimate": 40}, …]}
  items/dead-only/events/…json       {"kind": "created", "type": "decision", "title": "The sweep requeues dead charges only",
                                      "means": "A card that failed for funds is retried by the bank, not us."}
  items/notify/events/…json          {"kind": "created", "type": "proposal", "title": "Email the customer on the third failure",
                                      "means": "…", "takes": "a template and a hook, half a day"}
  assets/lapsed-email/versions/2/    asset.json {"file": {"kind": "derived", "name": "lapsed.png", "recipe": {…}}}
  review/versions/1/review.json      {"summary": "…", "blocks": [ … ]}
```

## The review

The review is the task's main page. The agent composes it when the work is
built, from **blocks**, as a story: a few sentences on what changed for you,
then each part with what shows it — a decision or a proposal inline with its
controls, a diff of a prompt or a schema, an excerpt of a long file, a
screenshot, a table or a chart of the numbers, and, for what nothing
built-in shows, a small page of its own (an html block, sandboxed, which can
leave notes and accept or reject like the rest). Under the review, the
task's other decisions and proposals are listed, open ones first, then its
assets, with the same controls. When the work changes, the agent writes a
new version of the review.

The agents follow `nock docs review` to compose it, and the project's own
preferences, which reflection learns from your notes and from what you skip:
the more you review, the better the reviews fit you.

## What you do

The minimum:

- **Accept** or **Reject** a proposal.
- **Note** an item or an asset, wherever it shows, or a block of your
  agent's own page. A note is a draft, pinned where you left it.
- **Send** a message in the task's one chat. It carries all your unsent
  notes, each pointing at what it is on, and asks for an answer now; it may
  be empty ("go through my notes and redo"). An agent waiting on its inbox
  gets it at once; otherwise nock starts one in the background to answer,
  and the chat shows it working — its reasoning and each command, as it
  goes. Its reply is a short summary, which can show things (an item, a
  diff, a chart) rather than only describe them. Notes you leave without
  sending are context for the agent's next reply.
- **Done** on the review: every decision you left no note on counts as fine.
  With nothing left for agents, the task is done.

## The studio

`nock studio` serves your page on your machine. The Topics tab lists the
tasks, each a row with what it holds, what waits on you, its plan's
progress (`3/5 steps · ~20 min left`) and its status; a row opens in place
on its review, and its chat floats from its corner. Filters keep what needs
you, what waits on an agent, what is to do or active; a search marks what it
finds. An asset opens in a viewer that compares its versions. The Timeline
tab is everything that happened, newest first. The page updates as agents
write.

**Notifications** keep a history of every change, in the Timeline: an
item added or revised, a review ready, a reply in the chat, a task changing
state. When a task is your turn (its review is ready, an agent answered you,
or proposed something), nock tells you once per burst: in the studio while
it is open, through the browser's notifications when you turn them on, on
the desktop when no page watches (`terminal-notifier`, if installed, opens
the place on a click). Turn them on in the studio's settings;
`notifications = false` turns them off.

A **round** that is due shows as one quiet button beside the filters (see
[Agents that build their own tools](#agents-that-build-their-own-tools)):
behind it, how often it comes, and Run, which starts it in the background,
its result a task like any other; or In a week, or Never. Work under way
shows as a small toast, with Stop.

## The memory

What is decided is also a record. `.nock/shared/memory.md` is the one place
for what nock has learned about the project and you: short lines saying what
is where, each pointing to the task, item or doc with the detail. The agent
you work with reads it first and points every agent it launches at the lines
and files that bear on its work, so a decision you settled a month ago
reaches the agent about to undo it. It stays small; the fit round keeps it,
reshaping it from how it was used, and you can read and edit the file
yourself.
