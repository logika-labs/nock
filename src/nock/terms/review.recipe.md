---
term: review.recipe
aliases: [recipe, regenerate, regenerator]
description: How an item is made again: a command, an instruction, or both
---

`recipe.command` runs in the working tree with the owner's note in $NOCK_REVIEW_FEEDBACK and writes the files into $NOCK_REVIEW_OUTPUT; nock registers them. `recipe.instruction` is for an agent: given the note and the current version, it makes the files in its work directory (it may run the command) and registers them with `review add`. The owner's Regenerate runs it; the new version records the note it answers.
