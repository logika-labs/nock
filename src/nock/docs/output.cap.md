---
term: output.cap
aliases: [capped, full, json, long-output]
description: Long output is capped and the rest saved; --json and --full
---

What a call prints is capped at about 8,000 characters or 60 table rows; the full text is saved under `.nock/local/outputs/` and its path printed. Every command takes `--json` (JSON of what it returned) and `--full` (everything). Stdout carries only the result; notes and errors go to stderr.
