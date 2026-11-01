# Privacy policy

Last updated: 1 November 2026

This policy explains what personal data reaches nock's makers when you visit nock.dev or use nock, the open-source tool. nock is made by Parallel Labs, S.L. ("we", "us"), a Spanish company, NIF B05585526, Calle Calabria 171, 5º-3ª, 08015 Barcelona, Spain, which is the controller for what this policy covers. Contact: [support@logika.host](mailto:support@logika.host). It follows the EU General Data Protection Regulation (GDPR) and Spain's Organic Law 3/2018 (LOPDGDD).

## 1. In short

nock runs on your computer, and what it records about your project stays there, in your repository. We receive two things, and only these:

- **A weekly anonymous usage report**, unless you turn it off: counts and categories only, under a random project id.
- **A reflection round's summary**, only when you choose to send one, after seeing exactly what would be sent.

The website sets no cookies and runs no analytics.

## 2. The website

nock.dev is a static site. It sets no cookies, keeps nothing in your browser and runs no analytics. Two companies receive your IP address and browser details when you open it, as part of delivering it:

- **GitHub, Inc.** (GitHub Pages), which hosts the site, in the United States;
- **Google LLC** (Google Fonts), which serves the site's fonts, in the United States.

Each keeps its own server logs under its own privacy statement. Both transfers rely on the EU–US Data Privacy Framework.

## 3. The usage report

While `share = true` in `.nock/config.toml` (the default), nock sends a usage report from your machine once a week to `api.nock.dev`. Nothing is sent until you have been told, once, the first time you engage with nock on that machine (your first reflection round, opening `nock studio`, or your first review of a decision).

A report holds:

- nock's version, Python's version and your platform (`darwin`, `linux`);
- whether reminders and the consultant are on, and whether the project uses Logika;
- counts over the week: sessions, requests, tool calls and failures, tokens, cost, commits, decisions by status, nock's own commands by how they ended, how many tools, checks and hooks the project has, and how many reflection rounds ran;
- the project's anonymous id: a random UUID, made when the first report is sent and kept in `.nock/project.json`, derived from nothing about you or the project.

It never holds code, file paths, file or tool names, prompts, command arguments, what your decisions say, or anything else written in your project. `nock usage` shows exactly what the next report would carry.

We use reports to learn how nock is used and to improve it, on the basis of our legitimate interest in improving nock (GDPR Art. 6(1)(f)). The reports identify no person. Set `share = false` (for the project in `.nock/config.toml`, or for one machine in `.nock/local/config.toml`) and nothing is ever sent.

## 4. Reflection summaries

A reflection round writes a summary of how nock is doing in your project. It leaves your machine only if you run `nock share`, review the text it shows you, and confirm. Before showing it, nock has an agent remove anything that could identify the project, its people, partners or customers. Read it before you confirm: if it still contains personal data, that data reaches us. We use summaries to improve nock, under the same legitimate interest, and never publish them.

## 5. What reaches our server, and what it keeps

`api.nock.dev` keeps each report or summary with the time it arrived, and nothing about the sender: no IP address and no request headers. Our server sees your IP address for each request, uses it to limit how often one address may send, and keeps it in its ordinary access logs for up to 30 days, for security. The server is in the European Union (Scaleway, France).

| What | Kept for |
|---|---|
| Usage reports | up to 3 years |
| Reflection summaries | up to 3 years |
| Server access logs | up to 30 days |

## 6. What nock does on your machine

nock's agents run under your own Claude Code (or other coding agent) account, on your machine, under your own agreement with its provider. What they read and send goes to that provider, not to us. When nock works with Logika (`nock reflect logika`), it reads your Logika project through your own `logika` CLI; that is covered by [Logika's privacy policy](https://logika.host/privacy), and nothing of it reaches nock's makers beyond the usage report above.

## 7. Your rights

You may ask us for access to, correction or erasure of personal data we hold about you, to restrict or object to its processing, or to receive it in a portable form, by writing to [support@logika.host](mailto:support@logika.host). Reports carry no identifier we can link to you, so to find yours, include your project's anonymous id from `.nock/project.json`. We answer within a month. You may complain to the Spanish data protection authority (AEPD, aepd.es) or the authority where you live.

## 8. Changes

We will say on this page when it changes, and update the date above. nock is not directed at children.
