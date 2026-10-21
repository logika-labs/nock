An agent working on this project recorded decision {{ decision["number"] }},
and the owner asked for more before reviewing it. You are a fresh session,
here only to say it better. Nobody will answer you.

# The decision

```json
{{ rendered }}
```

`note`, when there is one, is the owner's: what they found missing, or want
looked at.

# What to do

1. Find out what the decision needs. Read the code, the documents, git
   history, and the other decisions (`.nock/nock decisions list`,
   `.nock/nock decisions show N`): it may depend on one of them, or
   contradict one.
2. Change nothing in the project: read, run, try things in a scratch
   directory, but leave the repository as you found it.
3. Edit the decision, once, with one JSON record:

       .nock/nock decisions edit '{"number": {{ decision["number"] }}, "summary": …, "evidence": […], "alternatives": [{"option": …, "why_not": …}]}'

   - `summary` is Markdown for someone who knows what the system does but
     not how it is built: what was decided, what it changes, what it costs
     and rules out. Answer the owner's note first, in its own terms.
   - `evidence` is what you found, a line each — the files, numbers or
     commits that show it.
   - `alternatives` are the ways that were really open, each with why not;
     drop one that turns out moot, add one you found. If you find the
     decision is wrong, say so in the summary: the owner decides.
   - Keep the title unless it no longer says what was decided.

Finish with a line saying what you added.
