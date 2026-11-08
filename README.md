# nock

A toolbox your coding agents build for themselves.

Agents repeat themselves: the same five shell commands to find out why a test
fails, the same throwaway script, the mistake you have already corrected
twice. The usual fix is prose, and prose goes stale without anyone noticing.
nock's fix is code: a command that no longer fits the project breaks, and the
failure is recorded.

> **A check beats a hook beats prose.**

```sh
uvx nock init
```

Run it inside the repository you want it in, and commit the result. From then
on:

- **every call and session is recorded** on your machine, in a SQLite file
  that is never committed;
- **agents put their work before you** in topics: the decisions they made,
  the files they changed, what they made to show it. You accept, reject or
  chat about each in the studio's Work tab (`.nock/nock studio`), when it
  suits you;
- **every week or so a reflection round** reads the record and improves the
  toolbox: tools for the work that keeps costing turns, repairs for the ones
  that misbehave, the unused ones retired;
- **evaluations** answer whether a change makes your agents better, with real
  runs;
- in a [Logika](https://logika.host) project, **the logika round** writes the
  rules that wake your agent when production breaks them.

nock is standard-library Python 3.12 with no dependencies, vendored into the
project, so it is the project's own code. It shares nothing without your yes.

## Docs

The documentation is at [nock.dev/docs](https://nock.dev/docs/), and the same
text is in nock itself: `.nock/nock docs` lists its terms, the short articles
agents read, and `.nock/nock docs guide` the guides, the pages for people.
Both are `src/nock/terms/`.

- **Start:** [What changes for you](https://nock.dev/docs/why/),
  [Install](https://nock.dev/docs/install/),
  [The first session](https://nock.dev/docs/session/).
- **Every day:** [Reviewing in Work](https://nock.dev/docs/work/),
  [Chatting](https://nock.dev/docs/chat/),
  [Tidy up](https://nock.dev/docs/tidy/),
  [Topics and items](https://nock.dev/docs/topics/),
  [The map and consulting](https://nock.dev/docs/consult/),
  [Reflection rounds](https://nock.dev/docs/reflection/),
  [The logika round](https://nock.dev/docs/logika/).
- **Extending:** [A tool](https://nock.dev/docs/tool/),
  [Checks, hooks and generators](https://nock.dev/docs/check/),
  [Evaluations](https://nock.dev/docs/evaluation/).
- **Reference:** [Commands and exit codes](https://nock.dev/docs/commands/),
  [Settings](https://nock.dev/docs/settings/),
  [The terms](https://nock.dev/docs/terms/),
  [Telemetry](https://nock.dev/docs/telemetry/),
  [What nock's agents may do](https://nock.dev/docs/permissions/),
  [What nock shares](https://nock.dev/docs/sharing/),
  [Developing nock](https://nock.dev/docs/developing/).

## Developing nock

```sh
uv sync
uv run pytest -n 4        # real repositories and processes, no mocks
uv run ruff check && uv run ruff format && uv run basedpyright
```

[ARCH.md](ARCH.md) has how the code is laid out, and `.nock/nock docs
guide.developing` (or [the page](https://nock.dev/docs/developing/)) the gate
and how a release goes. `web/` is nock.dev, its docs built from
`src/nock/terms/` (`web/README.md`).

## Thanks

A special thank you to [David Eyk](https://worldsenoughstudios.com/), for graciously ceding his PyPI project under a similar name!
