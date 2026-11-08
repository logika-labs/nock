---
term: guide.why
aliases: []
description: Why nock: agents repeat themselves, prose goes stale; the fix is code, and its three principles
---

# What changes for you

After `nock init` and a commit, your agents work as before, and four things change:

- **Every session is recorded,** on your machine: what you asked, each tool call, what
  failed, what it cost (see [Telemetry](#telemetry)).
- **Agents put their work before you** in topics: the choices they made, the files they
  changed, what they made to show it. They never wait on you; you review in the studio's
  Work tab when it suits you (see [Reviewing in Work](#reviewing-in-work)).
- **Every week or so, a reflection round** reads the record and improves the toolbox: tools
  for the work that keeps costing turns, repairs, retirements (see [Reflection
  rounds](#reflection-rounds)).
- **The toolbox grows,** `.nock/nock` lists it at every session's start, and your tests and
  linters become the gate it must pass (see [Install](#install)).

## Why

Agents repeat themselves:

- they run the same five shell commands to find out why a test fails;
- they write the same throwaway script to query the database;
- they pipe the same noisy output through `tail`;
- they trip over the mistake the human has already corrected twice.

Every repeat costs turns and tokens, and every session starts again from
nothing.

The usual fix is prose: skills, notes, rules in CLAUDE.md. Prose has two
problems:

- **It goes stale without anyone noticing.** When the code moves on, a
  paragraph that no longer fits the project still reads as true.
- **It is read differently every time.** An agent can follow it, skip it, or
  half-apply it, and nobody can tell which.

nock's fix is code. A command that no longer fits the project **breaks**:
it exits non-zero, a check fails, and the failure is recorded. So the toolbox
can be kept honest by measuring it. That is also the rule nock lives by:

> **A check beats a hook beats prose.**
>
> A rule that a check enforces cannot be ignored. A behavior that a hook
> triggers cannot be forgotten. Prose is the last resort.

## Three principles

1. **An agent-friendly CLI.** Every byte a command prints is read by a model
   and paid for, so:
   - a command prints what the next decision needs, in the cheapest format
     that reads accurately;
   - success is often silence: a passing check prints nothing, and its exit
     code says so;
   - the exit code says what to do next: change the request, fix the code, or
     fix the machine;
   - a mistake gets an answer, not just a refusal: "did you mean", the
     expected shape of the input, a path to the full log.
2. **Every run recorded.** Every call to nock is recorded locally: its
   arguments, duration and exit code, and how much the agent had to read. So
   is every Claude Code session: what the human asked, each tool call the
   agent made (nock or not), what failed, and what it cost. You cannot
   improve what you have not measured, and agents do not remember.
3. **Reflection.** Every so often, an agent reads that record and improves
   the toolbox:
   - it builds tools for the work that keeps costing turns and tokens;
   - it repairs and retunes the tools that misbehave;
   - it retires the tools nobody uses.

   It starts from the big picture, not just the numbers: what the human has
   been asking for, and where the code is going. It writes down what it
   expects each change to do, and the next round holds it to that. What it
   builds is live on the next call.

## A framework, not a library

A tool's author writes only what the tool does. nock owns everything around
it, the way a web framework owns HTTP or pytest owns setup and teardown:

- parsing the arguments and checking the input;
- rendering the output, and capping it;
- exit codes and error reports;
- running processes under supervision;
- caching;
- telemetry;
- help text.

That matters most when an agent writes tools for itself. It has to get only
the business logic right, and everything else comes out the same in every
tool.

nock is standard-library Python 3.12 and has no dependencies. It is vendored
into the project, so it is the project's own code: an agent can read it, and
fix it if it must. Tools that need the project's own packages run on the
project's interpreter instead (see [The project's environment](#the-projects-environment)).
