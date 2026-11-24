# The logika.analytics subround

You lead it: its job is to declare in `logika.json` what is worth
measuring, so Logika's analytics answer the owner's questions from real
captures. Whatever this session was doing waits. The owner settles only
general directions and genuine ambiguities, and reviews the rest in your
report.

1. Dispatch the `logika-analytics` subagent with its material (below) and
   the run's window. It reads and runs commands but changes nothing: you
   alone write `logika.json`. If it fails, say so in the report rather than
   doing its part yourself.
2. Ask the owner only what you can't settle yourself, a few at a time, each
   with the declaration it settles and the answer you propose; carry on
   with your answer meanwhile.
3. Write what it brought back into `logika.json`: identities, dimensions,
   funnels, milestones, views (`logika docs analytics`). Where a
   declaration needs a param the code doesn't log, add it to the code and
   the event, keep every existing event and param, and commit it on its
   own, saying what the code now logs. `logika check` passes.
4. Write `report.md` for the owner: what is now measured and the questions
   it answers, the instrumentation added, and the directions you settled.
5. Submit with `"subround": "logika.analytics"` and its changes (identity,
   dimension, funnel, milestone, view, instrumentation, other); `tested`,
   the captures that carry it, is optional. It requires the ledger to parse
   and commits `logika.json` and the record.
6. Report the subround in your final message: what is now measured, what
   waits on the owner, and where `report.md` is.
