---
name: nock-reflect-logika
description: Run a logika round in a Logika project. Two parts - rules (what must hold - validations, paths, timeouts, rules, invariants, error marking, each proved quiet on real captures, firing on a replay and firing on the breach planted in the code) and analytics (identities, dimensions, funnels, milestones, views) - adding the instrumentation either needs. Run it when the owner asks, or agrees when nock says a round is due.
---

# A logika round

The owner asked for this round. Its job is to write down in `logika.json`
how this system is expected to behave, so that Logika wakes an agent when it
doesn't and stays quiet when it does, and what is worth measuring, so that
Logika's analytics answer the owner's questions from real captures. You
decide what lands, from the code, the docs, the copy users see and the data;
the owner settles only general directions and genuine ambiguities, and
reviews the rest in your report, after the round rather than before each
rule. Whatever this session was doing waits.

Done when: the rules and declarations you decided on are in `logika.json`,
each rule proved quiet, firing on a replay and firing on its breach planted
in the code; the instrumentation they need is in the code; `logika check`
passes; and `.nock/nock reflect logika finish` has recorded the round.

1. `.nock/nock reflect logika` prints the round's two material files and
   the report you write. The material shows what the ledger already says
   and measures, per component, event and param, what changed since the
   last round, and the decisions and suggestions earlier rounds left.
2. Start with what is owed:
   - the decisions the owner rejected or left a note on: act on each, then
     edit it to say what you did;
   - the last round's rules that raised false alarms: fix them or take them
     out (`logika query` shows them).
3. Dispatch the two parts as subagents, in one message, each of its type
   (in `.claude/agents/`). Give each its brief (beside this file), its
   material and the round's window. They read and run commands but change
   nothing, so both can work over the tree at once while you keep it: each
   comes back with candidates (each with its evidence and how it was
   checked), the instrumentation each candidate needs, for a rule the breach
   to plant in the code, and the few questions only the owner can settle.

   | part | subagent type | brief | material | proposes |
   |---|---|---|---|---|
   | rules | `nock-logika-rules` | `rules.md` | `rules` | validate, paths, timeouts, rules, invariants, error marking |
   | analytics | `nock-logika-analytics` | `analytics.md` | `analytics` | identities, dimensions, funnels, milestones, views |

   The rules part derives the product's promises itself, across every
   user-facing area rather than where the instrumentation is densest, and
   mines the clean captures for what they missed; each candidate names the
   promise it guards and the breach it catches. For a large project it may
   take one component at a time. If a part fails, say so in the report
   rather than doing its part yourself: its brief is what makes it careful.
4. Clear with the owner only what you can't settle yourself: a general
   direction (which areas matter most, what a whole class of failure means
   to them) or a genuine ambiguity, where the docs, the copy, the tests and
   the code's intent leave the intended behaviour open. Ask a few at a time,
   each with the rule it settles and the answer you propose, and carry on
   with your answer meanwhile; if they would rather answer later, record it
   as a decision (`.nock/nock decide '{"status": "done", "tags": ["logika",
   "important"], …}'`, your answer as the title; `.nock/nock docs
   decisions.important`). Thresholds aren't questions: they come from the
   data, with the margin you chose stated in the rule's evidence.
5. Add the instrumentation the candidates need, as the logika-instrument
   skill's common cases describe (`logika docs instrument`): the raw input a
   decision read beside its outcome, an effect's real result, the id it
   acted on, a step as a child event. Change the code and the ledger
   together, keep every existing event and param, run `logika check`, then
   capture again (`logika test "<the command that exercises it>"`) and see
   the new fields filled. Commit it on its own (the code and the ledger),
   saying what the code now logs.
6. Write the rules you decided on, most important first: money, stock,
   access, and anything else that changes shared state. Each carries its
   one-sentence `description` (the anomaly's title) saying what must hold
   and why. Prove each three ways, and record all three in its `tested`:
   - **quiet**: `logika test` on the clean behaviour raises nothing, and a
     query counts no existing row that breaks it;
   - **firing on a replay**: `logika test --replay` with the breach raises
     exactly this anomaly, with evidence an agent could act on;
   - **firing on the breach in the code**: plant it where the subagent
     said (flip the condition, drop a part of the key, skip the retry,
     report the failure as a success), run `logika test` again and see this
     rule fire, then revert it (`git diff` shows only your intended
     changes). This is what shows the rule catches the bug and not only the
     data's shape; a rule the planted breach doesn't fire is reworked or
     dropped.
   The common cases:
   - a rule that fires on today's behaviour, where the docs or copy state
     the promise, usually lands, with what it fires on reported as a known
     issue (or the code fixed): loosening it to fit would encode the bug;
   - a rule one form of Logika refused is usually tried in an equivalent
     form before it's dropped;
   - in doubt about whether a rule would fire on normal behaviour, it
     waits: a missing rule costs nothing until the day it would have fired,
     a false alarm costs the owner's trust every time.
7. Run `logika check` until it passes. Write the report for the owner, as
   what you decided, for them to review:
   - the rules you added or changed, with the evidence for each, the margin
     behind each threshold, and how each was proved, the planted breach
     included;
   - the instrumentation you added, and the rules it made possible;
   - what is now measured, and the questions it answers;
   - what you left out, and why;
   - the directions and ambiguities you settled, the answers you got or
     the ones you chose;
   - the known issues today's behaviour breaks.
8. Finish:

       .nock/nock reflect logika finish '{"summary": "the round in a sentence or two",
         "changes": [{"kind": "validate", "target": "refund", "why": "the evidence",
                      "expect": "what it should catch, and that it stays quiet otherwise",
                      "tested": "silent on <capture>; fired on <replay>; fired with <breach> planted in <file>"},
                     {"kind": "instrumentation", "target": "refund", "why": "the rule it made possible",
                      "expect": "the field filled on every sighting", "tested": "the capture that shows it"},
                     {"kind": "funnel", "target": "activation", "why": "the question it answers",
                      "expect": "what it should show", "tested": "the captures that carry it"}],
         "verdicts": [{"expectation": "…", "held": true, "evidence": "…"}],
         "notes": "what the next round should look at"}'

   The kinds are validate, path, timeout, rule, invariant and error (the
   rules, each with how it was `tested`), instrumentation, identity,
   dimension, funnel, milestone and view (the analytics), and other. The
   verdicts cover the last round's expectations. Finishing commits `.nock/`
   and `logika.json`; nock says what a round left open still needs
   (`.nock/nock docs reflection.kinds`).
9. Tell the owner in a few lines what changed, what you decided that they
   may want to look at, and where the report is. If `reflect logika` gave
   `ask_the_owner`, ask them that too, in its words, and record exactly
   their answer with `.nock/nock usage share yes` or `no` (nothing if they
   don't answer). Production is judged against the new rules, and measured
   by the new declarations, once `logika sync` deploys the ledger, which is
   the owner's to run.
