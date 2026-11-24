# nock

A toolbox coding agents build for themselves: an agent-friendly CLI framework
(`commands.py`, `fixtures.py`, `render.py`, woven together in `cli.py`),
telemetry of every call and session (`store.py`, `telemetry.py`,
`sessions.py`), the memory of what nock learned (`.nock/shared/memory.md`,
`shared.py`), and reflection and audit rounds (`rounds.py`, `rounds/`) that
turn it all into better tools, the memory and an account of how nock is
doing (`reflect.py`, `share.py`; in a Logika project, the logika round in
`logika.py`). A round (audit, fuzz, logika, nock) is a group of subrounds
(`audit.security`); `nock reflect ROUND` prints the plan, one agent per
subround, and each subround's lead reports its findings to the session that
ran it, in its final message, with its report in `.nock/local/reflections/`. It is
vendored into the projects that use it (`nock init` copies `src/nock` into
their `.nock/core/`), so everything here must run on Python 3.12 with the
standard library and nothing else: schemas are the JSON Schema subset in
`schema.py`.

- `uv run pytest -n 4`, `uv run ruff check`, `uv run ruff format`,
  `uv run basedpyright` — all green before a commit.
- Nothing in CI runs automatically: the gate (`.github/workflows/gate.yml`)
  runs by hand, `gh workflow run gate --ref BRANCH`, or when a release calls
  it. A release is a tag `vVERSION` that `python3 scripts/release.py [VERSION]`
  (the next patch by default) bumps, commits, creates and pushes after asking
  the owner; `release.yaml` then gates the
  tagged commit and publishes to PyPI (README, "Developing nock"). Never push,
  tag or publish without the owner's word.
- Tests use real git repositories and real processes; the dispatched agent
  (the sharer) is `tests/fake_agent.py`, configured as `agent.command`. No
  mocks.
- `server/` is api.nock.dev, a separate distribution (Python 3.14, FastAPI,
  Postgres) that is never vendored or published, so it may have dependencies:
  `cd server && uv run pytest` (Docker, for Postgres), `uv run ruff check`,
  `uv run ruff format --check`, `uv run basedpyright` — green too before a
  commit that touches it. Its README has the deploy and the provisioning.
- `src/nock/docs/` is nock's documentation, one source for agents and people: the
  terms are short articles agents read (`nock docs`, which the briefs point
  at; `docs/briefs/` the long texts every installed skill and subagent
  points at), and `docs/guides/` the guides, a page each, that nock.dev's
  docs are built from (`web/`, the site, outside the vendored core:
  `web/README.md`). Keep them true when behavior changes. The README is an
  overview that links to the docs. Every skill nock installs is one line
  pointing at a brief term (a subround's lead brief is the term of its name,
  `docs/briefs/audit.security.md`). The docs are also hosted: `nock docs`
  shows the newer signed bundle api.nock.dev serves (`hosted.py`,
  `signing.py`; `NOCK_DOCS=bundled` for the core's own), which
  `python3 scripts/publish_docs.py` publishes only on the owner's word, like a
  release.

## How the code is shaped

- `Project` (`project.py`) is the hub: telemetry on the main checkout
  (`project.local`), nock code — tools, settings, briefs — in the working tree
  (`project.code_path`).
- nock's own commands are tools (`builtin.py`), registered through the same
  decorators a project uses (`tools.py`); its fixtures likewise
  (`fixtures.py`).
- Exit codes are the `ExitCode` taxonomy in `errors.py`; raise the specific
  error class.
- Every byte a command prints is read by an agent: return what the next
  decision needs.

## Standards

- Classes own state and behavior; no `@staticmethod`; statuses are `StrEnum`s.
- Plain, full words; no abbreviations; long-form CLI flags only; a record is
  one JSON argument (or a file, or stdin), never JSON in a flag.
- No inline imports except a genuine cycle, marked as such.
- No abstraction a named requirement does not earn; the smallest diff that
  does the job.
- Module docstrings say what the module is in a sentence or two.
