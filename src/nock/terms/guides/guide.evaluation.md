---
term: guide.evaluation
aliases: [guide.evaluations, guide.eval]
description: Whether a change makes the agents better, answered with real runs over a provenance cache
---

# Evaluations

Does a change make the agents better? An evaluation answers it with real
runs, and keeps every intermediate result so the next question costs only
what changed. A scenario is a [Snakemake](https://snakemake.github.io/)
workflow in git beside the code; nock adds a profile, a budget, the reasons
a run reruns, pruning, and SQL over the results:

```
evals/detect/
  Snakefile                rules are steps, wildcards parameters
  profile/config.yaml      nock's Snakemake profile (`eval init` writes it)
  parameters/bug/none.json a parameter's values as files (bug=none is the clean twin)
  steps/plant.py           Step(snakemake).run(run): metrics.json, cost.json, error.json
  cache/3f2a…/             committed: each output, named by its provenance hash
  results/plant/bug=none/  this checkout's links into cache/ (not committed)
```

```python
BUGS = glob_wildcards("parameters/bug/{bug}.json").bug

rule all:
    input: expand("results/score/bug={bug}/rep={rep}", bug=BUGS, rep=[1, 2, 3])

checkpoint detect:
    input: "results/plant/bug={bug}"
    output: directory("results/detect/arm={arm}/bug={bug}/rep={rep}")
    params: keyed=lambda wildcards: dict(wildcards)
    cache: "omit-software"
    resources: agents=1, estimate_cents=40
    script: "steps/detect.py"
```

## Steps, forks and the cache

- **A step** is a rule whose output is a directory under
  `results/RULE/NAME=VALUE/…`, its script wrapped in
  `Step(snakemake).run(run)`: `run(step)` returns its numbers
  (`metrics.json`); `step.spend(usd, tokens)` and the seconds it took go
  to `cost.json`; a raise is `error.json`, a failed result, and a step one
  of whose inputs failed fails without running. `step.value("arm")`
  is a wildcard, `step.metrics("control")` an input's numbers, and
  `step.agent(brief, allowed=["Edit", "Bash(pytest:*)"])` dispatches a
  headless agent as nock dispatches its own, in `dontAsk` with that
  allowlist and nothing more, its cost counted. State the next step resumes
  from is `state.tar` (`step.pack(directory)`, `.git` included;
  `step.unpack()`), and a repository's change against the state before is
  `diff.patch`.
- **Forks, joins, `when`.** A fork is several jobs reading one output; a
  join is a rule with several inputs; `when` is an input function that
  returns `[]` or the branch to take, reading an earlier output's
  metrics.json through a `checkpoint`.
- **Memoisation is by content.** Every rule is `cache: "omit-software"`
  with its wildcards in its params, so Snakemake names its output by a hash
  of the rule's script, params and input files' content and the hashes of
  the jobs before it. `cache/` is committed: a fresh clone, whose files all
  have new mtimes, restores every output that matches and computes only the
  rest. Order the rules so the expensive-to-vary come first.
- **A cache outside git.** When outputs are too big to commit (whole
  repositories, databases), `[eval] cache = "~/.cache/my-evals"` in
  `.nock/config.toml` keeps each scenario's cache in that directory's
  `NAME/` instead; everything else works the same, on that machine.

## Running and reading

```sh
$ .nock/nock eval init detect                     # scaffold evals/detect/
$ .nock/nock eval run --dry                       # each job: from cache, or compute and why
$ .nock/nock eval run --budget 20                 # refused if the estimate passes $20
$ .nock/nock eval run results/score/bug=none/rep=1
$ .nock/nock eval run --limit agents=1 --retry      # one agent at a time; the failed again
$ .nock/nock eval import outputs.json              # outputs computed elsewhere, into the cache
$ .nock/nock eval query "SELECT rule, state, sum(cost_usd) FROM outputs GROUP BY ALL"
$ .nock/nock eval compare '{"by": "arm", "metric": "detected", "step": "detect", "unit": "bug"}'
```

`eval run` runs Snakemake with the profile (`--cores`, `keep-going`,
per-resource limits such as `agents=2`), on the default target or the
targets named. A dry run comes first: what reruns and why, in Snakemake's
words, and the estimate from each rule's mean past `cost.json` (or its
`resources: estimate_cents`); it refuses outputs that would share a cache
entry, Git LFS pointers in the cache, and, with `--budget`, an estimate past
it. **`eval query`** reads the result files with DuckDB (read-only, loaded
fresh each time, no index): `outputs`, `metrics`, `diffs` and a table per
rule with a column per wildcard and metric, so comparing arms is a
self-join on the wildcards they share. **`eval compare`** groups a rule's
current outputs by one parameter, holding the others fixed and pooling
`rep`: each mean with a bootstrap interval and the difference from the
baseline, paired when both sides have the same units. **`eval show`** gives
each rule's outputs current, stale (and why) and failed. **`eval prune`**
(`--dry` first) deletes the cache entries no current output is, and the
failed with what was computed from them, so a run computes them again; a
failed output is otherwise a result, restored rather than retried.
**`eval run --retry`** does that for the failed alone and runs, keeping
each failed attempt for its step to read (`step.previous`: an agent's work
worth keeping when only what followed it broke). `--limit NAME=N`
overrides a resource's limit, so a run takes at most N of what its rules
declare (`resources: stacks=1`). **`eval import`** puts outputs computed
elsewhere (another pipeline's results) into the cache under the entries
their jobs would have, each cloned from its source (copy-on-write where
the filesystem can, never moved) with its metrics, cost or error, so a run
restores them instead of computing them; jobs after a checkpoint are known
once it is restored, so such outputs are imported in rounds. The
`nock-eval` check fails when a rule is not cached by its wildcards or the
Snakefile does not read. Snakemake and DuckDB run through
[uv](https://docs.astral.sh/uv/); nock imports neither.

**More machines.** Another machine is another checkout: it runs part of the
targets, commits `cache/`, and pushes; entries merge as plain files, and the
next run anywhere restores them.

## In the studio

**The studio's Experiment tab** (`#experiment`) lists the scenarios, each with
the question it asks; the one chosen opens at its own address
(`#experiment/NAME`, so Back returns to the list) and draws it as an
experiment: its steps as a tree forking by parameter and by repeat, black boxes
on a grid, a line per value or per pooled set of values, with each step's time
and cost. Click a step for what it means, its parameters (the ones that vary
open to their values, a value narrows to its runs), its runs nested by what
tells them apart, and its time and cost; expand a run for when it ran and its
results, then follow it: its trajectory lights up, each step shows its results
and where it went, an iteration select narrows it, and the address keeps it.
Click a repeat's line to split it into its iterations. The table above counts
each measure per variant as total and per-iteration median: `26/36 (13/18
±2.8)`. Snakemake's description of the jobs is kept in `.nock/local/evals/`
and derived again only when the scenario changes, so the tab opens in a
second. An optional `evals/NAME/studio.json` words it:

```json
{
  "question": "Does the toolbox find the planted bug?",
  "parameters": {"bug": {"label": "Planted bug", "about": "…", "pooled": true,
                         "values": {"none": "no bug"}, "controls": ["none"]}},
  "rules": {"detect": {"title": "Detection", "means": "…",
                       "results": [{"name": "alarms", "kind": "list", "file": "alarms.txt"},
                                   {"name": "stories", "kind": "checks", "metrics": "stories."}],
                       "score": {"metric": "alarms", "better": "higher"}}},
  "decisions": [{"after": "detect", "label": "Detected?", "metric": "detected",
                 "measure": "Bugs detected",
                 "branches": [{"id": "yes", "equals": true, "verdict": "good"},
                              {"id": "no", "verdict": "bad"}]}]
}
```

A decision reads one metric of a step's outputs and takes the first branch it
fits; a branch with a verdict ends the trajectory, and each decision with a
good branch is a row of the table, with the cost per pooled value. Changing a
decision changes nothing on disk: it is read again on the next look. Without
`studio.json` a rule means the comment above it in the Snakefile. `nock docs eval` has the
rest, with the practice that keeps an evaluation honest: fix the inputs,
keep the answers from what is scored, measure the outcome, run enough
repetitions, write the comparison down first.
