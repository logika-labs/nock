---
term: sh.stream
aliases: [stream, server, interactive]
description: stream=True: print as it goes, with the caller's terminal
---

`sh(command, stream=True)` says the command line on stderr and prints the output as it arrives; the command reads the caller's stdin and has their terminal, so `ssh` and `sudo` can prompt and Ctrl-C reaches it. For servers, and what someone watches or answers: `sh("uvicorn app:app", check=False, stream=True, deadline=0, silence=0)`. Interrupted, it gets SIGINT and five seconds before it is killed. A failure points at the log.
