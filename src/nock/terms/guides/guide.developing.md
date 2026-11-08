---
term: guide.developing
aliases: [guide.development, guide.release]
description: Working on nock itself: the tests, the gate and how a release goes
---

# Developing nock

See [ARCH.md](ARCH.md) for how the code is laid out.

```sh
uv sync
uv run pytest -n 4        # real repositories and processes, no mocks
uv run ruff check && uv run ruff format && uv run basedpyright
uv run nock init          # in another repository: vendor this checkout into it (or re-wire, keeping its core)
```

Nothing in CI runs automatically. The gate (`.github/workflows/gate.yml`:
ruff check, ruff format --check, basedpyright, and the tests on Python 3.12
and 3.14) runs when you start it, `gh workflow run gate --ref BRANCH` (or
Actions → gate → Run workflow), and when a release calls it.

A release is one command, with the gate green:

1. `python3 scripts/release.py [VERSION]` (the next patch when left out):
   on a clean tree, on a branch, with no tag `vVERSION` here or on
   `origin`, it asks y/N, and only then bumps the version in
   `pyproject.toml`, `src/nock/releases.py` and `uv.lock` in a commit,
   creates the annotated tag and pushes the branch and the tag.
2. The tag starts `.github/workflows/release.yaml`: the gate on the tagged
   commit, a check that the tag names the package's version, the sdist and
   the wheel built, published to PyPI through trusted publishing (environment
   `pypi`), and attached with their SHA-256 sums to a GitHub release
   (`gh run watch` to follow it).

`evals/` measures whether reflection pays (`evals/README.md`), and whether nock
helps through a month of real work (`evals/story/README.md`).

`web/` is nock.dev: the site, its docs pages built from these guides and the terms, and the
publishing to GitHub Pages (`web/README.md`).
