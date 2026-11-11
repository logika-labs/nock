---
term: reflection.lead
aliases: [nock-reflect]
description: /nock-reflect: how the lead runs a reflection round, step by step
---

# A reflection round

Set aside whatever this session was doing: the round works from its
material, not from memory.

1. `.nock/nock reflect` prints the round's window, its three material
   files and the two files you write.
2. Dispatch three subagents in one message, each of its type (nock installs
   them in `.claude/agents/`, each with only the tools its part needs, and
   each reads its own brief, `.nock/nock docs TERM`). Give each its material
   and the window; each answers with a report. None commits.

   | part | subagent type | brief | material | may change |
   |---|---|---|---|---|
   | toolbox | `nock-reflect-toolbox` | `reflection.toolbox` | `process` | `.nock/`, not the topics |
   | map | `nock-reflect-map` | `reflection.map` | `knowledge` | `.nock/shared/map.md` |
   | nock | `nock-reflect-nock` | `reflection.nock` | `nock` | nothing (it has no editing tool) |

   If one fails, say so in the report; don't do its part yourself.
3. Write `report.md` for the owner: what needs them (items open in Topics,
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
   again. A command the part added fails `nock-wiring` until
   `.nock/nock init` allows it; Claude Code asks the owner for that (unless `permissions.confirm` is "allow"). It commits `.nock/`; commit a generated file outside it yourself.

       .nock/nock reflect finish '{"summary": "the round in a sentence or two",
         "changes": [{"kind": "add", "target": "failures", "why": "…", "expect": "…"}],
         "verdicts": [{"expectation": "…", "held": true, "evidence": "…"}],
         "notes": "what the next round should look at"}'

6. Tell the owner in a few lines what changed, what waits on them and where
   the report is. Say the summary is ready to share, which is how nock's
   makers learn how nock does in real projects:
   `.nock/nock share` shows what would be sent (only nock's makers read it;
   nothing is published). Send it (`'{"send": true}'`) only on their yes. If `reflect` gave
   `ask_the_owner`, ask them that too, in its words: whether nock may share
   its weekly usage report, asked once. Record exactly their answer with
   `.nock/nock config share true` or `false`; nothing if they don't answer.
   If the round found something nock itself lacks or gets wrong, offer to
   send it to nock's makers with `.nock/nock report`, on their go-ahead.
