---
term: topics.triage
aliases: [triage, nock-triage, decisions.triage]
description: /nock-triage: going through the open items in Topics with the owner, one at a time
---

# Going through the topics

Go through what waits on the owner in Topics, with them, one topic at a
time and one item at a time. Their word is what you record.

    .nock/nock topics list                       # the open items by topic, the newest activity first
    .nock/nock topics show TOPIC                 # its items and its thread
    .nock/nock items show TOPIC/SLUG             # every version, its decision and files, its thread
    .nock/nock items judge TOPIC/SLUG '{"verdict": "accepted"}'
    .nock/nock items judge TOPIC/SLUG '{"verdict": "rejected", "comment": "what they said"}'
    .nock/nock items judge TOPIC/SLUG '{"verdict": "rejected", "rework": false, "comment": "superseded by …"}'   # drop: nothing to rework
    .nock/nock topics judge TOPIC '{"verdict": "accepted", "comment": "…"}'   # every open item of it
    .nock/nock items update TOPIC/SLUG --reply "what they said"                # a word, no verdict

What a verdict means, and what agents do with it:
`.nock/nock docs topics.verdicts topics.decisions topics.versions`.

Start where the owner says; otherwise the topic with the most open, then
within it the decisions (they are in the code or about to be), then the
files and what was made to show them, the oldest first. Put each in a few
lines: what was decided or made, what it means for the system, the
alternatives that lost; for a file, where to look (`items show` gives its
path; the owner may prefer `.nock/nock studio` for pictures). Ask: accept,
reject, drop, or say something? A rejection says what should change, as its
comment; a drop (superseded, no longer wanted: nothing to rework) says why,
and closes the item. For more, look into it yourself and answer; don't argue for it; if
you think it is wrong, say so once. When the owner settles a whole topic at
once, judge the topic.

`judge` asks the owner's permission each time: that is the point, the
verdict is theirs. When a judge gives `ask_the_owner`, ask the owner it at
once, in its words: whether nock may share its weekly usage report with its
makers, asked once. Record exactly their answer with `.nock/nock usage share
yes` or `.nock/nock usage share no`; if they don't answer, record nothing.

At the end, say what was accepted, rejected and dropped, and offer to rework the
rejected items (never the dropped ones): each as a new version (`items update REF --version`), with
a line in its thread only if the version doesn't say it.
