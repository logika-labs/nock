The owner asked for a new version of `{{ key }}`, an item under review (now at version
{{ version["version"] }}, "{{ version["title"] }}").
!if version["feedback"]:
    Their note on it, which the new version must answer: {{ version["feedback"] }}
!else:
    They left no note: make it again as the recipe says.

How it is made, in the words of whoever registered it (the recipe's instruction)
!if recipe.get("instruction"):
    > {{ recipe["instruction"] }}
!if recipe.get("command"):
    Its command, which you may run (it writes into $NOCK_REVIEW_OUTPUT and reads
    the note from $NOCK_REVIEW_FEEDBACK, both already set): `{{ recipe["command"] }}`

Make the new version in {{ output }} (you may write there and nowhere else;
read the project as you need), then register it once, every file by its full
path, with a note saying what changed and how it answers the owner's note

    .nock/nock review add '{"key": "{{ key }}", "files": ["{{ output }}/…"], "note": "…"}'

(or `"text": …` for a text). The title, tags and recipe carry over.
If what the note asks needs a change to the project's code, which you cannot
make here, register the closest version you can and say so in its note.
End with a line on what you made.

The current version (`.nock/nock review show {{ key }}` has every version)

```json
{{ rendered }}
```
