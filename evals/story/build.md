# Build the world

`STORY.md`, in this directory, is the engineering record of one month at a
small software company. Build it as a *world*: the company's repository,
plus everything needed to replay each of the month's twenty reports on it
and to check, without judgment, whether an engineer resolved it. Agents will
be dropped into this repository and given each report's message, so the
repository must be the system the story describes, working and lived-in.

Build it in `world/`, in this shape:

```
world/
  repo/                  the company's git repository
  world.json             {"reports": [{"id": "W1-1", "week": 1, "family": "…"}, …]}
  reports/W1-1/
    message.md           the report's message, verbatim, as the engineer receives it
    owner.md             what the owner knows (the story's field 10), in their voice
    setup.py             makes this report's trouble happen on a fresh checkout
    resolve.py           applies the team's resolution (for validating only)
    verify.py            says whether the trouble is resolved, and what a careless fix broke
  …
```

## The repository

- `repo/` is the system as it stands at the start of week 1, built to the
  story: its code, config, tests, scripts, README, runbook and changelog,
  with a git history of realistic commits going back about a year (authors
  and dates as the story gives them).
- Tag `week-1` there. Then, for each following week, commit that week's
  teammate changes (their messages, as written) and the team's resolutions
  of the week's reports, and tag `week-2`, `week-3`, `week-4`. Nothing about
  the month's reports, setups or answers may appear in the repository except
  what the team itself would have committed.
- Python and SQLite only, standard library first: whatever runs it must run
  from a fresh clone with `python3`, and its tests with one command the
  README names. Partners are small local services the repository starts,
  and time comes from a clock the system can be told to use.

## Each report

All three scripts take one argument, the path of a checkout of the report's
week tag, and run with `python3` from anywhere. They are deterministic.

- `setup.py` makes the report's trouble happen, on top of the week's state,
  as the story's "How it was set up" says: a commit by a teammate (with the
  teammate's message, author and date), changed config or data, a partner
  that misbehaves, logs produced by running the system under that week's
  traffic. Whatever it changes must look as it would in the real system:
  no comments, files or names that point at the setup.
- `resolve.py` applies what the story calls a good resolution.
- `verify.py` checks "How we know it's resolved", and also what a careless
  resolution would break. It prints one JSON line per check,
  `{"check": "…", "ok": true}`, and exits 0 only when every check passes.
  It may start the system, send requests, run queries and tests, and must
  stop whatever it started. For a question about the data, it reads the
  engineer's answer from `ANSWER.md` at the checkout's root (the engineer is
  told to write it there) and checks the exact numbers or list the sender
  needed. Compute every expected figure from the world's own data with a
  query of its own, never a number written in by hand: a verifier that
  agrees with a wrong `resolve.py` still validates.

## Done means

`python3 {{ harness }} validate world` passes. For every report it
checks out the week tag, runs `setup.py`, requires `verify.py` to **fail**,
runs `resolve.py`, and requires `verify.py` to **pass**. Run it, fix what it
reports, and run it again until it passes. Then say in a few lines what you
built and anything the story asked for that you could not build.
