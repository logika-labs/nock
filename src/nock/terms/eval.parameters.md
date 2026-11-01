---
term: eval.parameters
aliases: [parameter, parameters, wildcard, wildcards, assignment]
description: Parameters are wildcards: in the output path, their values listed or globbed
---

A parameter is a wildcard, `NAME=VALUE` in an output's path: `results/detect/arm={arm}/bug={bug}/rep={rep}`. Its values are a list (`ARMS = ["control", "toolbox"]`), or files (`BUGS = glob_wildcards("parameters/bug/{bug}.json").bug`, the file an input), expanded in the first rule. Constrain each to one path part (`wildcard_constraints: bug="[^/]+"`). Narrow a run by naming targets: `nock eval run results/score/bug=none/rep=1`.
