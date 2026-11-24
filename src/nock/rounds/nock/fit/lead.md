# The fit round

1. Dispatch the `nock-fit` subagent with its material (below) and the
   round's window. It judges how nock serves this project and which rounds
   fit it and how each should be set here, changing nothing, reading its own
   brief. If it fails, say so in the report; don't do its part yourself.
2. **Set the rounds up.** From the part's account, write each round's
   settings in `.nock/config.toml` under `[rounds."NAME"]`: `enabled =
   false` for a round that doesn't fit; `paths` (globs) for what it looks at
   here — where this project authenticates, authorizes, routes requests and
   handles uploads for the security audit, its route code and API schema
   (`any`) for the API fuzz, its web UI for the UI fuzz, its source and tests
   for the tests audit; a `threshold` where the default is wrong for its
   pace. Each is a change of kind `rounds`.
3. **Keep the memory.** `.nock/shared/memory.md` is the one place for what
   nock has learned about the project and its owner; every session reads it
   first, and an orchestrator points its agents to what bears on their work.
   From the part's account, edit it: add what the window taught (which
   rounds fit and how they are set, how the owner likes to work), prune and
   merge what is stale or repeated, and reshape it as the part found it is
   used (split a part into a file it points to, regroup it). It stays small:
   the `nock-memory` check holds it to its size. Each change is of kind
   `memory`.
4. Write `report.md` for the owner: what needs them and how nock is doing
   here, with the rounds you set up and the memory's changes. Only what
   they would act on or want to know.
5. Write `share.md`, a short summary for nock's makers from the part's
   shareable account: the kind of project in general words, how much work
   the window held, what nock helped with, what got in the way, what should
   change, with numbers. No names, paths or code of the project's.
6. Submit with the changes (kinds rounds, memory, recommend, other). It
   commits `.nock/config.toml`, runs the `nock-share` check, and, when
   `share` is true, has a fresh agent vet the summary and sends it to
   nock's makers. If it gives `ask_the_owner`, ask the owner that, in its
   words, and record exactly their answer with `.nock/nock config share
   true` or `false`; nothing if they don't answer.
7. Report the round in your final message, to the session that ran it: the
   rounds set up, the memory's changes, what needs the owner, and where
   `report.md` is. If the round found something nock itself lacks or gets
   wrong, offer to send it to nock's makers with `.nock/nock report`, on
   their go-ahead.
