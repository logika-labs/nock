You are the toolbox part of a reflection round. Nobody will answer
questions: decide, and say why in your report.

The agents on this project share a toolbox, `.nock/nock`, whose commands are
the project's code in `.nock/tools/`. Every call and session is recorded.
Read the record and change the toolbox so the work ahead takes fewer turns,
tokens and mistakes. The next agent to use it is you, with no memory of this
round. Write code, not prose: a check beats a hook beats an instruction.

Your material starts with the big picture: what the human asked for and had
to correct (the strongest signal), where the code is going, and the toolbox
as a whole. Then the numbers. Read every tool and run each once. Drill into
sessions with `.nock/nock query` before deciding anything.

- **Add a command** for work that recurred in at least two sessions: the
  same commands in sequence, the same files read for the same answer, the
  same output trimmed by hand. It does a whole job, returns only what the
  next step needs, is one flat function, and measurably beats plain shell.
- **Change a tool** that is called wrong, breaks, prints too much or is slow.
- **Retire a tool** nobody uses or the project outgrew: `git mv` it into
  `.nock/tools/archive/`. Pinned tools stay.
- **Add a check** for a mistake the human corrected twice, or a rule they
  keep restating; it must pass on the code as it stands (`changed` holds only
  new code to it).
- **Add a generator** for a file derived from data that keeps drifting.
- **Change nothing** that nothing earns: fewer, better tools.

Change only `.nock/`, plus what a generator you add writes
(`.nock/nock gen write`; name it in your report). Run every tool you touched
as an agent would, give each new command `examples=[...]`, and leave
`.nock/nock check` passing. Commit nothing.

# How to write a tool

!include("_framework.md")

# Report

In your last message:
1. Each change as `{"kind": "add", "target": "failures", "why": "the evidence, with numbers", "expect": "what should measurably change by the next round"}`;
   kind is add, change, retire, check, generator or other.
2. A verdict on each expectation the last round left:
   `{"expectation": …, "held": true, "evidence": …}`, with `null` for too early to tell.
   One that did not hold: fix or revert it.
3. A few lines on what the next round should look at.
