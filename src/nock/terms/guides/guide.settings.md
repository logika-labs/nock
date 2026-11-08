---
term: guide.settings
aliases: [guide.config, guide.configuration]
description: Every key of .nock/config.toml, with its default
---

# Settings

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
| `agent.command`, `agent.model`, `agent.deadline` | `claude`, —, 1800 | the headless agent nock dispatches (consult, Ask, share); it may not bypass or set permissions (see [What nock's agents may do](#what-nocks-agents-may-do)) |
| `permissions.confirm` | `ask` | how Claude Code treats a `confirm=True` command: `ask` has the owner approve each call (even in bypass mode); `allow` lets the agent run it, which it does only when the owner's request calls for it (see [What nock's agents may do](#what-nocks-agents-may-do)); `nock init` rewrites the rules after a change |
| `consult.enabled`, `consult.deadline` | true, 600 | whether the consultant runs and the primer asks for it; seconds a consultation may take |
| `upgrade.check`, `upgrade.auto`, `upgrade.index` | true, true, PyPI's `nock` | whether a session start looks for a newer nock (at most daily); whether it then upgrades a core vendored from PyPI by itself when the merge is clean (off, or on a conflict, it only says the release is out); and where releases are looked up |
| `share` | — (unanswered) | the owner's answer to whether nock sends its makers the weekly usage report: unset sends nothing until they answer, false sends nothing, summaries included, only what you send yourself with `nock report` (see [What nock shares](#what-nock-shares)) |
| `endpoints.reflections`, `endpoints.usage`, `endpoints.reports` | `https://api.nock.dev/reflections`, `https://api.nock.dev/usage`, `https://api.nock.dev/reports` | where `nock share` sends a summary, where the usage reports go, and where `nock report` sends what you wrote |
| `environment.python`, `setup`, `path`, `dotenv` | —, —, `[]`, — | what tools run in: the project's interpreter and how to make it, PATH entries, a dotenv file |
| `pricing.fetch`, `pricing.table` | true, LiteLLM's `model_prices_and_context_window.json` on GitHub | whether nock fetches the public price table (at most daily) to cost sessions at API prices, and from where |
| `pricing."PREFIX"` | — | dollars per million tokens, `{input, output, cache_read, cache_write}`, for models whose name starts with PREFIX; overrides the table |
