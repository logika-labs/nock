---
term: topics.search
aliases: [list, show, search]
description: Finding topics and items: list, query, show
---

`.nock/nock topics list` and `items list [TOPIC]`: a summary first (open items by topic, what waits on you), then the list cut short; `--full` the whole list, no summary. `--query "words"` ranks by plain full text: names, descriptions, titles, decisions, threads, file paths, `when`. `topics show TOPIC`, `items show REF` (every version, each file's path, the thread); an earlier decision's number works as a ref.
