---
term: topics.triage
aliases: [triage, nock-triage]
description: /nock-triage: going through the open items in Topics with the owner, one at a time
---

# Going through the topics

Go through what waits on the owner in Topics, with them, one topic at a
time and one decision at a time. Their word is what you record.

    .nock/local/views/index.md                   # every topic, its open decisions, in the owner's order
    .nock/local/views/TOPIC.md                   # its decisions, their answers and assets, its thread

Record each word as an event in the decision's `events/`, in
`.nock/shared/topics/TOPIC/decisions/SLUG/events/` (any name ending `.json`):

    {"kind": "verdict", "verdict": "accepted"}
    {"kind": "verdict", "verdict": "rejected", "comment": "what they said"}
    {"kind": "verdict", "verdict": "dropped", "comment": "superseded by …"}    # nothing to rework
    {"kind": "message", "text": "what they said"}                              # a word, no verdict

An asset with variants takes the owner's pick first, a `preferred` event in
its own `events/`: `{"kind": "preferred", "version": N, "name": "b.svg"}`.

What a verdict means, and what agents do with it:
`.nock/nock docs topics.verdicts topics.decisions topics.versions`.

Start where the owner says; otherwise the topic with the most open, then
within it the decisions that are in the code or about to be, then those
about what was made to show them, the oldest first. Put each in a few
lines: what was decided or made, what it means for the system, the
alternatives that lost; for an asset, where to look (the view gives each
file's path; the owner may prefer `.nock/nock studio` for pictures). Ask: accept,
reject, drop, or say something? A rejection says what should change, as its
comment; a drop (superseded, no longer wanted: nothing to rework) says why,
and closes the decision. For more, look into it yourself and answer; don't argue for it; if
you think it is wrong, say so once. When the owner settles a whole topic at
once, write the verdict on each of its open decisions.

The verdict is theirs: write only what they said, and each event says it was
you who wrote it. If nock has not asked them yet (`.nock/nock config share`
says it is unanswered), ask them at the end, in its words: whether nock may
share its weekly usage report with its makers, asked once. Record exactly their answer with `.nock/nock config share
true` or `.nock/nock config share false`; if they don't answer, record nothing.

At the end, say what was accepted, rejected and dropped, and offer to rework the
rejected decisions (never the dropped ones): each as a new version (`docs topics.versions`), with
a line in its thread only if the version doesn't say it.
