---
term: output
aliases: [return, render, printing]
description: Return data and nock prints it, as compactly as its shape allows
---

None prints nothing (the exit code says it); `False` nothing, and exits 1; a string as is; a dict `key: value` lines; a list one item per line; a list of dicts CSV under a header (a column alike in every row printed once, above); nested data indented `key: value`; an Output from `sh` the command's condensed output and its exit code. Every byte is read by an agent: return what the next decision needs, not everything you have.
