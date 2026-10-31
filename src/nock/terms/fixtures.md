---
term: fixtures
aliases: [fixture, root, git, tmp, log, changed, project]
description: Ask for what a tool needs by naming a parameter after it
---

As in pytest, a tool, check or hook asks for what it needs by name: `root` (the working tree, a Path); `git` (`git("log", "-1")` returns the output); `sh` (`.nock/nock docs sh`); `changed` (files changed against the main branch); `tmp` (a directory removed after the call); `log` (notes to the call's log file, never to the caller); `config`; `project`. Your own: `@nock.fixture def db(root): …`, asking for others by name; `yield` to clean up after the call.
