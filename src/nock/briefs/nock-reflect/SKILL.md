---
name: nock-reflect
description: Run a nock reflection round — three subagents improve the toolbox, keep the map of decisions, and weigh how well nock serves this project; you write the owner a report and a summary they can share. Use when nock says a round is due, or when asked to reflect.
---

# A reflection round

You lead a reflection round on this project. Three subagents do the
looking, at the same time; you start the round, brief them, read what they
find, write the owner a report and a summary they can share, and finish the
round. If you were working on something else in this session, set it aside:
the round starts from its material, not from what you remember.

1. **Start.** `.nock/nock reflect start` starts the round (or picks up one
   left unfinished). It prints the round's name — its date — the moment the
   window opens (the last round's end), the three material files, and the
   two files you will write.

2. **Dispatch the three parts at once** — three subagents in one message,
   each told to read its brief, beside this file, and then its material, to
   do what the brief says, and to answer with its report in its last
   message:

   | part | brief | material | changes |
   |---|---|---|---|
   | the toolbox | `.claude/skills/nock-reflect/process.md` | `process` | `.nock/` but the decisions |
   | the map | `.claude/skills/nock-reflect/knowledge.md` | `knowledge` | `.nock/decisions/map.md`, decisions' tags |
   | nock itself | `.claude/skills/nock-reflect/nock.md` | `nock` | nothing |

   Give each the path of its material and the round's window. None of them
   commits; you do, at the end. If one fails or comes back empty-handed,
   say so in the report rather than doing its part yourself.

3. **Write the report** — the first of the two files `start` named
   (`report.md`). It is for the owner, who knows what the project does and
   wants to know what the round found, in this order:
   - **What needs you**: decisions waiting on review (how many, of what
     kind — the todos worth a look by name), rejected ones still to rework,
     and anything the parts want the owner to settle.
   - **The toolbox**: what changed and why, and what each change should do
     by the next round; how the last round's expectations fared.
   - **The map**: what changed in it, and why.
   - **How nock is doing here**: the nock part's assessment — what works,
     what does not, against the baseline — and what nock should change.
   Keep it to what the owner would act on or want to know; link files by
   path.

4. **Write the summary to share** — `share.md`. It goes, if the owner
   agrees, to nock's makers, to help improve nock. Write it from the nock
   part's shareable account and the round as a whole: what kind of project,
   in a few general words, how long nock has been in use and how much work
   the window held; how nock is used, what it helped with, what got in the
   way, what should change in nock, with the numbers that show it. Keep it
   abstract — no names, paths or code of the project's; `nock share` has an
   agent vet it before anything is sent.

5. **Finish.** With the toolbox part's changes and verdicts:

       .nock/nock reflect finish '{"summary": "the round in a sentence or two",
         "changes": [{"kind": "add", "target": "failures", "why": "…", "expect": "…"}],
         "verdicts": [{"expectation": "…", "held": true, "evidence": "…"}],
         "notes": "what the next round should look at"}'

   It runs nock's checks — the tools load and their examples run, the map
   cites standing decisions, the summary names nothing of the project — and
   refuses while one fails: fix what it says (or have the part that made
   the change fix it) and finish again. It commits `.nock/`; a file outside
   it that a new generator writes, commit yourself.

6. **Tell the owner**, in a few lines: what the round changed, what waits
   on them, where the report is. Then say that the summary is ready to
   share, and why it matters: it is how nock's makers learn how nock does
   in real projects. `.nock/nock share '{"visibility": "private"}'` has an
   agent vet it and shows exactly what would be sent. Private goes only to
   nock's makers; public is published on nock.dev. Ask whether they want to
   share it, and how; send it (`"send": true`) only on their yes.
