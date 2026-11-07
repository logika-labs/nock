# The question

The owner of this project asks, about the work agents have put before them:

<question>
{{ question }}
</question>

# Instructions

The project's agents submit their work as items in topics: a topic is a piece
of work, an item a decision, project files or something made to show part of
the project, each with a verdict the owner gives (open until then) and a
thread. Answer the question from them; change nothing.

1. Find what bears on it:

       .nock/nock topics list --query "<words>" --full
       .nock/nock items list --query "<words>" --full
       .nock/nock topics show <topic>
       .nock/nock items show <topic/slug>

   Read the code or its history only when the items alone do not answer it;
   `.nock/nock docs topics topics.verdicts` has how topics and verdicts work.
2. Submit the answer, naming the items it rests on:

       .nock/nock topics answer '{"answer": "<markdown>", "items": ["<topic/slug>"]}'

   The owner sees the answer as written, then each item named as a card that
   opens it, so don't repeat their titles. A name that doesn't exist is
   refused: fix it and submit again. If nothing answers it, say so in a
   sentence; that is a fine answer.

Be short: a few sentences or a short list, under 200 words.

!if topics:
    # The topics

    {{ topics }}
