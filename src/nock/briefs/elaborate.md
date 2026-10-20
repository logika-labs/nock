An agent working on this project asked its owner question {{ question["number"] }},
and the owner asked for more before deciding. You are a fresh session, here
only to say the question again, better. Nobody will answer you.

# The question

```json
{{ rendered }}
```

`owner` is what the owner said: `comment`, when there is one, is what they
found missing or want looked at; `choice`, the option they lean towards.

# What to do

1. Find out what the question needs. Read the code, the documents, git
   history, and the questions already answered (`.nock/nock questions list
   --state closed`, `.nock/nock questions show N`): the decision may be
   settled there, or depend on one that is.
2. Change nothing in the project: read, run, try things in a scratch
   directory, but leave the repository as you found it.
3. Rewrite the question, once, with one JSON record:

       .nock/nock questions rewrite {{ question["number"] }} '{"title": …, "context": …, "options": […], "recommended": 1}'

   - `context` is Markdown the owner reads cold: what the decision is, what
     each way leads to (what changes, what it costs, what it rules out), and
     what you found — with the files, numbers or commits that show it. Answer
     the owner's comment first, in its own terms.
   - `options` are real, distinct answers, in the order you would weigh them;
     drop one that turned out moot, add one you found. `recommended` is the
     number of the one you would take, and `context` says why.
   - Keep the title unless it no longer says what is being decided.

Finish with a line saying what you added.
