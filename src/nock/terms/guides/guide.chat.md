---
term: guide.chat
aliases: [guide.chatting, guide.threads]
description: Every word goes through a chat: a topic's, a decision's, a file's; how the two sides talk
---

# Chatting

Every word goes through a chat — a topic's, a decision's, a file's — opened
by its icon beside the time, even on a closed topic (which it opens), and
floating over what is under it from the icon, which stays put: the agent's
messages on one side, the owner's
on the other. The owner's message waits for the agent's answer, the item
"pending" meanwhile: the chat takes nothing more until it comes, and the
owner can withdraw the message to edit it; a verdict given since overrides
it. An agent's `--reply` while one waits is its answer (the command says
`answered`); it may say more afterwards. The icon marks what the agent said
since the owner last opened the chat (kept on the machine) with a glowing
foil dot; while the owner's message waits for its answer, the icon's outline
swirls slowly in the foil's colours (still, for reduced motion). A long
message grows the field to a limit, then scrolls inside it. Verdicts take no
comment on the page.

**The threads are where the two sides talk.** `--reply "markdown"` on
`topics update` or `items update` adds a message; while the owner's last
message waits, it is that message's one answer. When the owner is in the
session, the agent discusses with them there and leaves at most a line in
the thread; when they are away, or told it to work in the background, it
answers briefly in the thread, and says nothing if it just did what was
asked and the new version shows it.
