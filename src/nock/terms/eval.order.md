---
term: eval.order
aliases: [ordering, step-order]
description: Order steps so the expensive-to-vary ones come first
---

A snapshot is reused only while everything before it matches, and a fork multiplies what follows. So put the steps that are expensive and rarely change early (building a world, instrumenting a project) and the cheap or often-varied ones late (scoring, a parameter swept). Reading a parameter late keeps everything before it shared.
