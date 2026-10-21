# The story eval

Does nock help agents through a month of real work, compared with an agent
that keeps nothing, and with one that keeps prose and skills?

1. **The story.** A model with a clean context writes `STORY.md` from
   `brief.md`. It covers one month at a small software company: the system,
   and twenty reports over four weeks. The reports come in families of
   trouble that recur with different causes, plus a few one-offs and the
   team's own changes between weeks. Each report says what the owner knows:
   intent and semantics, never the cause.
2. **The world.** An agent builds the story from `build.md` into `world/`:
   - the company's repository, with a tag per week;
   - per report, its message, what the owner knows, `setup.py` (makes the
     trouble happen), `resolve.py` (the team's fix) and `verify.py` (resolved
     or not, and what a careless fix broke).

   `validate` requires every verifier to fail after the setup and pass after
   the fix. The builder is sent back until it does.
3. **The run.** Each arm works through the month. Every report is a fresh
   checkout of its week, with the week's earlier sessions replayed on it —
   their trouble and their fixes, as commits, as if merged — then set up,
   and a real session given the message. After it, a scripted owner reads
   its last message and, when it asks something or waits on an OK, answers
   from what it knows; the session is resumed once. Now and
   then — after half the sessions, at random but seeded — the owner gets
   round to the decisions waiting on review, and accepts or rejects them
   with notes, judging each from what it knows of its report. The verifier
   decides.
   - **bare** keeps nothing between sessions;
   - **skills** keeps `CLAUDE.md` and `.claude/`, rewritten each week by a
     reflection session over the week's transcripts (`reflect-skills.md`);
   - **nock** has nock installed, keeps `.nock/` (toolbox, decisions, map)
     and runs `/nock-reflect` each week.

   Weeks 1–3 are for learning. Then what each arm keeps is frozen, and week 4
   runs `--repeats` times in parallel. `--weeks N` stops after N learning
   weeks, to look before going on.
4. **The report.** `report.md` shows, per arm, how many reports were
   resolved, the share of checks passed, cost, turns, time and questions
   asked. A per-report table for week 4 follows.

```sh
uv run python evals/story/run.py story /tmp/story               # STORY.md, with Fable
uv run python evals/story/run.py build /tmp/story               # world/, validated
uv run python evals/story/run.py run /tmp/story --repeats 3     # all arms
uv run python evals/story/run.py report /tmp/story
```

Outcomes are appended to `OUT/outcomes.jsonl` as they happen. The arms'
repositories are linked from `OUT/arms/` to look at. They live in a
temporary directory of their own, and hold only the week's history: from
inside `OUT`, or with later weeks' tags, the answers would be in reach.
