# The fit round

1. Dispatch the `nock-fit` subagent with its material (below) and the
   round's window. It judges how nock serves this project, which rounds fit
   it and how each should be set here, and how the owner meets the reviews,
   changing nothing, reading its own brief. If it fails, say so in the
   report; don't do its part yourself.
2. **Set the rounds up.** From the part's account, write each round's
   settings in `.nock/config.toml` under `[rounds."NAME"]`: `enabled =
   false` for a round that doesn't fit; `paths` (globs) for what it looks at
   here — where this project authenticates, authorizes, routes requests and
   handles uploads for the security audit, its route code and API schema
   (`any`) for the API fuzz, its web UI for the UI fuzz, its source and tests
   for the tests audit; a `threshold` where the default is wrong for its
   pace. Then record what you set as one **decision** in this round's task
   (`round-nock-fit`, in `.nock/shared/topics/round-nock-fit/items/`, `docs
   files.item`): its title "Rounds set up for this project", `means` the
   rounds on and off and what each looks at, in a few lines. Each is a change
   of kind `rounds`.
3. **Keep the memory.** `.nock/shared/memory.md` is the one place for what
   nock has learned about the project and its owner; the orchestrator reads
   it first and points its agents to what bears on their work. From the
   part's account, edit it: add what the window taught (which rounds fit and
   how they are set, the owner's review preferences, how they like to work,
   how long work really takes against its estimates — the calibration
   agents read when they estimate), apply the owner's notes on its lines,
   prune and merge what is stale or repeated, and reshape it as the part
   found it is used (split a part into a file it points to, regroup it). It
   stays small: the `nock-memory` check holds it to its size and to items
   that exist. Each change is of kind `memory`.
4. **Grow the review.** From the part's account of the html blocks and the
   owner's notes and skips, record **proposals** in the same task: promoting
   a custom html block that keeps coming back into a built-in block kind of
   nock's (title "Make a built-in X block", `means` what it shows and which
   reviews used it, `takes` roughly what); and changes to the project's
   review preferences: what to show more or less, how.
   Each is a change of kind `review`. Accepted, a preference is written into
   the memory by the agent that carries it out (`nock docs review` shows the
   memory to every agent composing a review); a built-in block is a
   change to nock itself, to offer the owner sending with `.nock/nock report`.
5. Write `report.md` for the owner: what needs them and how nock is doing
   here. Only what they would act on or want to know. The round's task
   shows it with your decisions and proposals.
6. Write `share.md`, a short summary for nock's makers from the part's
   shareable account: the kind of project in general words, how much work
   the window held, what nock helped with, what got in the way, what should
   change, with numbers. No names, paths or code of the project's.
7. Submit with the changes (kinds rounds, memory, review, recommend, other). It
   commits `.nock/config.toml`, runs the `nock-share` check, writes the
   round's task with its review, and, when `share` is true, has a fresh agent
   vet the summary and sends it to nock's makers. If it gives
   `ask_the_owner`, ask the owner that, in its words, and record exactly
   their answer with `.nock/nock config share true` or `false`; nothing if
   they don't answer. If the round found something nock itself lacks or gets
   wrong, offer to send it to nock's makers with `.nock/nock report`, on
   their go-ahead.
