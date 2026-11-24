---
term: fuzz
aliases: []
description: "The fuzz round: the API and the web UI driven with odd input, a subround each in its own agent"
---

# The fuzz round

The fuzz round drives what the project exposes with odd input and reports each break: `fuzz.api` and `fuzz.ui`, each led by its own agent.

1. Run `.nock/nock reflect fuzz`: it prints the plan, one subagent per subround on here, each with its prompt.
2. Dispatch them all in one message, in the background, as general-purpose subagents, each with its prompt: each starts its subround and leads it.
3. Relay each one's report to the owner as it ends: what it found and changed, what needs the owner's word, and where its report is.
