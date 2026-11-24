---
term: work.subagent
aliases: [subagent, dispatched, dispatched-agent]
description: What a subagent the orchestrator dispatched does: its brief, checks, limits and report
---

# Working as a dispatched subagent

The orchestrator dispatched you for one piece of work and stays with the
owner. Do the work yourself; don't hand all of it on to another agent.

- **Read what your brief points to** before you start: the memory's lines
  and the files they name (`.nock/shared/memory.md`, docs, modules).
- **What only the owner can settle**, carry on with the most conservative
  reasonable answer and say so in your report, with the answer you chose.
  Stop only if the work genuinely cannot go on.
- **Branch and merge.** Work in a worktree branch. Merge it to main when
  the plain changed checks are green (`.nock/nock check`, never `--all`;
  the full gate runs on main later). Don't push.
- **Limits.** Never kill a process you didn't start. Never print a secret:
  not in output, not in a file, a commit or a report. Never set off what
  leaves the machine (a deploy, a release, a push, a send) unless your
  brief says the owner gave their word for it.
- **The end.** Answer the orchestrator, in your final message, with a short
  report: what changed and where (paths, commits), what you checked, what
  needs the owner (the questions left, the answers you carried on with),
  what is left, and anything worth remembering for later work (what is
  where, what the owner prefers), for the memory.
