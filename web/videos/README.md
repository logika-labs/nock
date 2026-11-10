# nock.dev's videos

Three minutes on the landing page, each from a script beside this file: `reflection.md` ("Your agents
build the tools they need") and `review.md` ("You decide, when it suits you"), the owner's, and
`evaluation.md` ("Choose the best way forward, from real runs"), written from the Evaluations essay.
Captions only, burned in at the top of the frame and also served as WebVTT; no voiceover. Each opens
and closes on the same card: the site's field and grain, "nock", `uvx nock init` and nock.dev.

Nothing is faked that claims to be a real interface. The terminal is real Claude Code sessions in a
sample repository, recorded with [VHS](https://github.com/charmbracelet/vhs); the studio is the real
`nock studio` on that repository, driven by Playwright and taken as 2x stills. Remotion composes them
on the site's look: the field, the cards, the captions, the end card. A scene the script asks for that
cannot be filmed as one take (three sessions side by side) is composed from separate real recordings,
sped up, with the speed on each card.

| Path | Is |
|---|---|
| `src/` | the compositions (`reflection.tsx`, `review.tsx`, `evaluation.tsx`, `parts.tsx`) and `captions.json`, the opening card's length (`intro`) and each beat's time and words, which the videos burn in and `scripts/finish.mjs` writes as WebVTT |
| `record/session.py` | records one Claude Code session: tmux runs `claude` in the sample repository, VHS attaches and records, the script types the prompts and waits for each turn to end (the repository's Stop hook marks it) |
| `record/tapes/` | VHS tapes of plain shell sessions (the evaluation's `nock eval` runs) |
| `record/shots.py`, `record/steps/` | the studio's stills: each step opens a page, clicks and types as the owner would, and saves the viewport and the boxes of what it names |
| `record/prepare.py` | `public/data/NAME.json`, what a composition shows: its recordings and their lengths, its stills and where to look in them, and for the reflection video the sample's own telemetry and the tool its round wrote |
| `scripts/finish.mjs` | renders, then writes `../site/videos/NAME.{mp4,webm,jpg,vtt}`, each video under 10 MB, and the review video's two stills Getting started shows (`review-work.webp`, `review-verdict.webp`) |

`public/` (the recordings, stills and data) and `out/` (the masters) are made, not committed. Of what
`web/site/videos/` holds, the posters, captions and stills are committed; the MP4s and WebMs are not:
`web/deploy.py` ships them from the working tree, and refuses to release while one the pages play is
missing.

## Making them again

Remotion is free for individuals and companies of up to three people; past that it needs a company
licence (Logika's `marketing-videos` topic has the decision).

1. **The sample repository**, `~/demo/tally`: a small billing package (charges, refunds, invoices,
   the nightly sweep) with about a hundred pytest tests and `web/` (a charges page, three badge
   variants, `web/shoot.py`), with nock initialised from this checkout
   (`uv run --project PATH/TO/nock nock init`), `.nock/config.toml` with `permissions.confirm = "allow"`,
   `share = false` and `[checks.test] command = "pytest -q"`, a `.venv` with pytest and playwright,
   and a gitignored `.claude/settings.local.json` that allows Bash, Edit and Write and adds a Stop
   hook, `date +%s >> "$HOME/demo/marks/stop"`, which `record/session.py` waits on. Commits are by a
   made-up author (`git config user.name`), so no real name shows.
2. **The reflection video's sessions**: commit a small break, record a session that finds it, reset;
   five times, each with its own break (refunds `>` for `>=`, rounding half up, an invoice line
   counted at least once, the sweep's cool-off `>`, ...): `s1` at 1680x860, `s2`–`s4` at 1120x1400 for
   the side-by-side, prompts asking which test fails and why, from pytest's output with tail and grep,
   without changing code. Then `/nock-reflect` (`round`, `"until_files":
   [".nock/reflections/DATE/record.json"]`, so the recording waits for the round's background parts),
   then a break and a plain "which test fails, and why?" (`s5`), which the round's new `failures`
   answers. Each spec is `{"repository", "width", "height", "font_size": 20, "framerate", "prompts"}`:
   `python3 record/session.py SPEC.json public/clips/NAME.mp4`.
3. **The review video**: `v1`, "The nightly sweep requeues charges that are still retrying. Fix it.
   I'm away until tomorrow, so make the calls yourself; put your work under a topic named
   charge-sweep."; then the items the topic fills with (`.nock/nock items create`: the retry email as
   text, the charges page shot, the Retry now video, the three badges as options; the email's second
   version); then the studio (`.nock/nock studio '{"port": 8790}'`, never the owner's on 8765) and
   `uv run --no-project --with playwright python record/shots.py http://127.0.0.1:8790/
   record/steps/FILE.json` for each steps file in the order the video tells it: list and open (on a
   clone of the repository at the commit with only the decision), the three fills (clones at each
   item's commit, since the studio reads what is committed), choose, comment, comment2, addressing
   (Address my comments runs the real addresser), reply (the owner picks the addresser's option 1
   and addresses again; the addresser may not run the shot's recipe, so its v2 is made by running the
   recipe and `items update --version`), answers, verdicts, done (after
   `.nock/nock topics update charge-sweep '{"state": "done"}'`). Last, `v7`: "Customers say some
   charges sit in retrying for days. Change the sweep so it requeues a charge that has been retrying
   for more than a day.", which consults nock and meets the accepted decision.
4. **The later round's cards**: three decision items in a `toolbox` topic (a new `coverage`, `seed`
   retired, `failures --since main`), each with what it expects by the next round, then
   `record/steps/round-cards.json`. A real round writes its changes to its report and `record.json`,
   not to Work; the script asks for them in Work, so these are staged.
5. **The evaluation video**: the sample's eval `evals/fix` (a bug planted per `parameters/bug/*.json`, an
   agent of each model in `MODELS` fixing it from the customer's complaint, twice, and the fix scored;
   `studio.json` words it), its cache committed. With the sample's nock studio on 8790, `vhs
   record/tapes/evaluation-run.tape` records the dry run and the run from an empty cache; a change to
   `steps/scored.py`, then `record/tapes/evaluation-rerun.tape` records the rerun of the scoring alone;
   `record/steps/evaluation.json` shoots the Experiment tab; `record/specs/evaluation-ask.json` (with
   `record/session.py`) records an agent asked which model did better. Logika's own experiment is shot
   from a clone of Logika's repository (`git clone --local`, its cache committed) with its studio on 8791
   (`record/steps/evaluation-logika.json`), never the owner's.
6. `python3 record/prepare.py NAME ~/demo/tally` for reflection, review and evaluation, `pnpm install`,
   `pnpm finish`; then `python3 web/build.py` at the repository's root.

`pnpm studio` previews a composition; `pnpm still reflection out/f.png --frame=N` checks one frame.
