---
term: guide.work
aliases: [guide.review, guide.reviewing]
description: The studio's Work tab: topics as rows, decisions, pictures and texts, the viewer, Search and Ask
---

# Reviewing in Work

## The tab

The studio's **Work** tab (`nock studio`, or with `{"open": true}`; `#topics` or `#work`) lists
the topics, newest activity first, each a row: its name, what it holds ("4
decisions · 6 images · 3 texts") and its verdicts ("3 open · 12 accepted · 2 dropped"),
its time ("21m", "3h", "2d", on a small grey pill) with its state's foil mark
beside it (active a slowly turning spinner, planned a ring, done a full circle
with a tick, abandoned one with a cross), its status line in grey right after
its name, and its description. A
topic opens in place, its items in sections, each with its count and a caret
that folds it: decisions as bubbles that open in place on the answer (its
whole width; Markdown's single line breaks flow together, a blank line parts
paragraphs), the alternatives, the files it concerns and Drop, Reject and Accept;
a decision is done unless a small TODO pill under its time says otherwise; a
green tick, a red cross or a muted cross before its time once accepted, rejected or dropped; an open
decision is framed in the foil's cyan and pink (`?decisions=rail` or `lift`
on the page's address shows two other looks); pictures as one line of
thumbnails, each with a ribbon of its title, time and verdict along its foot,
and texts as one line of white previews, their verdict at the bottom right,
both scrolling sideways; an item's options as one card, its title and time
over a small list of them (the preferred one starred); other files as rows;
an open decision also names the session that wrote it, and its parent's.
Accept all and Reject all close it. A picture or
a text opens in a viewer over the list, its title and time on a white
ribbon — a text in a column about 40% of the screen, a picture's viewer
shrunk to the picture, each picture framed in a grey hairline: a version
picked (a glass pill on a foil edge, "Version 3", its list giving each
version's time), or Compare for two side by side, the
newest and the one before by default, each side's select over it (a text's as
a line diff with the changed words marked); an item's options side
by side instead, each with a star to prefer it, Compare off; a Markdown file
rendered, its frontmatter as a ribbon of keys and values, code and data
highlighted, plain text as it is; a click on the file's path says where it
comes from, in a bubble; a click on a picture zooms it in place to its
natural size (twice its size when it is shown about that large already), the
part shown following the cursor — every picture side by side zooms with it, to
the same point, so two versions compare in detail; a click or Esc leaves the
zoom; on a touch screen a tap zooms, a drag pans. ← and → step through the
topic's pictures and texts, Esc closes. A video, a PDF, a page (an HTML page
runs no script there) open there too.

## Search and Ask

One bar toggles **Search**, which filters as you type —
it looks where the owner does: a topic's name, description, status and
thread; an item's title, decision, file names, the text of its text files and
its thread, the names of the files its messages carry too, in either (not a recipe, a `from`, a ref, or nock's own notes such as a
split's); every word must be in the topic and the item together, one at least
in the item. From three letters it opens the topics and decisions (and
unfolds the sections) holding what it finds, rings each picture, text or file
found in foil (a decision only shows the words), scrolls to the first and
washes the words found pink to cyan; Enter, Shift+Enter or the
arrows in the field go from hit to hit, and clearing the search closes what
it opened, not what the owner did — and **Ask**: a question goes to a headless agent (the asker seat) that reads
the topics and answers in markdown, with the items it relied on as cards
that open them, one question at a time, cancellable. The tab keeps up with
what agents submit without drawing again what did not change.
`#topics/TOPIC` opens a topic, `#topics/TOPIC/SLUG` an item; `#170` the item
an earlier nock's decision 170 became.
