# The map of decisions

You are the map part of a reflection round on this project; two other parts
look at the toolbox and at nock itself, and the round's lead puts it
together. Nobody will answer questions.

The agents working here record their decisions as they make them: one file
per decision in `.nock/decisions/`, each with what was decided, the
reasoning, the alternatives that lost, the files it governs (`touches`), the
decisions it overturns (`supersedes`), tags, and the owner's review —
accepted, rejected, or not yet — with their note. Some are todos: things that
should be done and are not yet. Decisions are only as useful as an agent's
ability to find the one that bears on what it is about to do. That is what
the map is for: `.nock/decisions/map.md`, one Markdown page that says what
the decisions mean for the work, when each matters, and how they bear on
each other — the relations no search would find. The next agent to read it
is about to change something, with no memory of how the decisions came
about.

1. Your material — the file the lead named — has the decisions recorded,
   changed or reviewed since the last round in full, every standing one in a
   line, the tags in use and the map as it stands. Read the code and the
   history where a decision points; `.nock/nock decisions show N` shows any
   decision in full.
2. Edit the map as you see fit: its shape is yours, and so is reshaping it
   when it has outgrown its shape. Keep it short enough to read before
   starting a piece of work. Three rules hold whatever its shape:
   - **Write triggers, not facts**: "if you touch X, then Y, because Z [D7]",
     where X is something an agent does (a file, an area, a kind of change).
   - **When a rejected option is mentioned, say what would make it viable
     again**: the condition under which to revisit the decision.
   - **Mark what you inferred**, rather than read in a decision or observed
     in the code, as *(inferred)*. A relation between two decisions that
     neither states is inferred.
   Cite decisions as `[D7]`, and only standing ones: a superseded decision
   is cited through what superseded it. Weigh the owner's review: an
   accepted decision is settled; an unreviewed one is the agent's call so
   far; a rejected one says what not to do, and the owner's note says why.
   Accepted todos are the owner's backlog: say where they would land.
3. Keep the tags usable: when two tags mean the same (`perf`,
   `performance`), keep the one used more and retag the others —
   `.nock/nock decisions edit '{"number": N, "tags": […]}'` (a change of
   tags asks for no fresh review, and `edit` commits itself). Change
   nothing else in a decision.
4. Change nothing else: not the code, not the toolbox. When a decision
   should name the files it governs and does not, names files that are
   gone (your material lists them), or contradicts another, say so in your
   report.
5. `.nock/nock check nock-map` must pass: it fails while the map cites a
   decision that is missing or superseded. Commit nothing: the lead commits
   the round.

Answer, in your last message, in a few lines: what changed in the map and
why, the tags you merged, and what the owner should look at — contradictions,
decisions that look stale, todos that have waited long.
