---
term: eval.scenario
aliases: [scenario, snakefile, profile, layout]
description: evals/NAME/: Snakefile, profile/, steps/, parameters/, cache/ committed, results/ not
---

A rule's output is `directory("results/RULE/NAME={NAME}/...")`, one `NAME=VALUE` per wildcard; it has `cache: "omit-software"` and `params: keyed=lambda wildcards: dict(wildcards)` (or each value would share one cache entry), and `script: "steps/RULE.py"`. Parameter files are inputs. The first rule names everything (`expand`). `cache/` is committed; `results/` is each checkout's links into it. The `nock-eval` check holds rules to this.
