# The fit round

1. Dispatch the `nock-fit` subagent with its material (below) and the
   round's window. It judges how nock serves this project and which other
   rounds would fit it, changing nothing, reading its own brief. If it
   fails, say so in the report; don't do its part yourself.
2. Write `report.md` for the owner: what needs them (decisions open in
   Topics, rejected ones to rework, what the part wants settled) and how
   nock is doing here. Only what they would act on or want to know.
3. For each round of the catalogue the part finds would serve the project
   and that is not adopted, record a decision in the topic `rounds`
   (`.nock/nock docs topics.items`): its title "Run NAME here", its answer
   why, its alternative "don't". The owner's acceptance adopts it.
4. Write `share.md`, a short summary for nock's makers from the part's
   shareable account: the kind of project in general words, how much work
   the window held, what nock helped with, what got in the way, what should
   change, with numbers. No names, paths or code of the project's.
5. Submit with the part's changes (kinds recommend, other). It runs the
   `nock-share` check; when `share` is true it has a fresh agent vet the
   summary and sends it to nock's makers. If it gives `ask_the_owner`, ask
   the owner that, in its words, and record exactly their answer with
   `.nock/nock config share true` or `false`; nothing if they don't answer.
   If the round found something nock itself lacks or gets wrong, offer to
   send it to nock's makers with `.nock/nock report`, on their go-ahead.
