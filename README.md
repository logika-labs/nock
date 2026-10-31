# nock

A toolbox your coding agents build for themselves.

## Why

Agents repeat themselves:

- they run the same five shell commands to find out why a test fails;
- they write the same throwaway script to query the database;
- they pipe the same noisy output through `tail`;
- they trip over the mistake the human has already corrected twice.

Every repeat costs turns and tokens, and every session starts again from
nothing.

The usual fix is prose: skills, notes, rules in CLAUDE.md. Prose has two
problems:

- **It goes stale without anyone noticing.** When the code moves on, a
  paragraph that no longer fits the project still reads as true.
- **It is read differently every time.** An agent can follow it, skip it, or
  half-apply it, and nobody can tell which.

nock's fix is code. A command that no longer fits the project **breaks**:
it exits non-zero, a check fails, and the failure is recorded. So the toolbox
can be kept honest by measuring it. That is also the rule nock lives by:

> **A check beats a hook beats prose.**
>
> A rule that a check enforces cannot be ignored. A behavior that a hook
> triggers cannot be forgotten. Prose is the last resort.

### Three principles

1. **An agent-friendly CLI.** Every byte a command prints is read by a model
   and paid for, so:
   - a command prints what the next decision needs, in the cheapest format
     that reads accurately;
   - success is often silence: a passing check prints nothing, and its exit
     code says so;
   - the exit code says what to do next: change the request, fix the code, or
     fix the machine;
   - a mistake gets an answer, not just a refusal: "did you mean", the
     expected shape of the input, a path to the full log.
2. **Every run recorded.** Every call to nock is recorded locally: its
   arguments, duration and exit code, and how much the agent had to read. So
   is every Claude Code session: what the human asked, each tool call the
   agent made (nock or not), what failed, and what it cost. You cannot
   improve what you have not measured, and agents do not remember.
3. **Reflection.** Every so often, an agent reads that record and improves
   the toolbox:
   - it builds tools for the work that keeps costing turns and tokens;
   - it repairs and retunes the tools that misbehave;
   - it retires the tools nobody uses.

   It starts from the big picture, not just the numbers: what the human has
   been asking for, and where the code is going. It writes down what it
   expects each change to do, and the next round holds it to that. What it
   builds is live on the next call.

### A framework, not a library

A tool's author writes only what the tool does. nock owns everything around
it, the way a web framework owns HTTP or pytest owns setup and teardown:

- parsing the arguments and checking the input;
- rendering the output, and capping it;
- exit codes and error reports;
- running processes under supervision;
- caching;
- telemetry;
- help text.

That matters most when an agent writes tools for itself. It has to get only
the business logic right, and everything else comes out the same in every
tool.

