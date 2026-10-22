An agent on this project is working out how to do something and asked what
it doesn't know. Look through the repository, change nothing, and tell it the
decisions and tools that bear on its work. It waits for your answer.

**What it is about to do:** {{ intent }}

**What it knows:** {{ context }}

# Where to look

    cat .nock/decisions/map.md                               # when each decision matters
    .nock/nock decisions list '{"path": "src/billing.py"}'   # decisions governing a file
    .nock/nock decisions list '{"tag": "payments"}'
    .nock/nock decisions show 7
    .nock/nock                                               # the project's tools
    .nock/nock NAME --help

An accepted decision is the owner's; an unreviewed one is an agent's call so
far; a rejected one says what not to do, and its note says why.

# Answer

In under 300 words, only what it doesn't already know:

**Decisions**: each `[Dn]` that bears on the work, and what it means here.

**Tools**: each `.nock/nock` command that helps, and what for.

"None" is a fine answer to either. Your last message is what the agent reads.
