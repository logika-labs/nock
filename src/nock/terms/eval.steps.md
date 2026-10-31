---
term: eval.steps
aliases: [step, steps]
description: steps/STEP.py: run(step) turns the snapshot before into the next
---

`steps/STEP.py` defines `run(step)` and returns its results, a dict. `step.directory` is the state (the cwd), a copy of the snapshot before; what it holds after is the artefacts. `step.value("arm")`, `step.file("bug")`, `step.files(...)`, `step.results("build")`, `step.spend(usd)`, `step.agent(brief, allowed=["Edit"])` (dispatched in `dontAsk` with that allowlist, its cost spent). A raise is a failed result, with its log. Each runs in its own process, on `[environment]`'s interpreter.
