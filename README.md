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
- allows each `.nock/nock` command in Claude Code's permissions, one rule
  per command, except `run` (it runs any command, so Claude Code treats it
  as that command) and the commands that need the owner's word, which Claude
  Code asks about (see [What nock's agents may do](#what-nocks-agents-may-do));
- installs the skills, and the subagents a round's parts run as.

Commit the result. From then on, every agent session in the repository starts
with the project's tools listed, and is recorded when it ends. nock speaks up
unasked only a little, and `reminders = false` silences it (see [What agents
see](#what-agents-see)); it shares a usage report only if you say yes when it
asks (see [What nock shares](#what-nock-shares)).

To upgrade, `.nock/nock upgrade`. It merges the latest release from PyPI into
the vendored core, keeping any local edits to it (a three-way merge against
the release you have), and re-wires the project: primer, hooks and skills.
Once a day at most, a session you start asks PyPI whether a newer nock is out
and says so; `upgrade.check = false` turns that off. Once a day at most, too,
nock fetches LiteLLM's public price table from GitHub (`pricing.table`), a
plain GET that sends nothing about the project, to cost sessions at API
prices; `pricing.fetch = false` turns that off.

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

The tool works on its next call, with nothing to register. `.nock/nock docs`
is the framework written for agents, one short article per term (`.nock/nock
docs` lists them, `.nock/nock docs fixtures` reads one, and a term it doesn't
know answers with the three closest). In short:

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
  `.nock/nock db NAME`. `Annotated[str, nock.Option("--from", help="…")]`
  gives an option its help or its own flag, and `rest="words"` hands
  `words` every word after `--`, verbatim, for a tool that passes them on.

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
approve it although the toolbox's other commands are allowed, and the
toolbox lists it as asking the owner. The `nock-wiring` check fails while
the rule is missing. A new tool is asked about until `nock init` allows it
(`nock-wiring` says so), and `nock init` itself asks the owner. An owner
who runs Claude Code with bypassed permissions and wants no prompts at all
sets `permissions.confirm = "allow"`: `nock init` then allows these commands
too, the toolbox lists them as for when the owner's request calls for them,
and an agent runs them only then.

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

Two variables choose how `.nock/nock` starts nock itself: `NOCK_PYTHON` the
interpreter (`python3`), and `NOCK_SOURCE` the directory nock's code is
imported from (`.nock/core`). `NOCK_SOURCE=/path/to/nock/src` runs a project
on a checkout of nock without vendoring it again.

### Long-running and interactive commands

`sh(command, stream=True)` says the command line on stderr and prints the
output as it arrives instead of
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

`nock gen write` writes the generated files, in the order they are
defined and each before the next is generated, so one may read a file an
earlier one writes (types from a schema it generates). `nock check` fails
when one of them has drifted.

## What agents see

Every session starts with the project's tools listed, through Claude Code's
SessionStart hook. CLAUDE.md imports a short primer, `.nock/context.md`: why
the project uses nock (to stay coherent across sessions), to consult before
changing code, recording decisions, `nock run`, and offering to tell nock's
makers what nock lacks with `nock report` (see [Telling nock's makers what
you need](#telling-nocks-makers-what-you-need)). A session the human
starts also hears where things stand, in a few lines — once a day, or sooner
when something new calls (a round falls due, the owner rejects a
decision) — with a word on what to do with it: take into account
what bears on the request, and mention the rest to the human only when
relevant or once the work is done. `.nock/nock` with no arguments lists the
toolbox.

**`reminders = false`** in `.nock/config.toml` keeps nock silent unless
asked: no toolbox or standing at a session's start, no reviews at a prompt,
no decisions after an edit, and a primer that only says what nock is. Every
session and call is still recorded, `nock status` still answers, and the
project's own hooks still run. The primer follows the committed settings (a
session start rewrites it when they change), so set it in
`.nock/local/config.toml` to quiet only the hooks on your machine.

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

## Telemetry

Everything is in `.nock/local/nock.db`, a local SQLite file that is never
committed:

| table | holds |
|---|---|
| `calls` | every nock call, including refused ones: the command, its arguments, session, duration, exit code, bytes printed and in full, whether it was cached, and the error |
| `runs` | every supervised process; the logs are in `.nock/local/logs/` |
| `sessions` | each Claude Code session's role, title, tokens by kind, API-equivalent cost, prompts, interrupts and compactions |
| `prompts` | what the human typed |
| `events` | every tool call of every session: the command, path or pattern, whether it failed, the bytes returned, and the duration |
| `heard` | which sessions were told the owner's reviews of the decisions they recorded |
| `shown` | which sessions were shown the decisions behind a file they edited |
| `nudged` | what a session start said and when: the day's standing, a round's unshared summary, a logika round's offer |
| `transcripts` | how far each session's transcript has been read, and what reading on needs |

Sessions are read from Claude Code's transcripts when they end and whenever
telemetry is read (`nock usage` and its report, `stats`, `status`, `query`,
`sessions`, a session start's standing, a round): each transcript is read on
from where the last read stopped, so a session that runs for days is counted
as it goes and nothing is counted twice; a transcript that has not grown costs
one `stat`.

- **Roles.** A session someone works in is `interactive`. A `claude -p` run or
  an Agent SDK session that nock did not dispatch (its transcript says
  `"entrypoint": "sdk-…"`) is `headless`: graders, planners, CI. Headless
  sessions are kept out of the numbers (sessions, requests, interrupts, tool
  calls) and out of what a reflection round reads; the usage report counts
  them apart, as `headless_sessions`. Sessions nock dispatched carry their
  role (`consultant`, …).
- **Windows.** A window's requests and tool calls are those made inside it,
  even in a session that began before it; tokens are the sessions'.
- **Cost** is API-equivalent: what the tokens would cost at the API's list
  prices, by model and kind (input, output, cache read, cache write) — a
  subscription does not pay per token. The prices are LiteLLM's public table,
  fetched at most daily and cached in `.nock/local/prices.json`; `[pricing]`
  overrides them by model-name prefix. A model in neither, or no table at all
  (offline, `pricing.fetch = false`), leaves the session unpriced: its cost is
  unknown, never 0, and totals say how many sessions they leave out.
- **Calls made while another nock call runs are not recorded.** Every nock
  command sets `NOCK_UNRECORDED=1` for what it starts, so a test suite run by
  `nock check`, `nock run` or a project's test tool never records the nock
  calls its tests make. A call an agent makes directly is recorded, and so
  are those of the agents nock dispatches. Set `NOCK_UNRECORDED=1` yourself
  for anything else that should stay out.

To look:

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

A decision is recorded only when a later reader would ask "why": a choice
between real alternatives the owner hasn't already made, a deliberate
simplification, or a reading of something ambiguous. Carrying out the
owner's explicit instruction is not a decision (the instruction is the
record), nor is a routine implementation detail, a change to an existing
decision (edit it instead), or the same thing twice: `decide` refuses a
title a standing decision already has, or nearly (normalised text
similarity), naming its number, unless `--force`. An alternative nobody
weighed is not an alternative. With `"status": "todo"` it is something that should be
done and is not yet; a possible improvement is a todo tagged `improvement`.
What only the owner can settle, when they are not there to ask, is a
decision tagged `important`: the title is the answer the agent proposes
("Refunds never exceed the charge"), the alternatives the other answers it
sees, and the agent carries on with it. The summary is written for someone who knows what the system does,
but not how it is built.

Each decision is a file, `.nock/decisions/0007.json`, written and committed in
the main checkout whichever worktree recorded it. A project can fix its tags
in `.nock/config.toml`:

```toml
[decisions]
tags = ["core", "web", "deploy", "billing"]
```

Then `decide` and `edit` refuse any other tag, naming the allowed ones, and
`decide --help`, the primer and the studio's tag filter list them (the filter
only those that would show something), and review items draw from the same
list; `important`
is always allowed, and so are a logika round's `logika` and `instrumentation`.
Without a vocabulary, tags are `important`, `technical`, `product`,
`improvement` and the agent's own: a topic the owner would look at together
(`pricing`, `emails`), never the project's or product's name, and none when
nothing fits; `decide` prints the
tags in use, so a near-duplicate is caught early. `touches` names the files or
globs it governs, and `supersedes` the decisions it overturns, which stay as
history. A decision that should never have been recorded is deleted,
`nock decisions delete 7`, in one commit; git keeps it.

| | unreviewed | accepted | rejected |
|---|---|---|---|
| **done** | done; please check | it stands | rework it |
| **todo** | worth doing later? | on the backlog | do not do it |

A decision tagged `important` is the owner's call: accepted, it holds as
proposed; rejected, it is reworked as the note says. While it is unreviewed,
the session start lists it, once a day. (A decision an earlier nock recorded
as a question reads as one done and tagged `important`, its review kept.)

- **The owner reviews.** In the studio, `nock studio` (or with
  `{"open": true}`), the owner's local page: its Decisions tab lists the
  decisions to review, accepted and rejected, searchable and
  filtered by status, important and tag, each card's tags at its foot; `#decisions/7` (or just `#7`) in its address
  opens decision 7. Or in a
  session, with `/nock-triage`, which goes through them one at a time. Each
  can be accepted, rejected or noted; asked for more, the session looks into
  it itself.
- **The session that recorded it hears.** When the owner next types there,
  the prompt hook tells it what they said, once.
- **Work changes the record.** `nock decisions edit` reworks a rejected
  decision, or marks a todo done, in place; git keeps the history. It sets
  `superseded_by` too (null: the decision stands again), keeping the other
  side's `supersedes` in step; a `supersedes` entry naming a deleted decision
  is dropped. Each call is a commit; `nock decisions batch '{"edit": […],
  "delete": […]}'` makes many changes in one, or none if one is refused. A change
  to what a decision says asks for a fresh review, and keeps the owner's
  note. `review` and `note` are the owner's word: agents set them only when
  told to.
- **An edit shows the decisions behind a file.** The first time a session
  edits a file a standing decision touches, the edit hook shows it — the
  rejected ones first, with the owner's note.
- **"Elaborate" starts an agent at once.** It reads the project and deepens
  the summary, evidence and alternatives, answering the owner's note
  (`nock decisions elaborate N`).

Once a day (sooner when something new calls), a session the human starts
says how many important decisions, todos and done decisions wait on review,
the important ones not yet reviewed and the rejected ones to rework (the
first few of each), and how many todos the owner accepted and notes they
left since the last round — a note often asks for something. `nock status`
says it all in full, and whether a reflection round is due.

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

Before an agent changes code, it consults:

```sh
$ .nock/nock consult '{"intent": "Move orders to Postgres.", "context": "SQLite locks under load."}'
```

A fresh headless agent is given the map, the project's tools and checks,
and reads the decisions that govern what the work touches. It changes
nothing, and takes the intent as given: it doesn't redesign the task. It
advises in a few lines — what the decisions mean for this work (what to keep
to, a rejected option the work would bring back, a todo it could
close, and first, plainly, an accepted decision the intent
goes against), the tools that do its steps, a choice the work is about to
make that should be recorded, and the checks to pass — or says that nothing
in nock bears on it. It submits with `nock advise`, which refuses a decision,
tool or check that doesn't exist, so it fixes the name; the calling agent
reads the advice exactly as submitted, followed by each named decision's
title and standing, each tool's usage and the `nock check` to run. Where
nock fell short for the task goes to the next reflection round. The caller
waits up to `consult.deadline` seconds.

The primer asks agents to consult before changing code, unless the task is
really straightforward and unambiguous. **`consult.enabled = false`** turns
it off: the primer no longer mentions it, and `nock consult` says so and
dispatches nothing.

## Review

What an agent makes for the owner to look at — a screenshot of a page it
changed, a video of a flow, a PDF, an HTML email, the text a command prints —
it registers for review, an item the owner judges in the studio. Each has a
stable key, and registering the key again adds a version: the latest
supersedes the earlier ones, which stay to compare against.

```sh
$ .nock/nock review add '{"key": "email/anomaly-report",
    "title": "The anomaly report email", "tags": ["anomalies"],
    "files": ["out/anomaly-report.html"],
    "note": "The headline leads with the count.", "decision": 12,
    "recipe": {"command": "uv run python dev/render.py anomaly --output $NOCK_REVIEW_OUTPUT",
               "instruction": "Render the anomaly email with the fixture, as the owner asks."}}'
```

`files` are images, videos, PDFs, HTML pages and text files (`.txt`, `.md`,
`.json`, …); `text` is a text given inline. A version leaves out what it
keeps of the last: the title, tags, decision and recipe carry over. The `note`
says what this version is, or what changed; `decision` is the decision it
illustrates. A tag names a topic the owner would look at together across keys
(`anomalies` groups the email with the queue's screenshot), never the
product, the project or what the key and the kind already say (`email` on
`email/…`, `prompt`, `screenshot`); most items need none. When the project
fixes its tags (`decisions.tags`), an item's come from them, `important`
aside, and `review add --help` lists them; without, any lowercase tag goes. Each version is a directory, `.nock/review/KEY/N/`, its record
`version.json` beside its files, written and committed in the main checkout
whichever worktree registered it, as decisions are. A file over 20 MB (most
videos) stays on the machine, under `.nock/local/review/`, uncommitted, and
the record says so (`"local": true`).

`nock review list` lists the items by their latest version (filtered by
`tag`, `verdict` or a key `prefix`), `review show KEY` has every version and
where each file is, and `review delete KEY` (or `--version N`) removes one
that should not be shown, in a commit; git keeps it.

- **The owner judges the latest version.** On the studio's Review tab, or
  `nock review judge KEY '{"verdict": "approved"|"rejected", "feedback": …}'`:
  approved, rejected, or a note (`feedback`); like a decision's review, it is
  the owner's word, which agents set only when told to.
- **Rejected or noted, it is made again.** Until a new version comes, the
  session start lists it (the first few, once a day, sooner when something
  new calls), with the owner's note and a pointer to how it was made.
- **"Regenerate" makes the next version.** `recipe.command` runs in the
  working tree (`sh -c`) with the owner's note in `$NOCK_REVIEW_FEEDBACK`, and
  what it writes into `$NOCK_REVIEW_OUTPUT` is registered as the next version.
  With `recipe.instruction`, nock dispatches an agent (the regenerator seat)
  with the instruction, the note and the current version; it makes the
  files in its own work directory, may run the recipe's command, and
  registers them. Either way the new version records what it was made from
  and the note it answers. `nock review regenerate KEY` does the same from a
  terminal; Claude Code asks the owner first, since it runs the recipe.

The Review tab shows the items as a grid of thumbnails or a list, filtered as
the Decisions tab filters: by verdict (to review, approved, rejected), by tag
(only the tags that would show something in that tab) and by a search on the
key and title; `#review/KEY` opens one, in its verdict's tab. The viewer shows a picture (fit, or
zoomed and scrolled), a video, a PDF, a page (an HTML page runs no script
there) or a text, and any version; "Compare" puts two side by side — the
last two, unless picked — and a text's as a line diff, the changed words of
a changed line marked. Next to Approve, Reject and Note, Regenerate saves
the note and makes the next version, which shows up when it is registered;
the tab keeps up with what agents register without drawing again what did
not change, so a picture, page or video loads once, and a note being written
stays. Keys: `a` approve, `r` reject, `n` note, `g` regenerate, `c` compare,
`←`/`→` between items, `esc` back.

## Reflection

Rounds come in kinds. nock's own is the default: `nock reflect` starts it,
and `nock reflect finish JSON` ends it. Another kind is named:
`nock reflect logika`, then `nock reflect logika finish JSON` (see [The
logika round](#the-logika-round)). Each kind has its skill, the files its
lead writes and the checks its end must pass, and keeps its rounds apart.
A session that started a round cannot end its turn while the round is
open: nock refuses the stop once, naming the kind and what is still
missing (the files to write, what the checks find, the `finish` to run),
and lets the next stop through.

nock's round is the `/nock-reflect` skill, which `nock init` installs, run in a
session like any other. When one is due, the session start says so, to the
agent and to you: by default after 15 sessions or 7 days, whichever comes
first.

1. **`nock reflect`** starts the round, named by its date, and writes
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
5. **`nock reflect finish JSON`** requires both, runs nock's checks — the tools
   load and their examples run, the map's citations hold, the summary names
   nothing of the project (no paths, file names, the project's or its
   authors' names, addresses or links) — and records the round in
   `record.json`: the toolbox's changes with what each should do by the next
   round, verdicts on the last round's, the window's numbers and each tool's.
   It commits `.nock/`.

The round ends by asking the owner whether to share the summary. `nock share`
has a fresh agent vet it — it reads the project
to learn its names, people, partners and customers, and rewrites whatever
would identify it — scrubs the result again, and shows exactly what would be
sent. With `'{"send": true}'` it goes to nock's makers, who alone read it;
nothing is published. Nothing is sent otherwise, and nothing at all when
`share` is false.

### The logika round

In a [Logika](https://logika.host) project (a `logika.json` ledger at the
root, the `logika` CLI on PATH) there is a second kind of round: the
`/nock-reflect-logika` skill, which `nock init` installs only there. It
has two parts, run as subagents while the session works with the owner:

- **rules** turns the instrumented code and the data it captures into what
  must hold (validations, paths, timeouts, rules, invariants and error
  marking), so that Logika wakes an agent when the system misbehaves, each
  rule with a one-sentence `description` that becomes the anomaly's title;
- **analytics** declares what the owner wants to measure (which params are
  identities and dimensions, funnels, milestones and views), so that
  Logika's analytics fill from real captures.

It is never automatic. It runs only when the owner asks. When one is due,
the session start offers it at most once a week: when no logika round has
run yet and the ledger declares events, or `reflect.logika.days` (30)
after the last one, once `logika.json` has changed since then. `nock
status` always says.

1. **`nock reflect logika`** writes each part's material: for rules, what
   the ledger already says per event and per component (with the commits
   that touched each component since the last round); for analytics, each
   param with its flags and the events that carry it, and the funnels,
   milestones and views declared; for both, the ledger's history, the last
   logika round's changes and expectations, and the decisions and
   suggestions tagged `logika`.
2. **The session works through it with the owner.** It learns the forms
   from Logika's own docs (`logika docs …`) instead of a copy, explores real
   captures with `logika show query`, and agrees with the owner what must
   hold and what to measure. It lands a rule only once it has seen the rule
   stay quiet on a real capture (`logika test`) and fire on a replay
   (`logika test --replay`), and a declaration only once captures show the
   events and params it names. False positives are the cost it guards
   against first.
3. **What only the owner knows** is asked in the session. A question for
   later becomes a decision tagged `logika` and `important`, the answer the
   session proposes and carries on with, for the owner to accept or reject. A rule or a measure that needs state the code
   doesn't record becomes a todo tagged `logika` and `instrumentation`, not
   a weaker rule or an empty funnel.
4. **`nock reflect logika finish JSON`** requires the round's
   `report.md`, a `logika.json` that parses, and every rule changed to say
   how it was `tested`. It records the rules and declarations
   changed, how each was tested, and the ledger's numbers before and after
   in `.nock/reflections/logika/DATE/record.json`, and commits `.nock/` and
   `logika.json`. Deploying the ledger (`logika sync`) is left to the
   owner's word.

Logika rounds are kept apart from nock's own, so neither moves the other's
window.

## What nock's agents may do

nock never bypasses Claude Code's permission checks: no code path passes
`--dangerously-skip-permissions` or `--permission-mode bypassPermissions`,
and nock refuses an `agent.command` that does (or that sets the permission
flags nock sets itself). A test holds the package, the evals and the
scripts to it.

**In your sessions,** the rules `nock init` writes into
`.claude/settings.json` are all there is, one per command, nothing that
runs arbitrary shell:

- `allow`: `.nock/nock` (it lists the tools) and each of the toolbox's
  commands, nock's and the project's, which read, record in `.nock/`, or
  run the project's own committed tools and checks;
- `ask`: every `confirm=True` command, the project's and nock's own:
  `init` (it rewrites these rules), `upgrade` (it fetches and merges code)
  `share` (it sends a summary out) and `report` (it sends what you wrote
  to nock's makers). Claude Code asks about these even
  in bypass mode; `permissions.confirm = "allow"` in `.nock/config.toml`
  moves them to `allow` and leaves nock no `ask` rule, and the agents are
  told to run them only when the owner's request calls for them;
- no rule for `run`, which runs any command: Claude Code asks about it as
  it would about the command itself.

Re-running `nock init` replaces nock's own rules and keeps everyone else's;
it removes the blanket `Bash(.nock/nock:*)` earlier versions wrote, which
`nock-wiring` flags until then.

**The agents nock dispatches** (`claude -p`, no human in the session) run
in `dontAsk`: each has the Claude Code tools and allow rules its brief
needs and nothing else, and anything else is refused, never prompted, so
a run cannot hang on a question. The project's and the checkout's own
Claude Code settings are not loaded (`--setting-sources user`), so the
project's allow rules never widen a seat (nor are the project's CLAUDE.md,
skills, hooks or MCP servers: the brief carries what the seat needs).
Reading files in the directory it runs in needs no rule.

| seat | tools | may run |
|---|---|---|
| consultant | Read, Grep, Glob, Bash | `.nock/nock decisions list`, `decisions show`, `docs`, `advise` |
| elaborator | Read, Grep, Glob, Bash | `.nock/nock decisions list`, `decisions show`, `docs`, `decisions edit`; `git log`, `git show` |
| regenerator | Read, Grep, Glob, Bash, Edit, Write | `.nock/nock review show`, `review add`, `docs`; `git log`, `git show`; the item's recipe command; reading and writing only its own work directory, `.nock/local/regenerations/…` |
| sharer | Read, Grep, Glob, Bash | `git log` |

`git log` and `git show` are allowed without `--output` (or any
abbreviation of it git accepts, down to `--ou`), which a deny rule refuses:
it would write their output to a file.

None but the regenerator can edit a file, and it only in its work
directory; none can reach the network or run any other command. What
Claude Code refused comes back with the session: in the consultation's
record and its failure, in the elaboration's result, in the vetted summary's
record and the share's failure, and in the run's log.
The owner's user-level Claude Code settings still apply to these sessions:
they are the owner's.

**A round's parts** are subagents of the session running the round, so
the session's permissions apply, narrowed by the subagent types nock
installs in `.claude/agents/`: the toolbox part (`nock-reflect-toolbox`)
reads, edits and runs commands, and its brief keeps it to `.nock/`; the map
part (`nock-reflect-map`) reads and edits the map; the nock part
(`nock-reflect-nock`) and the logika round's parts (`nock-logika-rules`,
`nock-logika-analytics`) only read and run commands, with no tool that
edits a file. A refused call is reported, not worked around.

## What nock shares

nock tells its makers how it is used, so they can improve it ([privacy
policy](https://nock.dev/privacy/)), but only with the owner's yes. `share` in
`.nock/config.toml` (or, for one machine, `.nock/local/config.toml`) is their
answer, and has no default:

- **unset**: unanswered. Nothing is sent and no id is made until the owner
  answers (below).
- **`share = true`**: a weekly usage report, counts
  and categories only. Each report carries nock's version, Python's (`3.12`)
  and the platform (`darwin`, `linux`); whether reminders and the consultant
  are on and whether it is a Logika project; the window's numbers that a
  reflection round also keeps (how many days, sessions and headless ones,
  requests, interrupts, compactions, tool calls and failed ones, tokens in
  all and by kind, the API-equivalent cost and how many sessions are unpriced,
  commits, nock calls by how they ended, consultations, decisions by status
  and review, how many of the project's tools were used and how often, the
  map's length and citations); calls and failures per nock command (`check`,
  `decide`, …: nock's own names); how many tools, checks, hooks and
  generators the toolbox has and how many failed to load; and how many
  rounds have run. Never code, paths, file or tool names, prompts, command
  arguments, what decisions say, or anything else written in the project.
  It also carries the project's id: a random UUID, committed in
  `.nock/project.json` so every clone of the project sends the same one. It
  is made only as the first report is sent, after the owner said yes (until
  then `nock usage` shows "(created when the first report is sent)" in its
  place), is derived from nothing — not the path, the remote or any name —
  and lets nock's makers count projects without knowing which; since every
  report of a project carries it, the reports are pseudonymous rather than
  anonymous. Nothing is published.
- **`share = false`**: nothing is ever sent — no report, no id is made, and
  `nock share` won't send a summary either. Only what you write and send
  yourself with `nock report` (below) still goes.

An earlier nock's `[share]` table with `level` still reads: `"none"` as
`share = false`, any other level as `share = true` (which now sends only the
anonymous report, never tool names); `nock usage` notes it until the table
is replaced.

nock asks the owner once on a machine, while nobody has answered, the first
time they engage with nock there: the first reflection round, opening the
studio (`nock studio`), or their first review or note on a decision. The
page shows the question under the title with **Share** and **Don't share**
until it is answered; the round and `/nock-triage` ask it in the session
(`ask_the_owner`), and the agent records exactly what the owner says with
`.nock/nock usage share yes` or `.nock/nock usage share no`. Either writes
`share` to the main checkout's `.nock/config.toml` and commits it (or to
`.nock/local/config.toml` when that already sets it), and keeps when the
answer was given, where, and the version of the question in
`.nock/local/usage.json`, so the consent can be shown. A `share = true` or
`share = false` already in a config is an answer, and is never asked about.
Counting starts at the yes. The first report goes a week later, as a
session ends, then at most weekly, to `endpoints.usage`, with a three-second
timeout; a failure is silent and tried again a day later. `.nock/nock usage`
shows the answer (unanswered, yes or no), when it was asked and given, the
reports sent and exactly what the next would carry (while unanswered too, so
the owner sees what they are asked about).

A round's summary is sent only with `nock share` and the owner's yes (see
[Reflection](#reflection)).

### Telling nock's makers what you need

When nock lacks something you need, or something in it is broken or
confusing, tell its makers: they read what arrives and it shapes what they
build next.

```sh
.nock/nock report "I need nock to list the decisions a commit touched."
```

The text is the argument, or stdin. It goes to `endpoints.reports` with
nock's version and the platform (`darwin`, `linux`) and nothing else —
nothing from the repository unless the text says it — and the makers'
answer is a reference id, printed with what was sent. On a terminal nock shows
exactly what would go and asks `[y/N]`; with no terminal to ask on (an
agent's session) it refuses unless `--yes` is passed, and shows what it would
have sent. The primer tells agents that this channel exists and matters:
when you need something nock lacks, your agent offers to send it, and sends
it only on your go-ahead (then with `--yes`), never code or secrets unless
you ask; Claude Code asks you before each call too (it is a `confirm=True`
command). The text is at most 10,000 characters. Reports are sent whatever
`share` says: each is something you wrote and chose to send.

## Evaluations

Does a change make the agents better? An evaluation answers it with real
runs, and keeps every intermediate result so the next question costs only
what changed. A scenario is a [Snakemake](https://snakemake.github.io/)
workflow in git beside the code; nock adds a profile, a budget, the reasons
a run reruns, pruning, and SQL over the results:

```
evals/detect/
  Snakefile                rules are steps, wildcards parameters
  profile/config.yaml      nock's Snakemake profile (`eval init` writes it)
  parameters/bug/none.json a parameter's values as files (bug=none is the clean twin)
  steps/plant.py           Step(snakemake).run(run): metrics.json, cost.json, error.json
  cache/3f2a…/             committed: each output, named by its provenance hash
  results/plant/bug=none/  this checkout's links into cache/ (not committed)
```

```python
BUGS = glob_wildcards("parameters/bug/{bug}.json").bug

rule all:
    input: expand("results/score/bug={bug}/rep={rep}", bug=BUGS, rep=[1, 2, 3])

checkpoint detect:
    input: "results/plant/bug={bug}"
    output: directory("results/detect/arm={arm}/bug={bug}/rep={rep}")
    params: keyed=lambda wildcards: dict(wildcards)
    cache: "omit-software"
    resources: agents=1, estimate_cents=40
    script: "steps/detect.py"
```

- **A step** is a rule whose output is a directory under
  `results/RULE/NAME=VALUE/…`, its script wrapped in
  `Step(snakemake).run(run)`: `run(step)` returns its numbers
  (`metrics.json`); `step.spend(usd, tokens)` and the seconds it took go
  to `cost.json`; a raise is `error.json`, a failed result, and a step one
  of whose inputs failed fails without running. `step.value("arm")`
  is a wildcard, `step.metrics("control")` an input's numbers, and
  `step.agent(brief, allowed=["Edit", "Bash(pytest:*)"])` dispatches a
  headless agent as nock dispatches its own, in `dontAsk` with that
  allowlist and nothing more, its cost counted. State the next step resumes
  from is `state.tar` (`step.pack(directory)`, `.git` included;
  `step.unpack()`), and a repository's change against the state before is
  `diff.patch`.
- **Forks, joins, `when`.** A fork is several jobs reading one output; a
  join is a rule with several inputs; `when` is an input function that
  returns `[]` or the branch to take, reading an earlier output's
  metrics.json through a `checkpoint`.
- **Memoisation is by content.** Every rule is `cache: "omit-software"`
  with its wildcards in its params, so Snakemake names its output by a hash
  of the rule's script, params and input files' content and the hashes of
  the jobs before it. `cache/` is committed: a fresh clone, whose files all
  have new mtimes, restores every output that matches and computes only the
  rest. Order the rules so the expensive-to-vary come first.
- **A cache outside git.** When outputs are too big to commit (whole
  repositories, databases), `[eval] cache = "~/.cache/my-evals"` in
  `.nock/config.toml` keeps each scenario's cache in that directory's
  `NAME/` instead; everything else works the same, on that machine.

```sh
$ .nock/nock eval init detect                     # scaffold evals/detect/
$ .nock/nock eval run --dry                       # each job: from cache, or compute and why
$ .nock/nock eval run --budget 20                 # refused if the estimate passes $20
$ .nock/nock eval run results/score/bug=none/rep=1
$ .nock/nock eval run --limit agents=1 --retry      # one agent at a time; the failed again
$ .nock/nock eval import outputs.json              # outputs computed elsewhere, into the cache
$ .nock/nock eval query "SELECT rule, state, sum(cost_usd) FROM outputs GROUP BY ALL"
$ .nock/nock eval compare '{"by": "arm", "metric": "detected", "step": "detect", "unit": "bug"}'
```

`eval run` runs Snakemake with the profile (`--cores`, `keep-going`,
per-resource limits such as `agents=2`), on the default target or the
targets named. A dry run comes first: what reruns and why, in Snakemake's
words, and the estimate from each rule's mean past `cost.json` (or its
`resources: estimate_cents`); it refuses outputs that would share a cache
entry, Git LFS pointers in the cache, and, with `--budget`, an estimate past
it. **`eval query`** reads the result files with DuckDB (read-only, loaded
fresh each time, no index): `outputs`, `metrics`, `diffs` and a table per
rule with a column per wildcard and metric, so comparing arms is a
self-join on the wildcards they share. **`eval compare`** groups a rule's
current outputs by one parameter, holding the others fixed and pooling
`rep`: each mean with a bootstrap interval and the difference from the
baseline, paired when both sides have the same units. **`eval show`** gives
each rule's outputs current, stale (and why) and failed. **`eval prune`**
(`--dry` first) deletes the cache entries no current output is, and the
failed with what was computed from them, so a run computes them again; a
failed output is otherwise a result, restored rather than retried.
**`eval run --retry`** does that for the failed alone and runs, keeping
each failed attempt for its step to read (`step.previous`: an agent's work
worth keeping when only what followed it broke). `--limit NAME=N`
overrides a resource's limit, so a run takes at most N of what its rules
declare (`resources: stacks=1`). **`eval import`** puts outputs computed
elsewhere (another pipeline's results) into the cache under the entries
their jobs would have, each cloned from its source (copy-on-write where
the filesystem can, never moved) with its metrics, cost or error, so a run
restores them instead of computing them; jobs after a checkpoint are known
once it is restored, so such outputs are imported in rounds. The
`nock-eval` check fails when a rule is not cached by its wildcards or the
Snakefile does not read. Snakemake and DuckDB run through
[uv](https://docs.astral.sh/uv/); nock imports neither.

**More machines.** Another machine is another checkout: it runs part of the
targets, commits `cache/`, and pushes; entries merge as plain files, and the
next run anywhere restores them.

**The studio's Evaluations tab** (`#evals` or `#evaluations`) draws a scenario as a graph: its rules as columns
left to right, a row per value of the parameter that forks the runs, each
group with its runs done, running, failed, stale and not yet run, their
median cost and key numbers, and wires to what was made from it. Hover a
group or a run for what it means, its parameters in words, why it is stale,
its highlights and its files; click it to narrow every column to its right
to what was made from it (the breadcrumb widens back); split a group by the
next parameter that forks inside it. "What if I change" picks a parameter's
value, an input the steps' params carry (a version) or a file, and lights
what would rerun, with a count and an estimate. While a run goes, the page
follows it every few seconds. The comparisons view counts the declared
comparisons as x of y. Snakemake's description of the jobs is kept in
`.nock/local/evals/` and derived again only when the scenario changes, so the
tab opens in a second. An optional `evals/NAME/studio.json` words it:

```json
{
  "rules": {"detect": {"title": "Detection", "means": "…", "metrics": ["detected"],
                       "highlights": ["Detected the bug: {detected}, with {alarms} alarms."]}},
  "parameters": {"bug": {"label": "Planted bug", "values": {"none": "no bug"}}},
  "lanes": "bug",
  "analyses": [{"name": "Does the toolbox find it?", "step": "detect", "by": "arm",
                "metric": "detected", "where": {"bug": "drop-banana"}, "baseline": "control"}]
}
```

Without it a rule means the comment above it in the Snakefile. The tab also
weighs a dry run with targets and a budget, nothing run. `nock docs eval` has the
rest, with the practice that keeps an evaluation honest: fix the inputs,
keep the answers from what is scored, measure the outcome, run enough
repetitions, write the comparison down first.

## Reference

### Commands

| command | does |
|---|---|
| `nock` | the toolbox: the project's tools first, then nock's |
| `nock check [NAME…] [--fix]` | run the checks (all, or the checks and chains named), side by side; prints nothing when all pass |
| `nock run -- COMMAND` | run anything supervised and condensed (Claude Code asks, as for the command itself) |
| `nock docs [TERM…]` | nock's documentation for agents, a short article per term: with no term, the terms |
| `nock calls`, `stats`, `sessions`, `query SQL` | the telemetry |
| `nock status` | a round due, decisions waiting, rejected ones to rework, important ones unreviewed, items to review or make again, an unshared summary, a logika round to offer |
| `nock decide JSON [--force]` | record a decision (`--force` past the duplicate guard) |
| `nock decisions list [JSON]`, `show N`, `edit JSON`, `delete N`, `batch JSON`, `elaborate N` | the decisions: filtered, in full, changed or reviewed, deleted, many at once in one commit, elaborated |
| `nock review add JSON`, `list [JSON]`, `show KEY`, `judge KEY JSON`, `delete KEY [--version N]`, `regenerate KEY` | review: register a version of an item, the items filtered, every version, the owner's verdict, deleted, made again from the recipe (asks the owner) |
| `nock studio [JSON]` | the owner's page, a tab for each thing to look at: the decisions, the items to review, the evaluations |
| `nock eval init NAME`, `run [TARGETS…] [--dry] [--budget USD] [--limit NAME=N] [--retry]`, `import JSON`, `show [NAME]`, `query SQL`, `compare QUERY`, `prune [NAME] [--dry]` | evaluations: scaffold a Snakemake scenario, run it restoring what the cache has (or the failed again), import outputs computed elsewhere, read it, query it with SQL, compare its outputs, delete stale and failed cache entries |
| `nock consult JSON` | a fresh agent advises on a task: the decisions, tools, checks and docs that bear on it; the caller waits |
| `nock advise JSON` | the consultant's advice, submitted; only a consultant nock dispatched runs it |
| `nock usage` | what nock shares with its makers, the owner's answer, and exactly what the next report carries |
| `nock usage share yes\|no` | records the owner's answer on sharing the usage report |
| `nock reflect [KIND]`, `nock reflect [KIND] finish JSON` | a reflection round: nock's own (`/nock-reflect`), or another kind, `logika` (`/nock-reflect-logika`) |
| `nock share [JSON]` | a round's summary as it would be sent, and sending it (asks the owner) |
| `nock report [TEXT] [--yes]` | send nock's makers what you need from nock or what is wrong with it (shows it and asks; with no terminal, only with `--yes`) |
| `nock gen write`, `new`, `add`, `set`, `rm`, `show`, `bind`, `unbind` | generators |
| `nock init`, `nock upgrade` | install (or re-wire), and upgrade the vendored core to the latest release, with a three-way merge (each asks the owner) |

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
| `reminders` | true | whether nock speaks up unasked (primer, session start, prompt and edit hooks); false: silent unless asked |
| `output.characters`, `output.rows` | 8000, 60 | the cap on what a call prints |
| `run.deadline`, `run.silence` | 3600, 900 | seconds before a supervised process is stopped |
| `checks.NAME.command`, `fix`, `chain`, `directory`, `deadline`, `silence`, `failure_codes` | — | a command that is a check; the command that fixes what it finds; the chain it runs in, after the chain's earlier checks; where it runs and its bounds; the exit codes that mean the code is wrong (`[1]`) |
| `checks.concurrency` | 2 | checks run at once, machine-wide |
| `reflect.sessions`, `reflect.days` | 15, 7 | when a round is due, whichever comes first |
| `reflect.logika.days` | 30 | in a Logika project, days after a logika round before the next is offered (once the ledger has changed) |
| `agent.command`, `agent.model`, `agent.deadline` | `claude`, —, 1800 | the headless agent nock dispatches (elaborate, consult, share, regenerate); it may not bypass or set permissions (see [What nock's agents may do](#what-nocks-agents-may-do)) |
| `permissions.confirm` | `ask` | how Claude Code treats a `confirm=True` command: `ask` has the owner approve each call (even in bypass mode); `allow` lets the agent run it, which it does only when the owner's request calls for it (see [What nock's agents may do](#what-nocks-agents-may-do)); `nock init` rewrites the rules after a change |
| `consult.enabled`, `consult.deadline` | true, 600 | whether the consultant runs and the primer asks for it; seconds a consultation may take |
| `upgrade.check`, `upgrade.index` | true, PyPI's `nock` | whether a session start says a newer nock is out, and where releases are looked up |
| `share` | — (unanswered) | the owner's answer to whether nock sends its makers the weekly usage report: unset sends nothing until they answer, false sends nothing, summaries included, only what you send yourself with `nock report` (see [What nock shares](#what-nock-shares)) |
| `endpoints.reflections`, `endpoints.usage`, `endpoints.reports` | `https://api.nock.dev/reflections`, `https://api.nock.dev/usage`, `https://api.nock.dev/reports` | where `nock share` sends a summary, where the usage reports go, and where `nock report` sends what you wrote |
| `environment.python`, `setup`, `path`, `dotenv` | —, —, `[]`, — | what tools run in: the project's interpreter and how to make it, PATH entries, a dotenv file |
| `pricing.fetch`, `pricing.table` | true, LiteLLM's `model_prices_and_context_window.json` on GitHub | whether nock fetches the public price table (at most daily) to cost sessions at API prices, and from where |
| `pricing."PREFIX"` | — | dollars per million tokens, `{input, output, cache_read, cache_write}`, for models whose name starts with PREFIX; overrides the table |

## Developing nock

See [ARCH.md](ARCH.md) for how the code is laid out.

```sh
uv sync
uv run pytest -n 4        # real repositories and processes, no mocks
uv run ruff check && uv run ruff format && uv run basedpyright
uv run nock init          # in another repository: vendor this checkout into it
```

Nothing in CI runs automatically. The gate (`.github/workflows/gate.yml`:
ruff check, ruff format --check, basedpyright, and the tests on Python 3.12
and 3.14) runs when you start it, `gh workflow run gate --ref BRANCH` (or
Actions → gate → Run workflow), and when a release calls it.

A release goes:

1. Bump `version` in `pyproject.toml` in a commit, with the gate green.
2. `python3 scripts/release.py VERSION`: on a clean tree whose
   `pyproject.toml` declares VERSION, with no tag `vVERSION` here or on
   `origin`, it asks y/N, then creates the annotated tag and pushes it.
3. The tag starts `.github/workflows/release.yaml`: the gate on the tagged
   commit, a check that the tag names the package's version, the sdist and
   the wheel built, published to PyPI through trusted publishing (environment
   `pypi`), and attached with their SHA-256 sums to a GitHub release
   (`gh run watch` to follow it).

`evals/` measures whether reflection pays (`evals/README.md`), and whether nock
helps through a month of real work (`evals/story/README.md`).

`web/` is nock.dev: the site, its docs pages built from this README, and the
publishing to GitHub Pages (`web/README.md`).

## Thanks

A special thank you to [David Eyk](https://worldsenoughstudios.com/), for graciously ceding his PyPI project under a similar name!
