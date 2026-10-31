---
term: eval
aliases: [evals, evaluation, evaluations]
description: nock eval: scenarios of steps, snapshots reused by content, leaves compared
---

An evaluation is a scenario in `evals/NAME/`: an ordered chain of steps, each turning the snapshot before it into the next, reading named parameters. `.nock/nock eval init NAME` starts one; `eval run` computes what an assignment needs and reuses every snapshot that still matches; `eval show` and the studio's Evals tab read the files; `eval compare` reads across leaves. Comparisons are never steps. The `nock-eval` check holds it all to its files.