nock is standard-library Python 3.12 and has no dependencies. It is vendored
into the project, so it is the project's own code: an agent can read it, and
fix it if it must. Tools that need the project's own packages run on the
project's interpreter instead (see [The project's environment](#the-projects-environment)).

## Getting started

Inside the repository you want it in:

```sh
uvx nock init
```

(Or `pipx run nock init`; from a checkout of nock, `uv run --project
~/path/to/nock nock init`.)

`nock init`:

- vendors nock into `.nock/core/` and writes the `.nock/nock` shim;
- writes `.nock/config.toml` and an empty `.nock/tools/`;
- writes the primer `.nock/context.md`, and imports it into CLAUDE.md;
- wires Claude Code's hooks;
- allows `.nock/nock` in Claude Code's permissions, except the commands that
  need the owner's word, which Claude Code asks about.

Commit the result. From then on, every agent session in the repository starts
with the project's tools listed, and is recorded when it ends.

To upgrade, `.nock/nock upgrade`. It merges the latest release from PyPI into
the vendored core, keeping any local edits to it (a three-way merge against
the release you have), and re-wires the project: primer, hooks and skills.
Once a day at most, a session you start asks PyPI whether a newer nock is out
and says so; `upgrade.check = false` turns that off.

To make your test suite and linters the gate that tools and reflection rounds
must pass, add them as checks:

```toml
# .nock/config.toml
[checks.test]
command = "pytest -q"

[checks.lint]
command = "ruff check"
```

Checks run side by side. Those that must not — they share a build, a lock
or a cache — share a `chain`, and run one after another in the order they
are written:

```toml
[checks.clippy]
command = "cargo clippy -- -D warnings"
chain = "rust"

[checks.cargo-test]
command = "cargo test"
chain = "rust"
```

`nock check rust` runs a chain; `nock check cargo-test` one check of it.

## A tool

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

The tool works on its next call, with nothing to register. `.nock/nock guide`
is the whole framework on one page, written for agents. In short:

**The signature is the command line.**

- A positional parameter is an argument, and a keyword-only one is an
  `--option`. A `bool` is a flag, a `list` repeats, and an `Enum` or
  `Literal` gives the choices.
- A parameter typed as a TypedDict or a dataclass is one JSON argument. It
  can be given inline, as a path to a JSON file, or on stdin (`-`, or left
  out when it has no default). It is checked against the type, and a
  misspelled key gets a "did you mean". With a default, left out is the
  default.
- The docstring is the help, and `group="db"` makes the tool
  `.nock/nock db NAME`.

**Fixtures, as in pytest.** A tool asks for what it needs by naming a
parameter after it:

| fixture | is |
|---|---|
| `sh` | runs a command supervised: bounded by a deadline and a silence timeout, logged, and condensed; `stream=True` prints it as it goes instead, for servers and for commands someone watches or answers |
| `root` | the working tree |
| `git` | `git("log", "-1")` returns the output |
| `changed` | the files changed against the main branch |
| `tmp` | a directory, removed after the call |
| `log` | notes to the call's log file, never to the caller |
| `config`, `project` | the settings, and the project |

`@nock.fixture` defines your own, and a `yield` in it cleans up after the
call.

**Return data, and nock prints it.**

| the tool returns | nock prints |
|---|---|
| `None` | nothing: the exit code says it |
| `False` | nothing, and exits 1 |
| a string | the string |
| a dict | `key: value` lines |
| a list | one item per line |
| a list of dicts | CSV under a header; a column with the same value in every row is printed once, above the table |
| nested data | indented `key: value` |
| an `Output` from `sh` | the command's condensed output, and its exit code |

These are the cheapest formats that models still read accurately. Long output
is capped at about 8,000 characters or 60 table rows, and the rest is saved to
a file whose path is printed. `--json` gives JSON, and `--full` gives
everything.

**Fail by raising.**

- `nock.Failed("why", evidence)` exits 1, and the evidence prints like a
  return value.
- `nock.UsageError` exits 40, `nock.PreconditionError` 42 and
  `nock.NotFoundError` 44.
- A crash prints the lines of the tool's own code that it went through, with
  the values those lines used, and leaves nock's frames out.

**The owner's word.** `@nock.command(confirm=True)` is for a command only
the owner may set off: a deploy, a release, a payment. `nock init` adds a
Claude Code `ask` rule for it, so an agent's call waits for the owner to
approve it although `.nock/nock` is otherwise allowed, and the toolbox
lists it as asking the owner. The `nock-wiring` check fails while the rule
is missing.

**Caching.** With `cache="src/**"`, a call with the same arguments replays the
last result as long as those files and the tool's own code are unchanged.
`--fresh` runs the tool anyway.

**Examples.** The strings in `examples=[...]` appear in `--help`, and
`nock check` runs them, so a tool that breaks fails the gate.

### The project's environment

nock itself needs nothing but Python, but a project's tools often do: its
packages, its build tools on PATH, its secrets. `[environment]` says what
they run in:

```toml
# .nock/config.toml
[environment]
python = ".venv/bin/python"   # nock re-runs itself on it, so tools import the project's code
setup = "uv sync"             # how to make it, run when it is missing (a fresh worktree)
path = ["~/.cargo/bin"]       # first on PATH, for every tool and every command they run
dotenv = ".env"               # its variables, unless already set
```

A relative interpreter path is the working tree's, so each worktree runs on
its own. The dotenv is the working tree's, else the main checkout's, since
it is rarely committed. Hooks get the same environment, but never wait on
`setup`: until it has run, nock says the interpreter is missing and runs on
the one it has. Variables git sets when it runs nock (`GIT_DIR`,
`GIT_INDEX_FILE`, …) never reach a command `sh` runs, so a repository a test
creates is its own.

### Long-running and interactive commands

`sh(command, stream=True)` prints the output as it arrives instead of
condensing it afterwards, and the command reads the caller's stdin and has
the caller's terminal: `ssh` and `sudo` can prompt on it, and Ctrl-C reaches
it. A failing streamed command points at its log rather than printing its
output twice. A bound of 0 is none, so a dev server is
`sh("uvicorn app:app", check=False, stream=True, deadline=0, silence=0)`;
interrupted, it is asked to stop (SIGINT) and given five seconds before it
is killed.

### Checks, hooks and generators

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
`after-tool`, `tool-failed`, `stop` and `session-end`.

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

`nock gen write` writes the generated files, and `nock check` fails when one
of them has drifted.

## What agents see

Every session starts with the project's tools listed, through Claude Code's
SessionStart hook. CLAUDE.md imports a short primer: why the project uses nock (to stay coherent across sessions), when to consult, recording decisions, and `nock run`. What the session start says comes with a word on what to do with it: take into account what bears on the request, and mention the rest to the human only when relevant or once the work is done. `.nock/nock` with no
arguments lists the toolbox. A mistake gets an answer:

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

## Telemetry

Everything is in `.nock/local/nock.db`, a local SQLite file that is never
committed:

| table | holds |
|---|---|
| `calls` | every nock call, including refused ones: the command, its arguments, session, duration, exit code, bytes printed and in full, whether it was cached, and the error |
| `runs` | every supervised process; the logs are in `.nock/local/logs/` |
| `sessions` | each Claude Code session's title, tokens, cost, prompts, interrupts and compactions |
| `prompts` | what the human typed |
| `events` | every tool call of every session: the command, path or pattern, whether it failed, the bytes returned, and the duration |
| `heard` | which sessions were told the owner's reviews of the decisions they recorded |
| `shown` | which sessions were shown the decisions behind a file they edited |
| `nudged` | which rounds' unshared summaries a session start mentioned |

Sessions are read from Claude Code's transcripts when they end, and any
that were missed are read when a reflection round starts. To look:

- `nock calls`, `nock stats` and `nock sessions` summarize the data;
- `nock query "SELECT …"` runs read-only SQL.

## Decisions

Agents record their decisions as they make them, and the owner reviews them
afterwards. Nothing waits on the owner: the agent goes ahead, and the record
says what it chose, why, and what it passed over.

```sh
$ .nock/nock decide '{"title": "The charge sweep requeues dead charges only",
    "status": "done",
    "summary": "The nightly sweep picks up charges whose job died, not ones still retrying…",
    "evidence": ["42 duplicate attempts last week came from requeued failed jobs"],
    "alternatives": [{"option": "Requeue failed and dead jobs",
                      "why_not": "failed jobs are still on their backoff; it doubles the attempts"}],
    "tags": ["important", "payments"], "touches": ["billing/sweeper.py"]}'
```

A decision is a non-trivial choice between ways that could each work, a
deliberate simplification, or a reading of something ambiguous. What has one
obvious right way is not a decision, and an alternative nobody weighed is
not an alternative. With `"status": "todo"` it is something that should be
done and is not yet; a possible improvement is a todo tagged `improvement`.
With `"status": "question"` it asks the owner what only they can settle,
when they are not there to ask: the title is the answer the agent proposes
("Refunds never exceed the charge"), the alternatives the other answers it
sees. The summary is written for someone who knows what the system does,
but not how it is built.

Each decision is a file, `.nock/decisions/0007.json`, written and committed in
the main checkout whichever worktree recorded it. Its tags are `important`,
`technical`, `product`, `improvement` and the agent's own (a component, a
subject); `decide` prints the tags in use, so a near-duplicate is caught
early. `touches` names the files or globs it governs, and `supersedes` the
decisions it overturns, which stay as history.

