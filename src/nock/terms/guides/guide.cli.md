---
term: guide.cli
aliases: []
description: The framework your agent writes its tools in, and why what they print is made for a model to read
---

# A CLI agents can use

Every byte a command prints to an agent is read by a model, and paid for. Most
command-line tools were written for a person at a terminal: colors, progress
bars, a page of output to skim, an error that says "invalid input" and leaves
you to work out which. A person skims; a model reads every line, and an agent
that gets a vague failure tries something else, often something worse.

So nock's commands keep to a few rules:

- a command prints what the next decision needs, in the cheapest format a model
  still reads accurately;
- success is often silence: a passing check prints nothing, and its exit code
  says so;
- the exit code says what to do next: change the request, fix the code, or fix
  the machine;
- a mistake gets an answer, not just a refusal: "did you mean", the shape the
  input should have, the path to the full log.

Those rules hold for nock's own commands, and for every tool your agent writes,
because they are the framework's, not the tool's.

## A tool

A tool is a Python function in `.nock/tools/`:

```python
# .nock/tools/tests.py
import nock


@nock.command(cache="src/** tests/**", examples=["--path tests/unit"])
def failures(sh, *, path: str = "tests") -> list[dict]:
    """The failing tests, with the first line of each error."""
    run = sh(f"python -m pytest -q -rf {path}", check=False)
    return [{"test": test, "error": error} for test, error in parse(run.lines)]
```

```sh
$ .nock/nock failures --path tests/unit
test,error
tests/unit/test_cart.py::test_total,assert 41 == 42
tests/unit/test_cart.py::test_empty,KeyError: 'items'
```

It works on its next call, with nothing to register, and `.nock/nock` lists it
at the start of every session. The author wrote only what the tool does. nock
owns everything around it, the way a web framework owns HTTP or pytest owns
setup and teardown: parsing and checking the arguments, rendering and capping
the output, exit codes and error reports, running processes under supervision,
caching, telemetry and help. That matters most when an agent writes tools for
itself: it has to get only the business logic right, and everything else comes
out the same in every tool.

**The signature is the command line.** A positional parameter is an argument,
a keyword-only one an `--option`. A `bool` is a flag, a `list` repeats, an
`Enum` or `Literal` gives the choices. A parameter typed as a TypedDict or a
dataclass is one JSON argument, given inline, as a path to a JSON file, or on
stdin, and checked against the type, with a "did you mean" for a misspelled
key. The docstring is the help; `group="db"` makes the tool `.nock/nock db
NAME`.

**Fixtures, as in pytest.** A tool asks for what it needs by naming a
parameter after it: `sh` runs a command under supervision (bounded by a
deadline and a silence timeout, logged, condensed), `root` is the working tree,
`git` runs git, `changed` is the files changed against the main branch, `tmp` a
directory removed after the call, `log` notes for the call's log file, and
`config` and `project` the settings and the project. `@nock.fixture` defines
your own, and a `yield` in it cleans up after the call.

**Return data, and nock prints it.** `None` prints nothing, and the exit code
says it; `False` prints nothing and exits 1. A dict prints as `key: value`
lines, a list one item per line, a list of dicts as CSV under a header, with a
column that's the same in every row printed once above the table. These are
the cheapest formats models still read accurately. Long output is capped at
about 8,000 characters or 60 rows, and the rest saved to a file whose path is
printed. Every command takes `--json` for JSON and `--full` for everything.

**Fail by raising.** `nock.Failed("why", evidence)` exits 1 and prints the
evidence like a return value. A crash prints the lines of the tool's own code
it went through, with the values those lines used, and leaves nock's frames
out: what an agent needs to fix its own tool.

**Caching and examples.** With `cache="src/**"`, a call with the same arguments
replays the last result while those files and the tool's code are unchanged
(`--fresh` runs it anyway). The strings in `examples=[...]` show in `--help`,
and `nock check` runs them, so a tool that breaks fails the gate.

`.nock/nock docs` is the framework written for agents, one short article per
term (`.nock/nock docs fixtures` reads one, and a term it doesn't know answers
with the three closest). It's what the reflection round reads before it writes
a tool, and it's on the [reference page](/docs/terms/) too.

## Exit codes

The codes are modelled on HTTP's, and each tells the agent what to do next:

| code | meaning | do |
|---|---|---|
| 0 | yes | — |
| 1 | no: the subject failed (a check, a test) | fix the code |
| 40 | called wrong | change the request |
| 41 | not authenticated | log in |
| 42 | the machine or the state is not ready | fix that first, never the code |
| 43 | policy | don't |
| 44 | not found | check the reference |
| 49 | conflict | reconcile |
| 50 | nock or a tool crashed | report it, or fix the tool |
| 52 | an external service failed | retry later |
| 54 | timed out | raise the bound or split the work |
| 55 | hung: no output for too long | suspect a deadlock |
| 56 | killed by nock | see the log |

