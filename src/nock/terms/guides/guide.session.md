---
term: guide.session
aliases: [guide.first-session, guide.what-agents-see]
description: What a session sees: the toolbox, the primer, the standing, and the few things nock says unasked
---

# The first session

Every session starts with the project's tools listed, through Claude Code's
SessionStart hook. CLAUDE.md imports a short primer, `.nock/context.md`: why
the project uses nock (to stay coherent across sessions), to consult before
changing code, putting work before the owner in topics, `nock run`, and offering to tell nock's
makers what nock lacks with `nock report` (see [Telling nock's makers what
you need](#telling-nocks-makers-what-you-need)). A session the human
starts also hears where things stand, in a few lines — once a day, or sooner
when something new calls (a round falls due, the owner rejects an
item) — with a word on what to do with it: take into account
what bears on the request, and mention the rest to the human only when
relevant or once the work is done. `.nock/nock` with no arguments lists the
toolbox.

## Quiet

**`reminders = false`** in `.nock/config.toml` keeps nock silent unless
asked: no toolbox or standing at a session's start, no verdicts at a prompt,
no items after an edit, and a primer that only says what nock is. Every
session and call is still recorded, `nock status` still answers, and the
project's own hooks still run. The primer follows the committed settings (a
session start rewrites it when they change), so set it in
`.nock/local/config.toml` to quiet only the hooks on your machine.

## Mistakes and noisy work

A mistake gets an answer:

```sh
$ .nock/nock failurs
nock: no command `failurs` — did you mean `failures`? (`.nock/nock` lists them all)
$ .nock/nock failures --pth tests
nock: unrecognized arguments: --pth tests; --pth → did you mean --path?
```

For work that isn't a tool yet:

- **`.nock/nock run -- COMMAND`** runs anything long or noisy under
  supervision. Colors and redrawn progress bars are dropped, repeated lines
  are folded into one with a count, and long output is cut to its end, with
  the log's path.
- **A failing call that repeats an earlier one byte for byte says so**: "same
  result as call 41 (3m ago) and no file has changed since". It never refuses
  to run, because something outside the repository may have changed.
