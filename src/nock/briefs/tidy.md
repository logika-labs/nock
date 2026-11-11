# Tidy up the topics

The owner of this project pressed Tidy up in nock's studio. The topics are
where agents put their work before the owner: topics (a piece of work, with
a state and a status line) holding decisions, each with the assets that show
it, the owner's verdict (open until they give one) and a thread. Over time it
sprawls. Your job is to leave it in order, so the owner sees what matters
first. They watch your words as you write; say briefly what you are doing as
you go.

They are files under `.nock/shared/topics/` (`.nock/nock docs files` has each
kind), and you change them by writing new event files, any name ending
`.json`, in a topic's or a decision's `events/`; nothing is ever edited.
Everything you write lands as one commit when you finish, and the owner can
undo it with one click; still, change only what you can justify from what is
there. Read first: `.nock/local/views/index.md` and each topic's view beside
it, and `.nock/nock search "<words>"`.

# What to do

1. **Regroup.** Move a decision that sits in the wrong topic: `{"kind":
   "moved", "to": "<other>"}` in its `events/` (its versions, assets and
   thread go with it; its old ref still resolves). Merge near-duplicate
   topics: move the decisions of one into the other, then set the emptied
   one abandoned. Split a sprawling topic: create the new one (`{"kind":
   "created", "description": "…"}` in `topics/<new>/events/`) and move its
   decisions there.
2. **Set where each topic stands,** from what is actually there: `{"kind":
   "state", "state": "done", "status": "…"}` in its `events/` — planned,
   active, review (its work built, only the owner's verdicts open), done
   (its work finished, nothing open) or abandoned. A done or abandoned topic
   takes no new decisions: move them before closing it.
3. **Drop what matters less.** An open decision superseded by a newer one,
   or stale (what it decides was changed since, what it shows is gone, an
   older render a newer one replaces): drop it, with a comment saying why:
   `{"kind": "verdict", "verdict": "dropped", "comment": "Dropped by Tidy
   up: superseded by [topic/slug]."}`. Leave accepting and asking for
   rework to the owner; leave alone what the owner is still discussing
   (the owner wrote last in its thread) and anything you are unsure of.
4. **Prioritize.** Give every planned, active or review topic its place in
   the owner's order, 1 first, by what needs the owner soonest and matters
   most, with a one-line reason in its status: `{"kind": "state",
   "priority": 1, "status": "first: three decisions block the release"}`.
   Done and abandoned topics take no priority (`"priority": 0` takes one
   away).

Write only in `.nock/shared/topics/`, and run nothing else. Don't reword
the owner's or the agents' messages, and don't record new decisions.

# When you finish

End with a short summary for the owner, as markdown: its first line says
in a few words what you did (it becomes the commit's subject, so no
heading), then a short list: what moved where, what you set done or
abandoned, what you dropped and why, and the order you gave, top first.

!if topics:
    # The topics now

    {{ topics }}
