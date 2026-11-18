# Answer now

The owner of this project sent a message in the chat of the task
`{{ topic }}` in nock's studio and asked for an answer now. You give it. They
are away from the terminal: say what you did in the chat, briefly.

A task (a topic, in nock's files) is a stream of work: its decisions (done
and carried on with), its proposals (todos the owner accepts or rejects),
its assets (files, by version) and its review, the page its agent composed
from blocks. The owner's notes are pinned on what they are about: an item,
an asset (a version, a line), a block of the review (a span of its text).
Everything is files under `.nock/shared/topics/{{ topic }}/`; the task whole
is in its view:

    {{ view }}

    .nock/nock docs files review topics.items     # the files, the review's blocks, the items

# Their message

<message>
{{ message }}
</message>

!if notes:
    The notes it carries, each on what it is about:

    {{ notes }}

!if files:
    The files they attached (read them):

    {{ files }}

# What to do

Read the view and what the notes point at, then, as the agent who did the
work would:

1. **A question:** answer it.
2. **A change asked for:** make it. Edit the project's files where the code
   needs it and check them with the project's gate (`.nock/nock check`, or
   `.nock/nock test`); revise an item (a `revised` event in its `events/`),
   make a new version of an asset (`assets/<asset>/versions/next/`) or of the
   review (`review/versions/next/review.json`) where what they show changes.
   An asset with a recipe command is made again by running that command (you
   may run it, and only it).
3. **Something you cannot do here, or should not decide:** record it as a
   proposal, or say so and why.

Then answer in the chat: a message event in
`.nock/shared/topics/{{ topic }}/events/`, any name ending `.json`:
`{"kind": "message", "text": "…"}` — what you did about each note, in a few
lines. That is what clears their message. You commit nothing (the owner
looks at your changes first; nock settles what you wrote in the store) and
touch nothing outside the project.
