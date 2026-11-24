---
term: logika.instrument
aliases: []
description: "The logika.instrument lead's brief: split the code into areas, an agent each, then report"
---

# The logika.instrument subround

Start the run with `.nock/nock reflect logika.instrument`, or pick up the one under way: it prints the run's material, its agents with their briefs, the files to write and the submit.

You lead it: the parts instrument the code and write its rules, an area
each; you split the code, check their work as a whole, report and submit.
Whatever this session was doing waits. The owner settles only general
directions and genuine ambiguities, and reviews the rest in your report.

1. **What is owed first.** The last run's rules that fired on normal
   behaviour (`logika query` shows them): fix them or take them out.
2. **Split.** The material is `logika map` when the run started: its
   directories, their open items and the reasons earlier runs gave. Split
   the code into areas, each a component's directory or a part of a large
   one; after the first run, only the areas with open items or changed
   since. The parts instrument every unit of work in their area, not only
   the listed items: the map is a meter, not the plan.
3. **Dispatch** one `logika-instrument` subagent per area, all in one
   message, in the background. Tell each its area, which it owns with
   everything beneath it; the material's path; that in `logika.json` it
   adds and changes only its own entries, reading the file again right
   before each edit; and, by `logika.json`'s `config.questions`, what to do
   with what is in doubt: `"ask"`, bring the question back with its
   recommendation; otherwise take the answer it recommends and list it as
   a decision in its report. If a part fails, say so in the report rather
   than doing its area yourself.
4. **Ask** the owner the questions the parts brought back, a few at a time,
   each with the rule it settles and the answer you propose; carry on with
   your answer meanwhile.
5. **As a whole.** Write the rules the parts brought back that relate one
   area's events to another's. `logika check` passes. `logika map` again:
   an area that left items open without a reason goes back to its part, or
   to a new one, once. Then the noise check, once (`logika docs replay`): `logika test
   "<command>"` over the tests and what traffic you can run, then `logika
   replay '{"on": "capture"}'`. A test raises errors on purpose: one we
   would want to know about stays an error; an ordinary user mistake
   becomes an outcome. What fires on normal behaviour is fixed; where the
   docs or copy state the promise it breaks, the rule stands and what it
   fires on is a known issue.
6. **Write `report.md`** for the owner: the rules added, each with the
   event it reads; the events and params added; the items left open, with
   their reasons; the decisions the parts took on what was in doubt; what
   the noise check fired on and what you did; the known issues.
7. **Submit** once, from what the parts reported: a change per rule and
   per event instrumented, and each reason a change of kind `reason`, its
   target the item (`silent <file> <function>`, `verdicts <event>`,
   `unread <event>`) and its `why` the reason. Kinds: validate, path,
   timeout, rule, invariant, error, reason, instrumentation, other;
   `tested`, what showed a change, is optional. It requires the ledger to
   parse and commits `logika.json` and the record. Before it, mark each
   component the parts covered `instrumented`, and commit the code they
   changed, saying what it now logs.
8. **Report** the subround in your final message: what is now covered, what
   was left open and why, what waits on the owner, and where `report.md`
   is. Production is judged against the new rules once `logika sync`
   deploys the ledger, which is the owner's to run.