| | unreviewed | accepted | rejected |
|---|---|---|---|
| **done** | done; please check | it stands | rework it |
| **todo** | worth doing later? | on the backlog | do not do it |
| **question** | asks you | yes, as proposed | no: the note says what holds |

A note alone answers a question in words. Until an agent acts on the answer
— and edits the question to done, saying what it did — every session the
human starts lists it.

- **The owner reviews.** On the page, `nock web` (or with `{"open": true}`),
  which lists the decisions to review, accepted and rejected, searchable and
  filtered by status and tag; `#7` in its address opens decision 7. Or in a
  session, with `/nock-triage`, which goes through them one at a time. Each
  can be accepted, rejected or noted; asked for more, the session looks into
  it itself.
- **The session that recorded it hears.** When the owner next types there,
  the prompt hook tells it what they said, once.
- **Work changes the record.** `nock decisions edit` reworks a rejected
  decision, or marks a todo done, in place; git keeps the history. A change
  to what a decision says asks for a fresh review, and keeps the owner's
  note. `review` and `note` are the owner's word: agents set them only when
  told to.
- **An edit shows the decisions behind a file.** The first time a session
  edits a file a standing decision touches, the edit hook shows it — the
  rejected ones first, with the owner's note.
- **"Elaborate" starts an agent at once.** It reads the project and deepens
  the summary, evidence and alternatives, answering the owner's note
  (`nock decisions elaborate N`).

