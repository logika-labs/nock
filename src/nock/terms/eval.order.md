---
term: eval.order
aliases: [ordering, step-order]
description: Order rules so the expensive-to-vary ones come first
---

An output is reused only while everything before it matches, and a fork multiplies what follows. So put the rules that are expensive and rarely change early (building a world, instrumenting a project) and the cheap or often-varied ones late (scoring, a wildcard swept). A wildcard first used late keeps every output before it shared.
