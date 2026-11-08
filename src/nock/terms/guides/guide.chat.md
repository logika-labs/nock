---
term: guide.chat
aliases: [guide.chatting, guide.threads]
description: Every word goes through a chat: how the two sides talk, with files and voice
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
asked and the new version shows it. The owner's message may carry files
(dropped into the chat on the page): it lists each as `attachments`, with
its name, type, size in `bytes` and `path`; `items show`, `topics show`, the
`awaiting_you` summary (`attachments`, the paths by thread) and the prompt
hook give each one's absolute path (`where`), for the agent to read.

## Files and voice

Files dropped on
a chat (or pasted into its field, or picked with its clip) go up at once and
wait in the composer as chips, each removable, until the message goes with
them (a message of files alone is fine); in the thread a message shows its
pictures as thumbnails that open enlarged, zooming like the viewer's, and
its other files as chips that open or download. A withdrawn message's files
come back to the composer. The files are kept beside the thread (see
[Topics and items](#who-wrote-it-and-where-it-is-kept)).

The microphone beside the field records (the
browser asks for the microphone once; 127.0.0.1 counts as secure): a pulsing
foil dot and the time while it records, a click to stop, a spinner while the
studio has the recording made text by the Whisper server
`studio.transcribe_url` names, and the text lands where the cursor was, to
edit and send; it is never sent by itself. A failed transcription says why,
the recording kept to try again. Without a URL the microphone stays, faded,
saying how to set one (see [Settings](#settings)).