Any session the human starts says how many questions, todos and done
decisions wait on review, the questions answered and not yet acted on, which rejected ones wait to be reworked, the owner's backlog (todos
they accepted), and what they said about decisions since the last round —
a note often asks for something. `nock status` says the same, and whether a
reflection round is due.

### The map

`.nock/decisions/map.md` says what the decisions mean for the work: when
each matters, and how they bear on each other. A consultant is given it
with its brief. A reflection round keeps it, within three rules:

- triggers, not facts: "if you touch X, then Y, because Z [D7]";
- a rejected option comes with what would make it viable again;
- what was inferred, rather than read or observed, is marked *(inferred)*.

`nock init` starts it empty. The `nock-map` check fails when the map cites a
decision that is missing or superseded. A done decision whose files are gone
is not a failure: the round's material lists it, for the map part to look
at; and `decide` says at once when `touches` names a file that doesn't exist.

### Consulting

While an agent works out how to do something, it consults:

```sh
$ .nock/nock consult '{"intent": "Move orders to Postgres.", "context": "SQLite locks under load."}'
```

A fresh headless agent is given the map, and searches the decisions and the
project's tools. It changes nothing, and answers within `consult.deadline` seconds with
the decisions that bear on the work and the tools that help; the calling
agent waits for it. The primer tells agents to consult while they work out
how to do something, unless the task is really straightforward and
unambiguous.

## Reflection

A round is the `/nock-reflect` skill, which `nock init` installs, run in a
session like any other. When one is due, the session start says so, to the
agent and to you: by default after 15 sessions or 7 days, whichever comes
first.

1. **`nock reflect start`** starts the round, named by its date, and writes
   what its parts read into `.nock/local/reflections/DATE/`.
2. **Three subagents**, at once:
   - **the toolbox** reads the work and the telemetry — what the human asked
     for, where the code is going, each tool's calls and failures, commands
     agents tried that do not exist, raw shell work that recurs, the last
     round's expectations — and adds, changes or retires tools, checks and
     generators (retired tools go to `.nock/tools/archive/`), or changes
     nothing, when nothing earns a change;
   - **the map** reads the decisions recorded, changed and reviewed since
     the last round, rewrites the map and merges near-duplicate tags;
   - **nock** reads the window's numbers beside every earlier round's — the
     first round's are the baseline — looks behind them, and forms an
     opinion: what works, what does not, what nock should change.
3. **The report**, `.nock/reflections/DATE/report.md`: what needs the owner,
   what changed in the toolbox and the map, and how nock is doing here.
4. **The summary to share**, `share.md` beside it: the same, abstractly
   enough that nobody could tell which project it is.
