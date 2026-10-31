---
term: eval.outcomes
aliases: [outcome, metric, metrics]
description: Measure the outcome, not a proxy; one detection counts one bug
---

Score what the owner wants, not what is easy to count: a bug fixed and staying fixed, not a test touched. One detection counts one bug, however many alarms it raised; false alarms are counted on the clean twin (`bug=none`). Put each number in the results of the step that can judge it, so `eval compare` can read it.
