---
name: nock-reflect-logika
description: Run a logika round with the owner, in a Logika project. It turns the instrumented code and the data it captures into ledger rules (validations, paths, timeouts, rules, invariants), tests each one against real captures and replays, and suggests the instrumentation a rule would need. Run it only when the owner asks, or agrees when nock says a round is due.
---

# A logika round

The owner asked for this round, and is here. Its job is to write down in
`logika.json` how this system is expected to behave, so that Logika wakes an
agent when it doesn't, and never when it does. Set aside whatever this
session was doing.

1. `.nock/nock reflect start --topic logika` prints the round's material and
   the report you write. The material shows what the ledger already says, per
   component and per event, what changed since the last round, and the
   questions and suggestions earlier rounds left.
2. Learn the forms from Logika, not from memory: `logika docs` lists them,
   and `logika docs ledger`, `ledger.validate`, `ledger.paths`,
   `ledger.timeout`, `ledger.rules`, `ledger.invariants` (and its children),
   `test`, `test.replay` and `query` hold the rest. Read `rules.md`, beside
   this file: it walks each operation from data to rule in five steps, and
   covers how to keep out false positives.
3. Start with what is owed:
   - the questions the owner has answered: act on each answer, then edit the
     question to done and say what you did;
   - the last round's rules that raised false alarms: fix them or take them
     out (see `logika show`).
4. Go through the components, most important first: money, stock, access,
   and anything else that changes shared state. Show the owner what you
   propose before writing it into the ledger. For a large project, give each
   component to a subagent with `rules.md` and the material. Subagents cannot
   ask the owner anything, so they come back to you with candidate rules,
   each with its evidence and test results, and with questions. You decide
   what lands.
5. Ask the owner what only they know, here in the session, a few questions at
   a time. Each question names the rule it would settle and the answer you
   propose. If they would rather answer later, or someone else has to:
   `.nock/nock decide '{"status": "question", "tags": ["logika"], …}'`, with
   the answer you propose as the title. Don't land a rule that depends on an
   unanswered question.
6. Where a rule needs a state change the code does not record, don't add the
   instrumentation in this round unless the owner says to. Record it as a
   todo tagged `logika` and `instrumentation`: the event and its params,
   where in the code it goes, and the rule it would make possible.
7. `logika check` must pass. Write the report for the owner:
   - the rules you added or changed, with the evidence for each and how it
     was tested;
   - what you left out, and why;
   - the questions you asked and the answers you got;
   - the instrumentation you suggest.
8. Finish:

       .nock/nock reflect finish --topic logika '{"summary": "the round in a sentence or two",
         "changes": [{"kind": "validate", "target": "refund", "why": "the evidence",
                      "expect": "what it should catch, and that it stays quiet otherwise",
                      "tested": "silent on <capture>; fired on <replay>"}],
         "verdicts": [{"expectation": "…", "held": true, "evidence": "…"}],
         "notes": "what the next round should look at"}'

   The kinds are validate, path, timeout, rule, invariant and other. The
   verdicts cover the last round's expectations. Finishing commits `.nock/`
   and `logika.json`.
9. Tell the owner in a few lines what changed, what is waiting on them, and
   where the report is. Production data is judged against the new rules
   only after `logika sync` deploys the ledger. Run it only when the owner
   says so.