5. **`nock reflect finish`** requires both, runs nock's checks — the tools
   load and their examples run, the map's citations hold, the summary names
   nothing of the project (no paths, file names, the project's or its
   authors' names, addresses or links) — and records the round in
   `record.json`: the toolbox's changes with what each should do by the next
   round, verdicts on the last round's, the window's numbers and each tool's.
   It commits `.nock/`.

The round ends by asking the owner whether to share the summary. `nock share
'{"visibility": "private"}'` has a fresh agent vet it — it reads the project
to learn its names, people, partners and customers, and rewrites whatever
would identify it — scrubs the result again, and shows exactly what would be
sent. With `"send": true` it goes to nock's makers (`private`), or is
published on nock.dev (`public`). Nothing is sent otherwise.

### The logika round

In a [Logika](https://logika.host) project (a `logika.json` ledger at the
root, the `logika` CLI on PATH) there is a second kind of round: the
`/nock-reflect-logika` skill, which `nock init` installs only there. It
turns the instrumented code and the data it captures into the ledger's
rules (validations, paths, timeouts, rules and invariants) for how the
system is expected to behave, so that Logika wakes an agent when it
doesn't.

It is never automatic. It runs only when the owner asks. When one is due,
the session start offers it at most once a week: when no logika round has
run yet and the ledger declares events, or `reflect.logika.days` (30)
after the last one, once `logika.json` has changed since then. `nock
status` always says.

1. **`nock reflect start --topic logika`** writes its material: what the
   ledger already says per event and per component (with the commits that
   touched each component since the last round), the ledger's history,
   the last logika round's changes and expectations, and the questions
   and suggestions tagged `logika`.
2. **The session works through it with the owner.** It learns the forms
   from Logika's own docs (`logika docs …`) instead of a copy, explores real
   captures with `logika show query`, and agrees with the owner what must
   hold. It lands a rule only once it has seen the rule stay quiet on a
   real capture (`logika test`) and fire on a replay (`logika test
   --replay`). False positives are the cost it guards against first.
3. **What only the owner knows** is asked in the session. A question for
   later becomes a question decision tagged `logika`, and the next round
   acts on the answer. A rule that needs state the code doesn't record
   becomes a todo tagged `logika` and `instrumentation`, not a weaker rule.
4. **`nock reflect finish --topic logika JSON`** requires the round's
   `report.md` and a `logika.json` that parses. It records the rules
   changed, how each was tested, and the ledger's numbers before and after
   in `.nock/reflections/logika/DATE/record.json`, and commits `.nock/` and
   `logika.json`. Deploying the ledger (`logika sync`) is left to the
   owner's word.

Logika rounds are kept apart from nock's own, so neither moves the other's
window.

## Reference

### Commands

| command | does |
|---|---|
| `nock` | the toolbox: the project's tools first, then nock's |
| `nock check [NAME…] [--fix]` | run the checks (all, or the checks and chains named), side by side; prints nothing when all pass |
| `nock run -- COMMAND` | run anything supervised and condensed |
| `nock guide` | how to write a tool, check, hook or generator |
| `nock calls`, `stats`, `sessions`, `query SQL` | the telemetry |
| `nock status` | a round due, decisions waiting, rejected ones to rework, answered questions, an unshared summary, a logika round to offer |
| `nock decide JSON` | record a decision |
| `nock decisions list [JSON]`, `show N`, `edit JSON`, `elaborate N` | the decisions: filtered, in full, changed or reviewed, elaborated |
| `nock web [JSON]` | the owner's page |
| `nock consult JSON` | a fresh agent finds the decisions and tools that bear on a task, and the caller waits |
| `nock reflect start`, `finish JSON` | a reflection round; the round is the `/nock-reflect` skill; `--topic logika` for a logika round (`/nock-reflect-logika`) |
| `nock share JSON` | a round's summary, and sending it |
| `nock gen write`, `new`, `add`, `set`, `rm`, `show`, `bind`, `unbind` | generators |
| `nock init`, `nock upgrade` | install (or re-wire), and upgrade the vendored core to the latest release, with a three-way merge |

Every command takes `--json` and `--full`, and every cached command also takes
`--fresh`.

### Exit codes

The codes are modelled on HTTP's, and each one tells the agent what to do
next.

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

### Settings

`.nock/config.toml` is committed. `.nock/local/config.toml` overrides it on
one machine.

| key | default | is |
|---|---|---|
| `branch` | `main` | the main branch, which `changed` diffs against |
| `output.characters`, `output.rows` | 8000, 60 | the cap on what a call prints |
| `run.deadline`, `run.silence` | 3600, 900 | seconds before a supervised process is stopped |
| `checks.NAME.command`, `fix`, `chain`, `directory`, `deadline`, `silence`, `failure_codes` | — | a command that is a check; the command that fixes what it finds; the chain it runs in, after the chain's earlier checks; where it runs and its bounds; the exit codes that mean the code is wrong (`[1]`) |
| `checks.concurrency` | 2 | checks run at once, machine-wide |
| `reflect.sessions`, `reflect.days` | 15, 7 | when a round is due, whichever comes first |
| `reflect.logika.days` | 30 | in a Logika project, days after a logika round before the next is offered (once the ledger has changed) |
| `agent.command`, `agent.model`, `agent.deadline` | `claude`, —, 1800 | the headless agent nock dispatches (elaborate, consult) |
| `consult.deadline` | 600 | seconds a consultation may take |
| `upgrade.check`, `upgrade.index` | true, PyPI's `nock` | whether a session start says a newer nock is out, and where releases are looked up |
| `share.endpoint` | `https://api.nock.dev/reflections` | where `nock share` sends a summary |
| `environment.python`, `setup`, `path`, `dotenv` | —, —, `[]`, — | what tools run in: the project's interpreter and how to make it, PATH entries, a dotenv file |
| `pricing` | — | per-model prices, to cost sessions |

## Developing nock

See [ARCH.md](ARCH.md) for how the code is laid out.

```sh
uv sync
uv run pytest -n 4        # real repositories and processes, no mocks
uv run ruff check && uv run basedpyright
uv run nock init          # in another repository: vendor this checkout into it
```

`evals/` measures whether reflection pays (`evals/README.md`), and whether nock
helps through a month of real work (`evals/story/README.md`).
