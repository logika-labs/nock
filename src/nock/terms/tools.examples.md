---
term: tools.examples
aliases: [example, examples]
description: examples= show in --help, and nock check runs each one
---

`@nock.command(examples=["--path tests/unit"])`: each string is a call, shown in `--help`; `.nock/nock check` (its `nock-tools` check) runs every one, so a tool that breaks fails the gate. Give every new command examples.
