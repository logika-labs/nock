---
term: environment
aliases: [env, interpreter, python, dotenv, venv]
description: What tools run in: the project's interpreter, PATH and dotenv
---

`[environment]` in `.nock/config.toml`: `python = ".venv/bin/python"` (nock re-runs itself on it, so tools import the project's packages; relative is each worktree's own), `setup = "uv sync"` (run when it is missing), `path = ["~/.cargo/bin"]` (first on PATH), `dotenv = ".env"` (the worktree's, else the main checkout's; variables already set win). Hooks get it too, but never wait on `setup`.
