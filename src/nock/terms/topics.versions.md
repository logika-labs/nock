---
term: topics.versions
aliases: [update, version, rework, compare, delete]
description: Changing an item: in place while open, a new version once decided
---

`.nock/nock items update REF '{…}'` changes an open item in place (title, decision, files). `--version '{…}'` adds a version, carrying over what it leaves out and copying project files again as they are now, and reopens a decided item: rework a rejected one so. An accepted or rejected item changes only by a version. `items delete REF`: only an open item the owner hasn't written on.
