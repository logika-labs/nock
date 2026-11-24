---
term: checks
aliases: [check, problem, gate]
description: @nock.check returns its problems; nock check runs those the changes affect, --all every one
---

A check returns its problems, strings or `nock.Problem(message, path, line)`, and nothing when all is well; its docstring states the rule. `.nock/nock check` runs the checks the branch's changes can affect (`--all` every one, checks.changed) and prints nothing when all pass: exit 1 the code is wrong, 42 the machine is. Asking for `changed` holds only new code to the rule, so it can land while old code still breaks it. A check beats a hook beats prose.
