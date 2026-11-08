---
term: guide.check
aliases: [guide.checks, guide.hooks, guide.generators]
description: Checks that return problems, hooks on Claude Code's events, generators that keep files in step
---

# Checks, hooks and generators

**Checks** are functions that return their problems, as strings or as
`nock.Problem(message, path, line)`. They return nothing when all is well.

```python
@nock.check
def migrations_reversible(root, changed):
    """Every new migration has a down step."""
    return [
        nock.Problem("no down()", path)
        for path in changed
        if path.startswith("migrations/") and "def down" not in (root / path).read_text()
    ]
```

A check that asks for `changed` applies its rule to new code only. So it can
land while old code still breaks the rule. A command can be a check too, set
in `.nock/config.toml` as shown above.

**Hooks** react to Claude Code's events: `session-start`, `prompt`,
`before-tool`, `after-tool`, `tool-failed`, `stop` and `session-end`.

- A hook asks for `payload`, the event's JSON.
- Text a hook returns is added to what the agent reads.
- `raise nock.Block("why")` at `stop` refuses the end of the turn.

Hooks run on every event of every session, so prefer a check.

**Generators** keep derived files in step with their source:

- `@nock.generator("src/version.py")` returns the text of one file, given
  a final newline; or its bytes, written exactly (a binary golden, a file
  that must not end in a newline).
- A **catalog** (`nock gen new`) is a list that code is generated from, such
  as error codes, feature flags or strings. Its entries are checked against a
  schema and rendered through templates into every file that lists them.
  `nock gen add flags '{"key": "dark_mode", …}'` adds an entry and rewrites all of those
  files in one call.

`nock gen write` writes the generated files, in the order they are
defined and each before the next is generated, so one may read a file an
earlier one writes (types from a schema it generates). `nock check` fails
when one of them has drifted.
