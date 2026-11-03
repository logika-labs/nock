---
name: nock-reflect-logika
description: Run a logika round with the owner, in a Logika project. Two parts - rules (what must hold - validations, paths, timeouts, rules, invariants, error marking, each tested against real captures and replays) and analytics (identities, dimensions, funnels, milestones, views the owner wants measured) - each suggesting the instrumentation the data lacks. Run it only when the owner asks, or agrees when nock says a round is due.
---

# A logika round

The owner asked for this round, and is here. Its job is to write down in
`logika.json` how this system is expected to behave, so that Logika wakes an
agent when it doesn't and never when it does, and what the owner wants to
measure, so that Logika's analytics answer their questions from real
captures. Set aside whatever this session was doing.

1. `.nock/nock reflect logika` prints the round's two material files and
   the report you write. The material shows what the ledger already says
   and measures, per component, event and param, what changed since the
   last round, and the decisions and suggestions earlier rounds left.
2. Start with what is owed:
   - the decisions the owner rejected or left a note on: act on each, then
     edit it to say what you did;
   - the last round's rules that raised false alarms: fix them or take them
     out (see `logika show`).
3. Dispatch the two parts as subagents, in one message, each of its type
   (in `.claude/agents/`: they read and run commands, and have no tool that
   edits a file). Give each its brief
   (beside this file), its material and the round's window. Neither can ask
   the owner anything, so each comes back to you with candidates, each with
   its evidence and how it was checked, with questions for the owner, and
   with the instrumentation it would suggest. Neither edits `logika.json`
   or commits.

   | part | subagent type | brief | material | proposes |
   |---|---|---|---|---|
   | rules | `nock-logika-rules` | `rules.md` | `rules` | validate, paths, timeouts, rules, invariants, error marking |
   | analytics | `nock-logika-analytics` | `analytics.md` | `analytics` | identities, dimensions, funnels, milestones, views |

   For a large project, the rules part may take one component at a time.
   If a part fails, say so in the report; don't do its part yourself.
4. Go through the candidates with the owner, most important first: money,
   stock, access, and anything else that changes shared state; then what
   they want to measure. Show each before writing it into the ledger. You
   decide what lands; a rule lands only once seen quiet on a real capture
   and firing on a replay, and each rule has its one-sentence `description`
   (the anomaly's title) saying what must hold and why.
5. Ask the owner what only they know, here in the session, a few questions at
   a time. Each question names the rule or declaration it would settle and
   the answer you propose. If they would rather answer later, or someone
   else has to, record the decision you propose and carry on with it:
   `.nock/nock decide '{"status": "done", "tags": ["logika", "important"],
   …}'`, with the answer you propose as the title (`.nock/nock docs
   decisions.important`); the owner accepts or rejects it in review.
6. Where a rule or a question needs state the code does not record, don't
   add the instrumentation in this round unless the owner says to. Record it
   as a todo tagged `logika` and `instrumentation`: the event and its
   params, where in the code it goes, and the rule or question it would make
   possible.
7. `logika check` must pass. Write the report for the owner:
   - the rules you added or changed, with the evidence for each and how it
     was tested;
   - what is now measured, and the questions it answers;
   - what you left out, and why;
   - the questions you asked and the answers you got;
   - the instrumentation you suggest.
8. Finish:

       .nock/nock reflect logika finish '{"summary": "the round in a sentence or two",
         "changes": [{"kind": "validate", "target": "refund", "why": "the evidence",
                      "expect": "what it should catch, and that it stays quiet otherwise",
                      "tested": "silent on <capture>; fired on <replay>"},
                     {"kind": "funnel", "target": "activation", "why": "the owner's question",
                      "expect": "what it should show", "tested": "the captures that carry it"}],
         "verdicts": [{"expectation": "…", "held": true, "evidence": "…"}],
         "notes": "what the next round should look at"}'

   The kinds are validate, path, timeout, rule, invariant and error (the
   rules: each says how it was `tested`, or finishing refuses), identity,
   dimension, funnel, milestone and view (the analytics), and other. The
   verdicts cover the last round's expectations. Finishing requires
   `logika.json` to parse and commits `.nock/` and `logika.json`. A session
   that started the round cannot end its turn with it open: nock says what
   it still needs, once (`.nock/nock docs reflection.kinds`).
9. Tell the owner in a few lines what changed, what is waiting on them, and
   where the report is. If `reflect logika` gave `ask_the_owner`, ask them
   that too, in its words, and record exactly their answer with `.nock/nock
   usage share yes` or `no` (nothing if they don't answer). Production data is judged against the new rules, and measured by
   the new declarations, only after `logika sync` deploys the ledger. Run it
   only when the owner says so.
