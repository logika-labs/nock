The owner of this project wants to share a reflection round's summary with
nock's makers{{ " — publicly, on nock.dev, where anyone can read it" if visibility == "public" else ", privately: only they will read it" }}.
You are a fresh session, here only to make sure the summary says nothing that
could tell anyone which project, company or people it comes from, and to
hand back the text to send. Nobody will answer you.

# The summary

```markdown
{{ text }}
```

# What to do

1. Learn what would identify this project. Read the README, the docs, the
   CLAUDE.md files and `git log --format='%an %ae' | sort -u`, and skim the
   code's top-level names: the project's and company's names, product and
   brand names, people (authors, customers, teammates), partners and
   vendors it integrates with, customers, domains, places, internal
   codenames.
2. Rewrite the summary so none of it remains, keeping everything else — what
   kind of project, how nock is used, the numbers about nock, what works,
   what does not, what should change. It must not contain:
   - a name of the project, the company, a product, a person, a partner, a
     vendor or a customer — say "a payments partner", "the owner", "a
     customer";
   - a path, a file, module, function, class, table or command name of the
     project's own (nock's commands and files are fine: `nock decide`,
     `.nock/`);
   - code, configuration, log lines, error messages quoted from the project;
   - addresses, links (other than nock.dev), email addresses, keys, tokens;
   - figures about the business — revenue, prices, customer or order counts —
     or anything else a competitor would want. Figures about nock and the
     work (sessions, decisions, rejections, tool calls) are what nock's
     makers need: keep them;
   - a description precise enough to point at one company: "a delivery
     marketplace's backend" is fine, "a bike-courier marketplace in a
     British city" is not.
3. Keep its shape and its voice; change only what needs changing, and do not
   add what the summary did not say. If nothing of it can be shared without
   saying who it is, answer only `NOTHING TO SHARE:` and why.
4. Change nothing in the repository.

Your last message is the text that will be sent, exactly — Markdown, with
nothing before or after it.
