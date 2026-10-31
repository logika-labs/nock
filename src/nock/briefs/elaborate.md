The owner asked for more on decision {{ decision["number"] }} before reviewing
it; its `note`, if any, says what they want. Look into it (the code, the
history, the other decisions: `.nock/nock decisions list`,
`.nock/nock decisions show N`; what each field is for:
`.nock/nock docs decisions.record`), change nothing, and edit the decision once:

    .nock/nock decisions edit '{"number": {{ decision["number"] }}, "summary": …, "evidence": […], "alternatives": [{"option": …, "why_not": …}]}'

Answer the note first, for someone who knows what the system does but not
how it is built. If the decision turns out wrong, say so: the owner decides.
End with a line on what you added.

```json
{{ rendered }}
```
