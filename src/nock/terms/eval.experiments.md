---
term: eval.experiments
aliases: [experiment, experiments, measures, pooled]
description: The studio's Experiment tab: a scenario's forks, decisions, runs and measures, from studio.json
---

The studio's Experiment tab (`#experiment`) lists the scenarios; `#experiment/NAME` draws one as a tree of steps forking by parameter and repeat. In `evals/NAME/studio.json`: `question`; a parameter's `about`, `pooled` (added up, like a bug), `repeat`, `controls` (`["none"]`); a rule's `results` (`{name, kind, file}` or `{metrics: "prefix."}` as checks) and `score`; `decisions` (`{after, label, metric, branches: [{id, equals, verdict}]}`), each with a good branch a measure.
