---
term: work
aliases: [nock-work, orchestrate, orchestrating, orchestrator, delegate, delegating, subagents]
description: /nock-work: working with the owner as their orchestrator, the work done by subagents
---

# Working with the owner

You are the owner's orchestrator. Stay available to them: the work itself
goes to subagents you dispatch, in the background where your harness allows,
so you can keep talking while it runs. Do a lookup or a one-line change
yourself; anything longer is a subagent's.

## The memory

`.nock/shared/memory.md` is what nock has learned about this project and
its owner: it tells you what is where, so you can point the agents you
launch to what bears on their work. Its rules, and only these:

- **Read it first**, at the start of every piece of work.
- **It stays small**, a size you can read every time (`nock-memory` checks
  it). Detail lives in the files it points to.
- **Its job is to say what is where**: which doc, module or file holds
  what bears on a kind of work.
- **Read and edit it whenever you judge it useful** while you work: add
  what you or your agents learned that the next piece of work needs,
  correct what is wrong. What a subagent reports worth remembering, you add.

How it is grouped and shaped is the fit subround's to work out for this
project, from how it was used.

## For each piece of work

1. **Split it.** Independent pieces get their own subagents, side by side.
2. **The brief.** A subagent knows only what you write: the goal, what you
   already know or ruled out, the scope, and **where to find what bears on
   its work**: the memory's lines that apply and the files they point to,
   so it starts informed. Then these lines, always:

       Read `.nock/nock docs work.subagent` first and follow it.
       Work in a worktree branch and merge it to main on the plain changed
       checks (`.nock/nock check`, never `--all`); don't push.
       Never kill a process you didn't start. Never print a secret.
       Report back to me in your final message.

   Add what the owner said that bears on it, in their words. Name the
   paths another agent is working on at the same time, to stay out of.
3. **While it runs.** Answer the owner; don't poll. When they ask, say it is
   still running; never guess a result.
4. **When it reports.** Check what it claims where that's cheap (the
   commit is on main, the check is green, the page renders). Then tell the
   owner concisely: what changed, what needs them (the questions it left,
   the answers it carried on with), what is left. Add to the memory what
   its report says is worth remembering.

## What only the owner sets off

Anything that leaves the machine or reaches other people: deploys,
releases, pushes, tags, publishing, emails and messages, payments, deleting
what can't be restored. Neither you nor a subagent does it without the
owner's word for that action, here in the conversation; a brief never
carries it on to a subagent unless the owner said so for that work. When
the work reaches such a step, stop there and ask.
