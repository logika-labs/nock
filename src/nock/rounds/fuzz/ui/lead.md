# The UI fuzz round

You drive the project's web UI the way careless, hurried and unusual users
would, and report what breaks. You change no code. The material `earlier` is
what earlier rounds found: don't report it again as new, but say in the
report which of its findings still reproduce.

1. **Run it locally.** Start the UI and the API it calls against the
   project's dev stack, on ports of your own, with seeded data (the project's
   docs or toolbox say how). Never send traffic to production. Load the
   skill or docs for each area you touch first.
2. **Map it.** List every page, route, dialog, menu and form from the router
   and the code, and the states each can take: empty, loading, error,
   long lists, permissions, plan limits. Where the project keeps a catalogue
   of states or fixtures, use it to reach the ones live data can't, and mock
   the API only for those.
3. **Drive it.** With headless Playwright, a script you keep in the
   round's scratch: visit every page and open every dialog, at 390, 768 and
   1440 px wide, in light and dark. Put into every input: empty, whitespace,
   10,000 characters, Unicode, RTL text, emoji, `<b>x</b>` and
   `<script>alert(1)</script>`, `' OR 1=1 --`, negative, zero and huge
   numbers, past and far-future dates. Submit twice fast, go back mid-request,
   reload on each step. Collect console errors, failed requests, page errors,
   and axe-core's violations on each page. On a large UI, split the pages
   among subagents, each with these steps and its share.
4. **Judge.** A finding is a layout break, overflow or clipped text, a
   console or page error, a crash or blank screen, an API error shown raw or
   not at all, an accessibility violation, or a state that leaves the user
   unsure what happened or what to do. Reproduce each once more before you
   keep it; group the same cause seen on many pages into one finding.
5. **Write each finding** in `report.md`, ranked by severity: its title
   the fix you propose; the problem with `file:line`, its severity (high:
   users lose work or are blocked; medium: wrong or confusing; low:
   cosmetic) and how sure you are; what the fix takes; and its evidence: a
   screenshot in the round's scratch directory with the case and the
   script call that makes it again, the console log or repro file where
   they say more. Then what you covered and what you could not reach.
6. **Submit** the round with one change per finding, its kind one of the
   end's.
7. **Report** the round in your final message, to the session that ran it:
   the findings by severity, a line each, what needs the owner, and where
   `report.md` and the screenshots are.
