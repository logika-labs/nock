---
term: review
aliases: [compose, blocks, story, review-preferences, preferences]
description: Composing a task's review: the blocks, when to show a diff or an excerpt, telling it as a story
---

# Composing the review

The review is the task's main page: what the owner reads to know, at a
glance, what changed, what it means for them, and what needs them. You
compose it from blocks, as a story, when the work is built (and again when
it changes: a new version replaces it). The owner reads it in the studio,
told as you composed it or listed flat by kind; both show the same items
and assets with the same controls (Accept and Reject on proposals, a note on
anything). They press Done when they have been through it: every decision
without a note counts as fine.

Write it in `.nock/shared/topics/TOPIC/review/versions/next/review.json`:

    {"summary": "Orders moved to SQLite; one proposal waits",
     "blocks": [
       {"kind": "text", "text": "Orders now live in one SQLite file …"},
       {"kind": "item", "item": "sqlite"},
       {"kind": "diff", "asset": "schema", "from": 1, "to": 2, "caption": "The new table"},
       {"kind": "item", "item": "archive-yearly"}]}

`summary` is the line the task list shows. Every block may have an `id`
(kept across versions, so the owner's notes stay pinned), a `title` and a
`caption`.

## The blocks

- **text** `{"text": markdown}`: the story between the things it shows.
  Short paragraphs; say what changed for the owner, not how you worked.
- **item** `{"item": SLUG}`: a decision or a proposal, inline with its
  controls. Every proposal belongs in the review; decisions that matter to
  the owner do too — routine ones can stay in the list.
- **diff** `{"asset", "from", "to"}`: two versions of an asset, line by
  line. Use it when the change itself is the point (a prompt, a config, a
  schema, copy) and it is short enough to read; `from`/`to` default to the
  last two versions.
- **excerpt** `{"asset", "lines": [first, last], "version"}`: some lines of a
  file — the part that matters of a long one, or of a new file with no before.
- **doc** `{"asset", "version"}`: a whole document (markdown is rendered):
  a page of copy, a spec, a report.
- **image** `{"asset", "version"}`: a screenshot, a picture, a video.
- **table** `{"columns": [...], "rows": [[...]]}`: numbers or comparisons
  the owner reads across.
- **chart** `{"chart": "bar" | "line", "labels": [...], "series": [{"name", "values"}], "unit"}`:
  a trend or a before/after in numbers.
- **html** `{"file": "flow.html", "height": 320}`: your own page, beside
  `review.json`, for what nothing built-in shows (a flow, an interactive
  comparison, a layout at three sizes). It runs sandboxed with nock's look
  (`label`, `grid`, `row`, `card`, `caption`, `checker`, `dark`) and a
  bridge: `nock.note(text, quote)` leaves the owner's note on the block,
  `nock.accept(slug)` / `nock.reject(slug)` give a proposal its verdict,
  `nock.open("#/t/TOPIC/item/SLUG")` goes somewhere. It sizes itself.
  The next reflection round looks at the html blocks agents write: one that
  keeps coming back becomes a built-in.

## When to show what

- Show a **diff** when the owner should judge the change itself; an
  **excerpt** when only a few lines of a long file matter; **nothing** when
  the change is mechanical (a rename, a dependency bump, generated code) —
  a decision's line says it.
- Show a **picture** when it is about what someone sees; a **table** or a
  **chart** when it is about numbers.
- One block per thing. Don't repeat in text what an item says.

## Telling it as a story

Open with what changed for the owner in two or three sentences. Then the
parts, each a short text and what shows it, in the order the owner would
want to judge them: what needs them first (the proposals), then what
changed that they would want to know, then the rest. End with what is left
or what comes next, if anything. Nothing about how you worked, what you
tried, or the checks you ran unless one failed.

When the review is written, set the topic to review (`docs topics.state`).
