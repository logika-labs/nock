---
term: eval.artefacts
aliases: [artefact, artefacts, state, tarball, diff, lfs]
description: state.tar carries a step's state to the next; diff.patch is its change; big ones in LFS
---

Whatever a step leaves in its output directory is its snapshot. State the next step resumes from is `state.tar` (`step.pack(directory)`, a repository's `.git` included; `step.unpack()` extracts the input's). When the state is a git repository, `pack` writes `diff.patch`, its change against the state before, and commits it. Big cache entries go to Git LFS (the commented line in `.gitattributes`); a run refuses LFS pointers: `git lfs pull`.
