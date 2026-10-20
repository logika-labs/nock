---
name: consolidate
description: Keep this project's map of decisions (.nock/questions/map.md) — read the decisions made since the last round, edit the map, record lessons, and land it. Use when nock says consolidation is due, or when asked to consolidate.
---

# Consolidate the decisions

The agents working here ask the owner what the code cannot settle, and the
answers are kept: one question per file in `.nock/questions/`, each decided
one with an `answer`, the files it governs (`touches`) and the decisions it
overturns (`supersedes`). They are only as useful as an agent's ability to
find the one that bears on what it is about to do. That is what the map is
for: `.nock/questions/map.md`, one Markdown page that says what the decisions
mean for the work, when each matters, and how they bear on each other — the
relations no search would find. The next agent to read it is about to change
something, with no memory of how the decisions came about.

1. `.nock/nock consolidate material` prints the decisions made since the last
   round, every standing decision, and the map as it stands. Read the code
   and the history where a decision points; `.nock/nock questions show N`
   shows any question in full.
2. Edit the map as you see fit: its shape is yours, and so is reshaping it
   when it has outgrown its shape. Keep it short enough to read before
   starting a piece of work. Three rules hold whatever its shape:
   - **Write triggers, not facts**: "if you touch X, then Y, because Z [Q7]",
     where X is something an agent does (a file, an area, a kind of change).
   - **When a rejected option is mentioned, say what would make it viable
     again**: the condition under which to revisit the decision.
   - **Mark what you inferred**, rather than read in a decision or observed
     in the code, as *(inferred)*. A relation between two decisions that
     neither states is inferred.
   Cite decisions as `[Q7]`, and only standing ones: a superseded decision is
   cited through what superseded it.
3. When the work taught something that is not yet a decision — a mistake
   that recurred, a convention the decisions imply — record it as a lesson,
   a question decided at once, which the map can then cite:

       .nock/nock questions record '{"title": …, "context": …, "answer": …, "touches": […]}'

   `context` says what happened that taught it, with the evidence; `answer`
   is the lesson. A lesson is inferred by nature: say so in its answer.
4. Change nothing else: not the code, not the question files by hand. When a
   decision should name the files it governs and does not, say so in the map.
5. `.nock/nock check nock-map` must pass: it fails while the map cites a
   question that is not a standing decision. Then `.nock/nock consolidate
   record`, and commit the map and the record together. Say in a line what
   changed in the map, and why.
