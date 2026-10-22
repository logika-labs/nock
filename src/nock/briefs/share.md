The owner wants to share this reflection summary with nock's makers{{ ", publicly on nock.dev" if visibility == "public" else ", privately" }}.
Make sure nothing in it tells which project, company or people it comes from,
and hand back the text to send. Change nothing in the repository.

Learn what identifies the project: the README, docs, CLAUDE.md,
`git log --format='%an %ae' | sort -u`, the code's top-level names. Then
rewrite the summary without:
- names of the project, company, products, people, partners, vendors or
  customers (say "a payments partner", "the owner");
- the project's own paths, files and code names (nock's are fine);
- quoted code, configuration or logs; addresses, links, keys;
- business figures (revenue, prices, customer counts), or a description that
  points at one company.

Keep the numbers about nock and the work, the shape and the voice, and add
nothing. If nothing can be shared, answer only `NOTHING TO SHARE:` and why.
Your last message is sent exactly as written.

```markdown
{{ text }}
```
