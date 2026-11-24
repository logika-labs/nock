---
term: audit
aliases: []
description: "The audit round: performance, security and tests, a subround each in its own agent"
---

# The audit round

The audit round judges the project and changes nothing: `audit.performance`, `audit.security` and `audit.tests`, each led by its own agent.

1. Run `.nock/nock reflect audit`: it prints the plan, one subagent per subround on here, each with its prompt.
2. Dispatch them all in one message, in the background, as general-purpose subagents, each with its prompt: each starts its subround and leads it.
3. Relay each one's report to the owner as it ends: what it found and changed, what needs the owner's word, and where its report is.
