---
term: guide.tool
aliases: [guide.tools]
description: A tool is a function: the signature, fixtures, output, failures, the environment and streaming
---

# A tool

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

## In short

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
`nock check` runs them, so a tool that breaks fails the gate. A
`confirm=True` tool's examples are never run, since that would set off what
only the owner may without asking: the check only parses each against the
tool's arguments, so one that calls it wrong still fails the gate.

## The project's environment

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
on a checkout of nock without vendoring it again: its `nock init` re-wires the
project with the checkout's primer, hooks and skills and keeps the vendored
core, which `nock upgrade` updates.

## Long-running and interactive commands

`sh(command, stream=True)` says the command line on stderr and prints the
output as it arrives instead of
condensing it afterwards, and the command reads the caller's stdin and has
the caller's terminal: `ssh` and `sudo` can prompt on it, and Ctrl-C reaches
it. A failing streamed command points at its log rather than printing its
output twice. A bound of 0 is none, so a dev server is
`sh("uvicorn app:app", check=False, stream=True, deadline=0, silence=0)`;
interrupted, it is asked to stop (SIGINT) and given five seconds before it
is killed.
