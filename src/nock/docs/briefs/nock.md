---
term: nock
aliases: []
description: "The nock round: fit and toolbox, how nock serves the project and its toolbox improved"
---

# The nock round

The nock round improves how nock serves this project: `nock.fit` judges it, sets the other rounds up and keeps the memory; `nock.toolbox` improves the toolbox from its telemetry. Each is led by its own agent.

1. Run `.nock/nock reflect nock`: it prints the plan, one subagent per subround on here, each with its prompt.
2. Dispatch them all in one message, in the background, as general-purpose subagents, each with its prompt: each starts its subround and leads it.
3. Relay each one's report to the owner as it ends: what it found and changed, what needs the owner's word, and where its report is.
