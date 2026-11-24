---
term: tools.signature
aliases: [arguments, options, flags, option]
description: The signature is the command line: arguments, options, flags, choices
---

A positional parameter is an argument; a keyword-only one (after `*`) is an `--option`. A `bool` is a flag, a `list[str]` repeats, an `Enum` or `Literal` gives the choices. `Annotated[str, nock.Option("--from", help="…")]` gives an option its help or its own flag; declared so, it is an option even when it shares a fixture's name, like `--project`. `rest="words"` gives `words: list[str]` every word after `--`, verbatim. Long-form flags only.
