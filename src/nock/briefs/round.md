# Run the {{ title }} round

The owner of this project pressed Run on the {{ title }} round
(`{{ protocol }}`) in nock's studio. Nobody will answer questions: run the
round whole, to its submit, as a session the owner started would.

    .nock/nock reflect {{ protocol }}

prints the round's brief for its lead (you), its agents (subagent types you
dispatch with the Agent tool, each with its brief and material), the files to
write and the submit. Do what it says, to the end: `.nock/nock reflect
--submit …` records it. If a part fails, say so in the report rather than
doing its part yourself.

Its result is a task to review: the task `{{ topic }}`. Submitting writes it
(the round's summary, report and changes, as decisions); put there what
needs the owner too — a proposal for each thing you would have them decide,
in `.nock/shared/topics/{{ topic }}/items/<slug>/events/`
(`.nock/nock docs topics.items`). End with a short summary.
