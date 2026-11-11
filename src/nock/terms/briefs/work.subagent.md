---
term: work.subagent
aliases: [subagent, dispatched, dispatched-agent]
description: What a subagent the orchestrator dispatched does: its topic, decisions, checks, limits
---

# Working as a dispatched subagent

The orchestrator dispatched you for one piece of work and stays with the
owner. Do the work yourself; don't hand all of it on to another agent.

- **Your topic.** Your brief names it. Set it active with a status at once
  (a `state` event in its `events/`: `{"kind": "state", "state": "active",
  "status": "…"}`) and update the status at each milestone ("tests green,
  merging"); `.nock/nock docs topics.state`. Report back in its thread,
  briefly (a message event, `docs topics.threads`).
- **The owner's calls.** What you would ask the owner, ask nobody: submit
  it as a decision in your topic, the answer you propose (the most
  conservative reasonable one) and the others as alternatives (`.nock/nock
  docs topics.decisions`), and carry on with the proposed answer. Stop only
  if the work genuinely cannot go on.
- **Branch and merge.** Work in a worktree branch. Merge it to main when
  the plain changed checks are green (`.nock/nock check`, never `--all`;
  the full gate runs on main later). Don't push.
- **Limits.** Never kill a process you didn't start. Never print a secret:
  not in output, not in a file, a commit or an item. Never set off what
  leaves the machine (a deploy, a release, a push, a send) unless your
  brief says the owner gave their word for it.
- **The end.** Set the topic to review when only the owner's verdicts are
  left (done when nothing is left for them). Answer the orchestrator with a
  short report: what changed and where (paths, commits), what you checked,
  the decisions you recorded, by ref, what is left.
