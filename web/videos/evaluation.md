# Evaluation: "Choose the best way forward, from real runs"

About 60 seconds. Captions only, no voiceover. Each row is a beat: the picture, then the caption on screen.

| Time | Picture | Caption |
|---|---|---|
| 0–6s | The studio's Experiment tab on a small real scenario in the sample repository: a bug planted in a billing package, and the tree fanning out from it into agents of two models, each run twice. | When you program with AI, you can send several agents to explore different options at once. |
| 6–12s | Three of those agents' real answers to the same bug, side by side, each in its own words. | The hard part becomes tracing their work, and judging it. |
| 12–20s | A bigger real experiment in the same tab: Logika's evaluation on a real open-source app, its expensive stage ringed with what one run of it took, in minutes and dollars. | There are many parameters to tweak, and agents' work is slow, costs money, and comes out different every time. |
| 20–28s | Back to the small scenario, its stages drawn left to right: the app, the agent set up with its model, the bug planted, the fix, the score; each fork's label lights as the view passes it. | So nock breaks an experiment into stages, each branching on parameters: models, skills, anything. |
| 28–35s | The decisions after the stages, each branch with its verdict mark (the tests catch the bug? the fix found it? fixed it?), and the measures above them, counted per model. | Each stage's results are scored against criteria, or decide what runs next. |
| 35–44s | The terminal: `nock eval run --dry` says what would run and what it would cost, and the run. Then the scoring changes and it runs again: only the scoring recomputes, everything before it restored from the cache. | Every stage is cached once it runs: a memoized graph that's easy to read, and saves time and money. |
| 44–51s | In the studio, one run opened: its trajectory lights up, and each stage shows what it made: the planted line, the agent's fix, its answer, the score. | You can drill into any run to see exactly what happened… |
| 51–57s | A Claude Code session asks which model did better and at what cost; the agent runs `nock eval compare` and `nock eval query` and answers from them. | …or let your agent query the trends, without inventing a methodology. |
| 57–60s | The nock wordmark, `uvx nock init` and nock.dev. | Trace and judge your agents' work, and choose the best way forward. |

## Notes

- Footage: the small scenario is a real eval in the sample repository (`evals/fix`: three planted bugs, Haiku and Sonnet, two repetitions), run for real with `nock eval run`; the terminal is recorded with VHS, the studio is the real Experiment tab on a demo studio, and the agent's question is a real Claude Code session. The bigger experiment is Logika's own, read from its committed cache.
- No number is written for the video: every figure on screen (cost, minutes, counts) is what the runs recorded. The open-source app is not named and neither are its bugs.
- Like the other two, the video opens and closes on the card: the gradient, "nock", `uvx nock init` and nock.dev.
