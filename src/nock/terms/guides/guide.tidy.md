---
term: guide.tidy
aliases: [guide.tidy-up, guide.tidier]
description: Tidy up: a headless agent reorganizes Work in one commit you can undo
---

# Tidy up

**Tidy up**, at the end of the filters' line in Work, sends a headless agent (the tidier
seat, `briefs/tidy.md`) to reorganize Work, after a short confirm: it moves
misplaced items, merges near-duplicate topics and splits sprawling ones,
sets each topic's state and status from what is there (review for one
whose work is built and waits only on the owner's verdicts), drops stale or
superseded items with a comment (`"rework": false`: dropped, nothing to
rework; it never accepts nor asks for rework, which `items judge` refuses
it), and gives the planned, active and review
topics a priority, a one-line reason in each status. Its writes are not
committed one by one: when it ends they land as **one commit**, "Work tidied
up: …", with its summary. It runs in the global chat (see [Chatting](#the-global-chat)),
which opens to show it working, and ends with the summary and **Undo**, which
`git revert`s that commit (refused, nothing changed, when later commits conflict with it).

The tidier changes Work only through nock's commands, the owner having pressed
Tidy up (see [What nock's agents may do](#what-nocks-agents-may-do)).
