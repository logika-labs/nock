---
term: eval.steps
aliases: [step, steps, step-helper]
description: steps/RULE.py: Step(snakemake).run(run) writes metrics.json, cost.json, error.json
---

`Step(snakemake).run(run)`: `run(step)` returns its numbers (metrics.json); `step.value("arm")` is a wildcard, `step.input("bug")` an input, `step.metrics("control")` an input's numbers, `step.spend(usd)` goes to cost.json with the seconds taken, `step.agent(brief, allowed=["Edit"])` dispatches in `dontAsk` with that allowlist. A raise is error.json: a failed result, cached. `step.unpack()`/`pack(dir)` carry state.
