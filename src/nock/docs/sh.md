---
term: sh
aliases: [shell, output-object, supervised]
description: sh runs a command supervised, logged and condensed
---

`sh(command)` runs it supervised (a deadline, a silence timeout), logged and condensed, and ends the call on failure. `sh(command, check=False)` returns an Output: `.code`, `.ok`, `.lines`, `.text`, `.raw`, `.log`. It takes `deadline=`, `silence=` (seconds; 0 is none), `directory=`, `input=`. Returning the Output passes the condensed output and exit code through. The variables git sets (`GIT_DIR`, …) never reach the command.
