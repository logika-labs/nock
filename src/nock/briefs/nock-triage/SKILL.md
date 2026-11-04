---
name: nock-triage
description: Go through the decisions nock's agents recorded with the owner, one at a time, here in the conversation, recording their accept, reject or note. Use when the owner wants to review decisions, or says /nock-triage.
---

# Going through the decisions

Go through the decisions waiting on the owner, with them, one at a time.
Their word is what you record.

    .nock/nock decisions list '{"review": "unreviewed"}'   # or '{"tag": …}', '{"path": …}'
    .nock/nock decisions show 7
    .nock/nock decisions edit '{"number": 7, "review": "accepted"}'
    .nock/nock decisions edit '{"number": 7, "review": "rejected", "note": "what they said"}'
    .nock/nock decisions edit '{"number": 7, "note": "what they said"}'
    .nock/nock decisions delete 7    # only when the owner says it should not have been recorded
    .nock/nock decisions batch '{"edit": [{"number": 7, "review": "accepted"}, …], "delete": [9]}'   # many, one commit

What each review means for a done decision and a todo:
`.nock/nock docs decisions.review decisions.todos decisions.important`.

Start where the owner says; otherwise those tagged `important` first (the
owner's calls, which agents carry on with as proposed until reviewed), then
done decisions (they are in the code), then todos, then the oldest. Put
each in a few lines: what was decided, what it means for the system, the
alternatives that lost. Ask: accept, reject, a note, or more? Rejected, a
note says what holds instead. For more, look into it yourself and answer;
edit the decision if it should say so too. Don't argue for it; if you think
it is wrong, say so once.

When an edit gives `ask_the_owner`, ask the owner it at once, in its
words: whether nock may share its weekly usage report with its makers,
asked once. Record exactly their answer with `.nock/nock usage share yes`
or `.nock/nock usage share no`; if they don't answer, record nothing.

At the end, say what was accepted and rejected, and offer to rework the
rejected done ones; edit each to say what was done.
