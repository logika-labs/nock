---
name: nock-triage
description: Go through the decisions nock's agents recorded with the owner, one at a time, here in the conversation, recording their accept, reject or note, and their answers to the agents' questions. Use when the owner wants to review decisions, or says /nock-triage.
---

# Going through the decisions

Go through the decisions waiting on the owner, with them, one at a time.
Their word is what you record.

    .nock/nock decisions list '{"review": "unreviewed"}'   # or '{"tag": …}', '{"path": …}'
    .nock/nock decisions show 7
    .nock/nock decisions edit '{"number": 7, "review": "accepted"}'
    .nock/nock decisions edit '{"number": 7, "review": "rejected", "note": "what they said"}'
    .nock/nock decisions edit '{"number": 7, "note": "what they said"}'

What each review means for a done decision, a todo and a question:
`.nock/nock docs decisions.review decisions.todos decisions.questions`.

Start where the owner says; otherwise questions first (an agent waits on
the answer), then done decisions (they are in the code), then todos,
`important` first, then the oldest. Put each in a few lines: what was
decided, what it means for the system, the alternatives that lost. Ask:
accept, reject, a note, or more? A question's title is the answer the agent
proposes: accepted is yes, rejected is no with a note saying what holds, and
a note alone answers in words. For more, look into it yourself and answer;
edit the decision if it should say so too. Don't argue for it; if you think
it is wrong, say so once.

When an edit gives `tell_the_owner`, tell the owner it at once, in its
words: it is what nock shares with its makers, said once.

At the end, say what was accepted and rejected, and offer to rework the
rejected done ones; edit each to say what was done.
