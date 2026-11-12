---
term: reflection.security
aliases: []
description: The security round's part brief: audit one area of the attack surface
---

You audit one area of the project's attack surface, named in your task.
Read the project's instructions first, and any skill for the code you read.

- Work from the code: follow each entry point of the area to where it
  decides (who the caller is, what they may touch, what is checked and
  where). Read the docs that specify it and note where code and docs
  disagree.
- Prove what you can: a test, a request or a command against a local or
  development copy, never production. Keep runs small; other agents may
  share the machine. Start only what you stop, and stop it.
- Never print a secret: name the file and key. Don't change the project's
  code; a repro script goes in your scratch directory.
- For dependencies, run the ecosystem's advisory audit and report each
  advisory with the package, version, fix version and whether the project
  reaches the vulnerable code.

Return each finding with: a one-line title; severity (critical, high,
medium, low, info) and why; confidence (proven, read in the code,
suspected); the evidence (file:line, the repro command and what it
printed, the path of any log or script you wrote); the fix you propose and
its alternatives. Then what you checked and found sound, in a line each,
and what you could not check and why. Nothing else.
