---
term: eval.scenario
aliases: [scenario, scenario-json]
description: evals/NAME/scenario.json: the steps in order and the parameters they read
---

`scenario.json`: `{"steps": [{"name": "plant", "reads": ["bug"], "code": ["steps/lib/*.py"], "estimate": {"seconds": 60, "cost_usd": 0.2}, "deadline": 1800}], "parameters": {"bug": {"files": "parameters/bug/*"}, "arm": {"values": ["control", "toolbox"]}, "rep": {"values": [1, 2, 3]}}}`. A glob is the scenario directory's, or with a leading `/` the working tree's. Only `name` is required of a step; `code` adds files to its code digest.
