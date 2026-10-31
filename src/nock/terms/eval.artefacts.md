---
term: eval.artefacts
aliases: [artefact, artefacts, lfs]
description: A snapshot's files: committed, in Git LFS, or ignored by the scenario's .gitattributes/.gitignore
---

Artefacts sit in `snapshots/HASH/artefacts/`, listed in the manifest with digest and bytes. Small ones are committed; big ones go to Git LFS or are ignored, by the commented lines `eval init` writes in the scenario's `.gitattributes` and `.gitignore`. A clone lacking some is told (`eval show`, `--dry` says which steps are blocked), never broken; `nock-eval` fails when a committed snapshot's artefact is neither there nor ignored.
