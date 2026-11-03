---
term: eval.steps
aliases: [step, steps, step-helper]
description: steps/RULE.py: Step(snakemake).run(run) writes metrics.json, cost.json, error.json
---

`Step(snakemake).run(run)`: `run(step)` returns its numbers (metrics.json); `step.value("arm")` is a wildcard, `step.metrics("control")` an input's numbers, `step.spend(usd, tokens)` goes to cost.json, `step.agent(brief, allowed=["Edit"])` dispatches in `dontAsk`. A raise is error.json, a failed result; a step whose input failed fails unrun. `step.previous` is a retried step's failed attempt. `pack`/`unpack` carry state.
