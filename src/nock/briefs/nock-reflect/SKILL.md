---
name: nock-reflect
description: Run a nock reflection round. Three subagents improve the toolbox, keep the map of decisions, and judge how nock serves this project; you write the owner a report and a summary they can share. Use when nock says a round is due, or when asked to reflect.
---

# A reflection round

Set aside whatever this session was doing: the round works from its
material, not from memory.

1. `.nock/nock reflect start` prints the round's window, its three material
   files and the two files you write.
2. Dispatch three subagents in one message. Give each its brief (beside this
   file), its material and the window; each answers with a report. None
   commits.

   | part | brief | material | may change |
   |---|---|---|---|
   | toolbox | `process.md` | `process` | `.nock/`, not the decisions |
   | map | `knowledge.md` | `knowledge` | `.nock/decisions/map.md`, tags |
   | nock | `nock.md` | `nock` | nothing |

   If one fails, say so in the report; don't do its part yourself.
3. Write `report.md` for the owner: what needs them (decisions to review,
   rejected ones to rework, what the parts want settled), what changed in the
   toolbox and the map and why, and how nock is doing here. Only what they
   would act on or want to know.
4. Write `share.md`, a short summary for nock's makers from the nock part's
   shareable account: the kind of project in general words, how much work the
   window held, what nock helped with, what got in the way, what should
   change, with numbers. No names, paths or code of the project's;
   `nock share` vets it before anything is sent.
5. Finish with the toolbox part's changes and verdicts. It runs nock's checks
   and refuses while one fails: fix it, or have the part fix it, and finish
   again. It commits `.nock/`; commit a generated file outside it yourself.

       .nock/nock reflect finish '{"summary": "the round in a sentence or two",
         "changes": [{"kind": "add", "target": "failures", "why": "…", "expect": "…"}],
         "verdicts": [{"expectation": "…", "held": true, "evidence": "…"}],
         "notes": "what the next round should look at"}'

6. Tell the owner in a few lines what changed, what waits on them and where
   the report is. Say the summary is ready to share, which is how nock's
   makers learn how nock does in real projects:
   `.nock/nock share '{"visibility": "private"}'` shows what would be sent
   (private goes to nock's makers only; public is published on nock.dev).
   Send it (`"send": true`) only on their yes. If `reflect start` gave
   `tell_the_owner`, tell them that too, in its words: it is what nock
   shares with its makers, said once.
