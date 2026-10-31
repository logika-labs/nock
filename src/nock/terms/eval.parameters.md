---
term: eval.parameters
aliases: [parameter, parameters, assignment]
description: A named value a step reads: files beside the scenario, or literals; an assignment picks values
---

A parameter's values are files (`"files": "parameters/bug/*"`, one value per file or directory, named by its stem), literals (`"values": [1, 2]`), or names for globs (`"values": {"current": ["/src/**"]}`, so code is a parameter). An assignment, `{"bug": "*", "arm": ["control"], "rep": [1, 2], "budget_usd": 5}`, gives each a value, a list or `*`; one with a single value needs no mention, and `"scenario"` names the scenario.
