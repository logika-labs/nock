---
term: guide.work
aliases: [guide.review, guide.reviewing]
description: The studio's Work tab: topics as rows, decisions, pictures and texts, the viewer, Search and Ask
---

# Reviewing in Work

## The tab

The studio's **Work** tab (`nock studio`, or with `{"open": true}`; `#topics` or `#work`) lists
the topics in the owner's order — by `priority` (1 first; `topics update
TOPIC '{"priority": 1}'`, 0 takes it away), then the rest, newest activity
first — each a row: its name, what it holds ("4
decisions · 6 images · 3 texts") and its verdicts ("3 open · 12 accepted · 2 dropped"),
its time ("21m", "3h", "2d", on a small grey pill) with its state's foil mark
beside it (active a slowly turning spinner, planned a ring, done a full circle
with a tick, abandoned one with a cross; a topic in review shows none, since
waiting on the owner needs no mark), its status line in grey right after
its name, and its description. A
topic opens in place, its items in sections, each with its count and a caret
that folds it: decisions as bubbles that open in place on the answer (its
whole width; Markdown's single line breaks flow together, a blank line parts
paragraphs), the alternatives, the files it concerns and Drop, Reject and Accept;
a decision is done unless a Todo pill under its time (white on a foil edge, like Tidy up) says
otherwise; before its title, its verdict: a dashed foil ring while open, a black tick on a cool foil
circle (cyan into lavender) once accepted, a black cross on a warm one (yellow into pink) once
rejected, a muted cross once dropped (hovered, in plain words: "Accepted on Nov 23, 2026 at 14:05",
in local time; a topic's state mark likewise says when it was set); an open
decision is framed in the foil's cyan and pink (`?decisions=rail` or `lift`
on the page's address shows two other looks); pictures as one line of
thumbnails, each with a ribbon of its title, time and verdict along its foot,
and texts as one line of white previews of one height, their verdict at the
bottom right, both scrolling sideways; an item's options as one card, a small
list of them, each with a star (grey; the preferred one's filled in the foil,
a click prefers it or takes it back) and the title and time along its foot
(a text's on top); other files as rows. Hovered, a topic, a decision, a text
or a file row takes a soft wash of silver, yellow, orange and purple, which an
open topic's head and an open decision's keep. Accept all and Reject all close it. A picture or
a text opens in a viewer over the list, its title and time on a white
ribbon — a text in a column about 40% of the screen, a picture's viewer
shrunk to the picture, each picture framed in a grey hairline: a version
picked (a white pill on a foil edge, "v3", its list giving each
version's time; with one version, the label alone in the middle of its
pill), or Compare (off at first, and absent where there is nothing to
compare: one version, options, a file only to download) for two side by
side, the newest and the one before, each side's select on one line over
it at its left edge, the file's path beside the left one (a text's as
a line diff in nock's colours, the changed words marked, a long unchanged run
folded into one row a click unfolds); an item's options side
by side instead, each with its star, Compare off; a Markdown file
rendered (nested lists, ruled tables, code blocks black and highlighted),
its frontmatter the tinted top band of its page as keys and values, code and data
highlighted, plain text as it is; a click on the file's path says where it
comes from, in a bubble; a click on a picture zooms it over all the room the
viewer has (compared, each side its half; on a phone, stacked, each half the
height) at its natural size, or larger where that would leave the room
unfilled, the part shown following the cursor — every picture side by side
zooms and pans with it, to the same point, so two versions compare in
detail; a click or Esc leaves the
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

## Filters

Under the bar, **filters**, one at a time and combined with the search, each
with its count: All; **Needs me** (topics in review, open items, and chats the agent answered
since the owner looked); **Waiting on agent** (the owner wrote last, or
rejected an item still to rework); **Todo** (todo decisions); **Active**
(topics under way). Done and abandoned topics, and dropped items, stay hidden until **Show
closed** shows them. The choice is kept per browser. **Tidy up** is at the
right end of that line (see [Tidy up](#tidy-up)); on a phone the chips
scroll sideways beside it.

## Settings

The **settings** behind the gear hold, beside whether nock shares its usage
report, the recorder's transcription server: its address, model and the name
of the environment variable holding its key (never the key), saved to this
machine's `.nock/local/config.toml`, never committed.

`#topics/TOPIC` opens a topic, `#topics/TOPIC/SLUG` an item; `#170` the item
an earlier nock's decision 170 became.
