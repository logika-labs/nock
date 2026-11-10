---
term: guide.evaluation
aliases: [guide.evaluations, guide.eval]
description: Whether a change makes the agents better, answered with real runs over a memoized graph of stages
---

# Evaluations

Evaluations are hard and confusing. But when programming with AI, they take
center stage: where before, we would need to deal with programmers with
different preferences, agendas and egos, now we can dispatch several agents to
explore different options, and the hard part becomes tracing and evaluating the
agents' work to choose the best way forward.

It's tricky because there are a lot of parameters to tweak, and agents' work
takes time, costs money and isn't deterministic, so I developed the kind of
tool I needed myself, to evaluate how well Logika instruments logs, catches
bugs and so on.

Basically, an experiment is broken down into different configurations, with
each configuration having several stages. Each stage can branch on parameters
(e.g. different models, different skills, etc.), and once a stage is evaluated
it's cached for reuse, and the results it produces can be scored to see if they
meet some criteria, or fed as parameters to further stages, i.e. branching
if-this-else-that.

Viewing it as a memoized graph is readable, saves time and cost, and lets me as
a user focus on specific runs to see what exactly happened there, or lets the
agent query trends over the data and discern patterns from what happened,
without having to invent evaluation methodologies or re-interpret results from
scratch.

## An experiment, by example

Logika's own evaluation asks: *does a coding agent find and fix a silent
production bug better, faster or cheaper with Logika than with plain
OpenTelemetry?* Its stages, in order:

1. **The app**: an open-source application at a pinned release, set up to run.
2. **Bank the bug**: each planted bug's claims checked before any agent sees
   it: its test fails with the bug and passes without it.
3. **Instrument**: an agent instruments the whole app, with Logika's skill or
   with plain OpenTelemetry. That's the `arm` parameter, and a second one,
   `degree`, says how thoroughly: light, or a subagent per directory.
4. **Write the rules**: on the Logika arm, a logika round writes the rules,
   then checks they stay quiet on clean traffic.
5. **Detect** and **fix**: the bug is planted and the traffic runs, and an
   agent is set to find the bug and fix it.
6. **Score** it.

The `bug` parameter forks the stages after the instrumenting once per bug, and
one of its values is `none`: the clean twin, the same traffic with no bug,
where every alarm is a false one. And `rep` repeats the agent's fix, since one
run of an agent proves little.

Instrumenting a whole app is the expensive stage, and it doesn't depend on the
bug. So it runs once per arm and degree, and every bug forks from its cached
result. Change only the scoring, and nothing but the scoring runs again. Change
the instrumenting skill, and everything from that stage on runs again, and
nothing before it.

## Scenarios are Snakemake workflows

nock doesn't invent a workflow language. A scenario is a
[Snakemake](https://snakemake.github.io/) workflow in git beside the code: rules
are stages, wildcards are parameters. nock adds a profile, a budget, the
reasons a run reruns, pruning, SQL over the results, and the studio's drawing
of it all.

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

**A step** is a rule whose output is a directory, its script wrapped in
`Step(snakemake).run(run)`. `run(step)` returns its numbers, which land in
`metrics.json`; `step.spend(usd, tokens)` and the seconds it took go to
`cost.json`; a raise is `error.json`, a failed result, and a step whose input
failed fails without running. `step.value("arm")` reads a wildcard,
`step.metrics("control")` an input's numbers, and `step.agent(brief,
allowed=["Edit", "Bash(pytest:*)"])` dispatches a headless agent the way nock
dispatches its own, with that allowlist and nothing more, its cost counted. The
state the next step resumes from is packed with `step.pack(directory)` and
unpacked with `step.unpack()`.

**Forks, joins, and if-this-else-that.** A fork is several jobs reading one
output; a join is a rule with several inputs. A branch is an input function
that reads an earlier output's `metrics.json` through a `checkpoint` and returns
the branch to take, or nothing.

**Memoization is by content.** Every rule is cached by its wildcards, so
Snakemake names its output by a hash of the rule's script, its params, its
input files' content and the hashes of the jobs before it. `cache/` is
committed, so a fresh clone restores every output that matches and computes
only the rest, and another machine is just another checkout: it runs part of
the targets, commits the cache and pushes. When outputs are too big for git,
`[eval] cache = "~/.cache/my-evals"` keeps the cache outside it.

## Running and reading

```sh
$ .nock/nock eval init detect                     # scaffold evals/detect/
$ .nock/nock eval run --dry                       # each job: from cache, or compute and why
$ .nock/nock eval run --budget 20                 # refused if the estimate passes $20
$ .nock/nock eval run --limit agents=1 --retry    # one agent at a time; the failed again
$ .nock/nock eval query "SELECT rule, state, sum(cost_usd) FROM outputs GROUP BY ALL"
$ .nock/nock eval compare '{"by": "arm", "metric": "detected", "step": "detect", "unit": "bug"}'
```

A run starts with a dry run: what reruns and why, in Snakemake's words, and an
estimate from each rule's past cost, so `--budget` can refuse a run before it
spends anything. A failed output is a result, restored rather than retried,
until `--retry` runs the failed alone again, keeping each failed attempt for its
step to read: an agent's work is worth keeping when only what followed it
broke. `eval prune` deletes what no current output uses, and `eval import` puts
outputs computed elsewhere into the cache, so a run restores them.

**`eval query`** reads the results with DuckDB, read-only: `outputs`,
`metrics`, `diffs`, and a table per rule with a column per wildcard and metric,
so comparing arms is a self-join on the wildcards they share. That's what lets
an agent look for patterns in the data instead of re-reading runs.
**`eval compare`** groups a rule's outputs by one parameter, holding the others
fixed and pooling repetitions: each mean with a bootstrap interval and the
difference from the baseline, paired when both sides have the same units.

## In the studio

The studio's **Experiment** tab lists the scenarios, each with the question it
asks, and draws the one you open as an experiment: its stages as a tree forking
by parameter and by repetition, each with its time and cost. Click a stage for
what it means, its parameters and its runs; expand a run for its results, then
follow it: its whole trajectory lights up, each stage showing its results and
where it went next. The table above counts each measure per variant, such as
bugs detected, as a total and a median per repetition.

An optional `evals/NAME/studio.json` words it: the question, what each
parameter and stage means, which values are controls, how each stage's results
show, and the decisions that read a metric and branch on it, a branch with a
verdict ending a trajectory as good or bad. Changing a decision changes nothing
on disk; it's read again the next time you look.

## Keeping it honest

An evaluation can fool you as easily as no evaluation. `nock docs eval` has
the practice, an article each:

- **fix the inputs**: recorded traffic, seeds, the model as a parameter, and
  repetitions explicit, so each is its own cached output;
- **keep the answers out of reach**: a step never sees what it's scored on, the
  planted bug or the answer key;
- **measure the outcome you want**: a bug fixed and staying fixed, not a test
  touched; false alarms counted on the clean twin;
- **run enough**: agents vary a lot from run to run, and a difference whose
  interval spans zero is no difference yet;
- **write the comparison down first**, in the Snakefile or as a decision item:
  looking first and choosing the cut after finds a winner in noise;
- **order the stages** so the expensive and rarely changed come first, and the
  cheap or often varied last.
