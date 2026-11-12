---
term: reflection.logika.lead
aliases: [logika-rounds]
description: /logika: how the lead runs the logika rounds, rules and analytics, step by step
---

# The logika rounds

The owner asked for these rounds: `logika.rules` and `logika.analytics`,
run together (`/logika`) or one alone (`/logika-rules`, `/logika-analytics`). Their job is to write down in `logika.json`
what must hold, so that Logika wakes an agent when the system breaks it, and
what is worth measuring, so that Logika's analytics answer the owner's
questions from real captures. You decide what lands, from the code, the
docs, the copy users see and the data; the owner settles only general
directions and genuine ambiguities, and reviews the rest in your report,
after the round rather than before each rule. Whatever this session was
doing waits.

Every event in the ledger carries its `risks`: each a risk key (`once`)
mapped to the event's params that are its evidence, or to the reason it
doesn't apply here:

    "risks": {"once": ["attempt", "will_retry"], "stale": "why it doesn't apply"}

`logika docs risks` says what a risk is and how a rule guards it.
The round gives each risk with evidence its rule over those params, or the
reason it gets none; `logika map` shows where that stands.

Done when: the rules and declarations you decided on are in `logika.json`;
`logika map` leaves no risk at "no rule yet" that a rule could guard; the
instrumentation they need is in the code; the noise check fires on nothing
normal; `logika check` passes; and `.nock/nock reflect --submit` has
recorded each round.

1. `.nock/nock reflect logika` starts both rounds (`reflect logika.rules`
   or `reflect logika.analytics` one) and prints each one's material and
   the report you write for it. The material shows what the ledger already says
   and measures, per component, event (with its risks) and param, what
   changed since the last round, and the decisions earlier rounds left in the
   `logika` topic.
2. Start with what is owed:
   - the decisions the owner rejected or wrote on: act on each, as a new
     version (`.nock/nock docs topics.versions`), answering in its thread
     when the version doesn't say it;
   - the last round's rules that raised false alarms: fix them or take them
     out (`logika query` shows them).
3. Find the gaps: `logika map` (`logika docs map`) prints, per file, each
   function's events and each event's risks, "by <params>, guarded by …",
   "no rule yet" or "ruled out", and ends with "To look at". That is the
   round's work list: the gaps come from it.
4. Dispatch the parts as subagents, in one message, each of its type (in
   `.claude/agents/`; each reads its own brief): one rules part per
   directory the map shows gaps in (a component's paths, or a top-level
   source directory where the map names no components), and one analytics
   part for the whole. Give each its material and the round's window, and
   a rules part its directory. They read and run commands but change
   nothing, so all can work over the tree at once while you keep it: you
   alone write `logika.json` and the code.

   | part | subagent type | brief | material | brings back |
   |---|---|---|---|---|
   | rules, one per directory | `logika-rules` | `reflection.logika.rules` | `rules` | for each risk, its rule over its evidence or the reason it gets none; risks an event lacks; the fields a rule needs |
   | analytics | `logika-analytics` | `reflection.logika.analytics` | `analytics` | identities, dimensions, funnels, milestones, views |

   If a part fails, say so in the report rather than doing its part
   yourself: its brief is what makes it careful.
5. Clear with the owner only what you can't settle yourself: a general
   direction (which areas matter most, what a whole class of failure means
   to them) or a genuine ambiguity, where the docs, the copy, the tests and
   the code's intent leave the intended behaviour open. Ask a few at a time,
   each with the rule it settles and the answer you propose, and carry on
   with your answer meanwhile; if they would rather answer later, record it
   as a decision in the `logika` topic, your answer as its title
   (`.nock/nock docs topics.items topics.decisions`; create the topic the
   first time). Thresholds aren't questions: they come from the
   data, with the margin you chose stated in the rule's evidence.
6. Add the instrumentation the rules need, as Logika's docs describe
   (`logika docs instrument`): the raw input a decision read beside its
   outcome, an effect's real result, the id it acted on, a step as a child
   event. Change the code and the ledger together, point the event's risks
   at the new params, keep every existing event and param, run `logika
   check`, then capture again (`logika test "<the command that exercises
   it>"`) and see the new fields filled. Commit it on its own (the code and
   the ledger), saying what the code now logs.
7. Write what the parts brought back into `logika.json`, most important
   first: money, stock, access, and anything else that changes shared
   state. Each rule carries its one-sentence `description` (the anomaly's
   title) saying what must hold and why (`logika docs rules`); each risk
   maps to its evidence or its reason. Run `logika check` until it passes.
   Then run `logika map` again: if it shows much the parts didn't cover
   (risks the new instrumentation brought, a directory they missed), run
   steps 4 to 7 once more over those directories only, then stop.
8. One noise check, at the end (`logika docs replay`): judge real traffic
   against the new ledger, `logika replay '{"on": "capture"}'` for the last
   local capture, or `logika replay '{"on": "query", "query":
   "<condition>"}'` for production's events that match a condition. Fix what
   fires on normal behaviour; where the docs or copy state the promise it
   breaks, the rule stands and what it fires on is a known issue (or the
   code is fixed), since loosening it would encode the bug. Keep the rest:
   a little noise is calibrated in production, and a missing rule never
   fires.
9. Write each round's report for the owner, as what you decided, for them to
   review (the rules round's the rules, risks and their instrumentation; the
   analytics round's what is now measured):
   - the rules you added or changed, each with its risk, its evidence and
     the margin behind its threshold;
   - the risks you ruled out, and why;
   - the instrumentation you added, and the rules it made possible;
   - what is now measured, and the questions it answers;
   - what the noise check fired on, and what you did about it;
   - the directions and ambiguities you settled, the answers you got or
     the ones you chose;
   - the known issues today's behaviour breaks.
10. Submit each round:

        .nock/nock reflect --submit '{"protocol": "logika.rules", "summary": "the round in a sentence or two",
          "changes": [{"kind": "validate", "target": "refund", "why": "refunds.overpaid, by amount and charged",
                       "expect": "what it should catch, and that it stays quiet otherwise",
                       "tested": "quiet in the noise check over a week of production refunds"},
                      {"kind": "risk", "target": "delivery: once", "why": "the provider never reuses a delivery id",
                       "expect": "no rule while ids come from the provider"},
                      {"kind": "instrumentation", "target": "refund", "why": "the rule it made possible",
                       "expect": "the field filled on every sighting", "tested": "the capture that shows it"},
                      ],
          "verdicts": [{"expectation": "…", "held": true, "evidence": "…"}],
          "notes": "what the next round should look at"}'

    and `"protocol": "logika.analytics"` with its own changes, such as
    `{"kind": "funnel", "target": "activation", "why": "the question it
    answers", "expect": "what it should show", "tested": "the captures that
    carry it"}`. The rules round's kinds are validate, path, timeout, rule,
    invariant and error (the rules), risk (a risk declared or ruled out),
    instrumentation and other; the analytics round's identity, dimension,
    funnel, milestone, view, instrumentation and other.
    `tested`, what showed a change (the noise check, a capture), is
    optional. The verdicts cover the last round's expectations. Submitting
    requires the ledger to parse and commits `logika.json` and the round's
    record; nock says what a round left open still needs (`.nock/nock docs
    reflection.protocols`).
11. Tell the owner in a few lines what changed, what you decided that they
    may want to look at, and where the report is. If `reflect` gave
    `ask_the_owner`, ask them that too, in its words, and record exactly
    their answer with `.nock/nock config share true` or `false` (nothing if they
    don't answer). Production is judged against the new rules, and measured
    by the new declarations, once `logika sync` deploys the ledger, which is
    the owner's to run.