A tool raises the one it means: `nock.UsageError` is 40,
`nock.PreconditionError` 42, `nock.NotFoundError` 44. The difference between
1 and 42 matters most: a test that fails because Docker is down is not a bug in
the code, and 42 tells the agent to fix the machine, not the code.

## Checks, hooks and generators

Tools are what an agent calls. Three other kinds of code are what keep the
project in step without anyone calling them.

**Checks** are functions that return their problems, as strings or as
`nock.Problem(message, path, line)`, and nothing when all is well:

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

A check that asks for `changed` applies its rule to new code only, so it can
land while old code still breaks it. Your test suite and linters are checks
too, as commands in `.nock/config.toml` (see [Your tests as the
gate](#your-tests-as-the-gate)). `nock check` runs the checks the branch's
changes can affect, side by side, and prints nothing when they all pass;
`--all` runs every one.

**Hooks** react to the coding agent's events: `session-start`, `prompt`,
`before-tool`, `after-tool`, `tool-failed`, `stop` and `session-end`. A hook
asks for `payload`, the event's JSON; text it returns is added to what the agent
reads; `raise nock.Block("why")` at `stop` refuses the end of the turn. Hooks
run on every event of every session, so prefer a check.

**Generators** keep derived files in step with their source.
`@nock.generator("src/version.py")` returns one file's text (or its bytes,
written exactly). A **catalog** (`nock gen new`) is a list that code is
generated from, such as error codes, feature flags or strings: its entries are
checked against a schema and rendered through templates into every file that
lists them, and `nock gen add flags '{"key": "dark_mode", …}'` adds one and
rewrites all of those files in one call. `nock gen write` writes them, and
`nock check` fails when one has drifted.

Together they are the order nock prefers: a rule a check enforces can't be
ignored, a behavior a hook triggers can't be forgotten, and prose is the last
resort.

## The owner's word

Some commands only you may set off: a deploy, a release, a payment.
`@nock.command(confirm=True)` marks one. `nock init` allows every other
command of the toolbox in the agent's permissions, one rule per command, and
gives these an `ask` rule instead, so an agent's call waits for you to approve
it, and the toolbox lists it as asking the owner. Since the examples of every
tool run in the gate, a `confirm` tool's are only parsed against its
arguments, never run.

nock's own commands of that kind ask too: `init` (it rewrites these rules),
`upgrade` (it fetches and merges code), `share` and `report` (they send
something out). If you run your agent with bypassed
permissions and want no prompts at all, `permissions.confirm = "allow"` makes
`nock init` allow these too, and the agents are told to run them only when
your request calls for them. What nock's own agents may do is in [What nock's
agents may do](#what-nocks-agents-may-do).

## The project's environment

nock itself needs nothing but Python 3.12, but a project's tools often need its
packages, its build tools on PATH, its secrets. `[environment]` says what they
run in:

```toml
# .nock/config.toml
[environment]
python = ".venv/bin/python"   # nock re-runs itself on it, so tools import the project's code
setup = "uv sync"             # how to make it, run when it is missing (a fresh worktree)
path = ["~/.cargo/bin"]       # first on PATH, for every tool and every command they run
dotenv = ".env"               # its variables, unless already set
```

A relative interpreter path is the working tree's, so each worktree runs on its
own; the dotenv is the working tree's, else the main checkout's. Hooks get the
same environment but never wait on `setup`.

Long-running and interactive commands stream: `sh(command, stream=True)`
prints the output as it arrives, and the command has the caller's terminal, so
`ssh` and `sudo` can prompt and Ctrl-C reaches it. A bound of 0 is none, so a
dev server is `sh("uvicorn app:app", check=False, stream=True, deadline=0,
silence=0)`.

## nock is its own first user

nock's own commands are tools, registered through the same decorators a project
uses, and the whole of nock is standard-library Python with no dependencies,
vendored into `.nock/core/`. It is the project's own code: an agent can read it,
and fix it if it must, and `nock upgrade` merges the next release over those
edits.

Working on nock itself is plain: `uv sync`, `uv run pytest -n 4` (real
repositories and real processes, no mocks), `uv run ruff check`, `uv run ruff
format` and `uv run basedpyright`. From a checkout, `uv run nock init` in
another repository vendors that checkout into it. A release is one command,
`python3 scripts/release.py [VERSION]`, which asks first, then bumps, tags and
pushes; the tag's workflow runs the gate on it and publishes to PyPI. The
repository's [ARCH.md](ARCH.md) has the layout.

Every command, nock's own and their flags, is on the [reference
page](#commands).
