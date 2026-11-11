# nock

A self-improving toolbox for coding agents.

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
  suits you; a topic whose work is built and waits only on your verdicts
  is in review;
- **every week or so a reflection round** reads the record and improves the
  toolbox: tools for the work that keeps costing turns, repairs for the ones
  that misbehave, the unused ones retired;
- in a [Logika](https://logika.host) project, **the logika round** writes the
  rules that wake your agent when production breaks them.

nock is standard-library Python 3.12 with no dependencies, vendored into the
project, so it is the project's own code. It shares nothing without your yes.

## Docs

The documentation is at [nock.dev/docs](https://nock.dev/docs/): nock from
first principles, in a few long essays, best read in order. The same text is in
nock itself: `.nock/nock docs guide` lists the essays, and `.nock/nock docs` the
terms, the short articles agents read. Both are `src/nock/terms/`.

1. [Why nock](https://nock.dev/docs/why/)
2. [Agents that build their own tools](https://nock.dev/docs/reflection/)
3. [A CLI agents can use](https://nock.dev/docs/cli/)
4. [Review on your time](https://nock.dev/docs/review/)
5. [nock in Logika](https://nock.dev/docs/logika/)
6. [Setting up](https://nock.dev/docs/setup/)

And the [reference](https://nock.dev/docs/terms/): every command, exit code and
term.

## Developing nock

```sh
uv sync
uv run pytest -n 4        # real repositories and processes, no mocks
uv run ruff check && uv run ruff format && uv run basedpyright
```

[ARCH.md](ARCH.md) has how the code is laid out, and `.nock/nock docs
guide.cli` (or [the essay](https://nock.dev/docs/cli/#nock-is-its-own-first-user))
the gate and how a release goes. `web/` is nock.dev, its docs built from
`src/nock/terms/` (`web/README.md`).

## Thanks

A special thank you to [David Eyk](https://worldsenoughstudios.com/), for graciously ceding his PyPI project under a similar name!
