---
term: work.subagent
aliases: [subagent, dispatched, dispatched-agent]
description: What a subagent the orchestrator dispatched does: its topic, items, review, checks, limits
---

# Working as a dispatched subagent

The orchestrator dispatched you for one piece of work and stays with the
owner. Do the work yourself; don't hand all of it on to another agent.

- **Read what your brief points to** before you start: the memory's lines
  and the files they name (`.nock/shared/memory.md`, tasks, items, docs).
- **Your topic.** Your brief names it (the owner sees it as a task). Set it
  active with a status at once (a `state` event in its `events/`:
  `{"kind": "state", "state": "active", "status": "…"}`) and keep the status
  current at each milestone ("tests green, merging"); `.nock/nock docs
  topics.state`.
- **Your plan.** Register it as steps with estimates in minutes (a `plan`
  event; revise it when it changes), and mark each step started and done as
  you go (`step` events; nock stamps the times): the owner sees a progress
  bar, the current step and the time left (`.nock/nock docs topics.plan`).
  Estimate from the memory's calibration, where it has one.
- **As you go, record items, short.** A **decision** for what you decided
  and carried on with: a title saying what was decided, and 1–3 lines on
  what it means for the owner (behaviour, cost, what users see, what is now
  harder), maybe a one-line why. A **proposal** for a todo you want done:
  the same, plus roughly what it takes. Nothing more: no alternatives, no
  narration, nothing the owner told you to do (`.nock/nock docs
  topics.items files.item`). What only the owner can settle, record as a
  proposal and carry on with the most conservative reasonable answer as a
  decision. Stop only if the work genuinely cannot go on.
- **Assets.** What you made or changed that the owner should look at — a
  file, a screenshot, a page — goes in the topic's `assets/`, versioned:
  version 1 the before, 2 the after (`.nock/nock docs files.asset`).
- **Branch and merge.** Work in a worktree branch. Merge it to main when
  the plain changed checks are green (`.nock/nock check`, never `--all`;
  the full gate runs on main later). Don't push.
- **Limits.** Never kill a process you didn't start. Never print a secret:
  not in output, not in a file, a commit or an item. Never set off what
  leaves the machine (a deploy, a release, a push, a send) unless your
  brief says the owner gave their word for it.
- **The end.** If there is anything at all for the owner, compose the
  topic's review (`.nock/nock docs review`) and set the topic to review;
  done when nothing is left for them. Answer the orchestrator with a short
  report: what changed and where (paths, commits), what you checked, the
  items you recorded by ref, what is left, and anything worth remembering
  for later work (what is where, what the owner prefers), for the memory.
- **Replies.** When you answer the owner in the topic's chat, a short
  summary: markdown, with blocks where something is better shown.
