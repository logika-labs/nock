---
term: guide.why
aliases: [guide.about, guide.origin]
description: Why nock exists: the usual problems of AI engineering, the queue it grew into, and an experiment
---

# Why nock

As I started working with AI engineering, I started experiencing the usual
problems: agents struggling with specific tasks, making decisions on their
own and over-engineering, being unable to keep on top of the volume, and so
on.

nock was born out of necessity this way: as a CLI framework and a reflection
round that makes it easy for agents to periodically reflect on their work
and add more agent-friendly commands for themselves in the future.

## Code, not prose

The usual fix for an agent that keeps stumbling is prose: a skill, a note, one
more rule in CLAUDE.md. I wrote a lot of those, and they have two problems.
They go stale without anyone noticing: when the code moves on, a paragraph
that no longer fits still reads as true. And they are read differently every
time: an agent can follow one, skip it, or half-apply it, and nobody can tell
which.

A command is different. When it no longer fits the project, it breaks: it
exits non-zero, a check fails, and the failure is recorded. So a toolbox can be
kept honest by measuring it, and that became the rule nock lives by:

> **A check beats a hook beats prose.**
>
> A rule that a check enforces cannot be ignored. A behavior that a hook
> triggers cannot be forgotten. Prose is the last resort.

So nock records every session on your machine, and every so often an agent
reads that record and changes the toolbox: a command for the chore that keeps
costing turns, a fix for the one that misbehaves, the retirement of the one
nobody calls. How that works is in [Agents that build their own
tools](#agents-that-build-their-own-tools), and what makes a command easy for an
agent to use is in [A CLI agents can use](#a-cli-agents-can-use).

## A queue instead of a task manager

To keep track of work, I created a central queue into which the agent could
submit its decisions: first in the form of potentially blocking questions.
But then I found that it's better to let it work, submit decisions for me to
review, and discuss them with it on demand, and to use the established corpus
for a special "consult" procedure, whereby the agent, as it makes decisions,
makes sure it's aligned with decisions that were already made.

I wanted to avoid a complex task management system, so I realized it's
simplest to group these decisions by topics, which I can manipulate in bulk,
search through, see progress on and so on.

Then I also realized that other generated artifacts I'd like to review by
hand, like skills, microcopy, and things like UI interfaces or emails that can
be rendered into images or interactive videos, should also be submitted for me
to review in the same queue, with convenient ways for me to leave a comment
on further work, compare different versions, choose amongst several options
and so on.

That queue is the studio's Work tab, and the whole of it is in [Review on your
time](#review-on-your-time).

## Choosing between agents

The more agents I ran, the more my questions turned into comparisons. Is the
new skill better than the old one? Does this model catch more bugs, or just
cost more? Before, the hard part of a project was people: programmers with
different preferences, agendas and egos. Now I can dispatch several agents to
explore different options, and the hard part becomes tracing what they did
and judging it, to choose the best way forward.

Agents' work takes time, costs money and isn't deterministic, so I built the
kind of tool I needed myself: an experiment drawn as a graph of stages, every
stage cached, so I pay only for what changed, and every run there to open up
and look at. It's how I measure how well Logika instruments code and catches
bugs, and it's in [Evaluations](#evaluations).

## An experiment

I developed nock while developing [Logika](https://logika.host), to handle the
scope of that project and its complexity. Logika's agents keep their own
toolbox and submit their work to me in topics, and in a Logika project nock
runs a second kind of reflection round, which writes the rules that catch bugs
before they happen ([nock in Logika](#nock-in-logika)).

I'm generally curious about the future of programming and AI engineering, so
nock is meant as an experiment. What would open source look like in the age of
AI? It's no longer just code that's worth sharing, but what agents learn while
working with it. How do we share insights into programming with AI, and grow a
community around them?

nock starts small there. A reflection round ends with a summary of what it
learned, written so that nobody could tell which project it came from, and
asks you whether to send it to nock's makers. When nock lacks something, your
agent offers to tell us, in your words, with `nock report`. Nothing leaves your
machine without your yes ([What nock shares](#what-nock-shares)). Everything
else is in your repository: nock is vendored into it as plain,
dependency-free Python, so your agents can read it, and fix it if they must.

If you want to try it, [Setting up](#setting-up) takes a few minutes.
