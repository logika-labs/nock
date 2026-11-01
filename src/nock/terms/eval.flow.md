---
term: eval.flow
aliases: [fork, join, when, checkpoint, checkpoints]
description: Forks, joins, when and values from earlier outputs, in Snakemake's terms
---

A fork is several jobs reading one output (a wildcard first used downstream); a join is a rule with several inputs (`control=…, toolbox=…`). `when` is an input function returning `[]` to skip, or the path of the branch to take. A decision on an earlier output's value needs that rule to be a `checkpoint`: the function calls `checkpoints.RULE.get(**wildcards)` and reads its metrics.json. A dry run cannot see past a checkpoint that has not run.
