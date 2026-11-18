---
term: topics.triage
aliases: [triage, nock-triage]
description: /nock-triage: going through what waits on the owner in their tasks, here in the conversation
---

# Going through the tasks

Go through what waits on the owner, with them, one task at a time: the
open proposals and the reviews not done. Their word is what you record.

    .nock/local/views/index.md                   # every task, what waits, in the owner's order
    .nock/local/views/TOPIC.md                   # its decisions, proposals, assets, review, chat

Start where the owner says; otherwise the task with the most waiting. Tell
each review as its blocks do, briefly: what was done and what it means for
them, the decisions in a line each; then each open proposal, what it would
do and what it takes. Ask: accept, reject, or a note? Where to look at
pictures: the studio (`.nock/nock studio`).

Record each word as an event (any name ending `.json`):

    topics/TOPIC/items/SLUG/events/      {"kind": "verdict", "verdict": "accepted"}     # a proposal only
                                         {"kind": "verdict", "verdict": "rejected"}
    topics/TOPIC/events/                 {"kind": "note", "on": {"item": "SLUG"}, "text": "what they said"}
                                         {"kind": "reviewed", "version": N}            # Done on the review

A decision takes no verdict: what the owner says about one is a note. Notes
stay pinned as drafts, context for the next agent that works in the task;
the owner sends them for an answer now from the studio. The word is theirs: write only what
they said; each event says it was you who wrote it.

If nock has not asked them yet (`.nock/nock config share` says it is
unanswered), ask them at the end, in its words: whether nock may share its
weekly usage report with its makers, asked once. Record exactly their
answer with `.nock/nock config share true` or `false`; if they don't
answer, record nothing.

At the end, say what was accepted and rejected, and offer to carry out the
accepted proposals now.
