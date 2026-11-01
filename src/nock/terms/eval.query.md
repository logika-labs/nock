---
term: eval.query
aliases: [duckdb, eval-query, eval-sql]
description: nock eval query: read-only DuckDB over the result files: outputs, metrics, diffs, a table per rule
---

Tables: `outputs` (rule, path, parameters map, state, why, cost_usd, seconds, error), `metrics` (rule, path, parameters, state, metric, value), `diffs` (bytes, files, added, removed), and per rule a column per wildcard and metric. `SELECT t.bug, t.detected::INT - c.detected::INT FROM detect t JOIN detect c USING (bug, rep) WHERE t.arm = 'toolbox' AND c.arm = 'control'`; `SELECT rule, sum(cost_usd) FROM outputs GROUP BY 1`.
