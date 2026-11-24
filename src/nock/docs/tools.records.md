---
term: tools.records
aliases: [record, records, json-argument, typeddict, dataclass]
description: A TypedDict or dataclass parameter is one JSON argument
---

A parameter typed as a TypedDict or a dataclass is one JSON argument: inline, a path to a JSON file, or stdin (`-`, or left out when it has no default). It is checked against the type, and a misspelled key gets a "did you mean". Give it a default to make it optional. A record is always one JSON argument, never JSON in a flag.
