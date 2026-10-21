---
name: nock-triage
description: Go through the decisions nock's agents recorded with the owner, here in the conversation — one at a time, accepting, rejecting, noting or elaborating as they say. Use when the owner wants to review decisions, or says /nock-triage.
---

# Going through the decisions

The agents working on this project record their decisions as they make them,
and the owner reviews them. You are going through them with the owner now,
in this conversation. Their word is what you record; yours is the summary.

1. `.nock/nock decisions list '{"review": "unreviewed"}'` lists what waits on
   the owner. Take the done ones first — they are in the code already — then
   the todos; within each, the ones tagged `important` first, then the
   oldest. If the owner named a tag, a file or a number, start there instead
   (`'{"tag": …}'`, `'{"path": …}'`).
2. For each, `.nock/nock decisions show N`, and put it to the owner in a few
   lines: what was decided (or should be done), what it means for what the
   system does, and the alternatives that lost and why — only the evidence
   that bears on whether it is right. Then ask: accept, reject, a note, or
   more? Do not argue for it; if you think it is wrong, say so plainly once.
3. Record their word:

       .nock/nock decisions edit '{"number": N, "review": "accepted"}'
       .nock/nock decisions edit '{"number": N, "review": "rejected", "note": "what they said"}'

   A note on its own needs no review. When they want more, find it — read
   the code, the history — and answer them here; if the decision should say
   it too, edit its `summary`, `evidence` or `alternatives`. When they would
   rather an agent looked into it while you move on,
   `'{"number": N, "elaborate": true, "note": "their question"}'`. When they
   want to skip one, skip it.
4. Stop when they say so, or when nothing waits. Then say in a line or two
   what was accepted and rejected. A rejected done decision is to be
   reworked: offer to do it now, and when it is done, edit the decision to
   say what was done instead.
