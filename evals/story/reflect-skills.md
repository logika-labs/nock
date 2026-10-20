You are reflecting on a week of work on this repository, so that the work
ahead goes better. The engineers working here — you, in other sessions — get
reports (alerts, complaints, questions about the data, features, operational
chores) and resolve them in this repository. This week's sessions are
recorded as Claude Code transcripts (JSON lines, one per session):

{{ transcripts }}

Read them. What did the sessions spend their turns on? What did they have to
find out the hard way, what did they get wrong, what did they look up again
and again, what would have saved them time? Read the code and the history
where they point.

Then improve what the next session starts with: `CLAUDE.md` at the
repository root, which every session reads, and skills in `.claude/skills/`
(each a directory with a `SKILL.md`: a front matter `name` and `description`,
saying when to use it, then the instructions; scripts beside it if a skill
needs them). Write down what the next engineer needs and would not find
quickly: how the system is laid out and where things really are, how to
investigate each kind of trouble that keeps coming back, the business's
semantics and the decisions the owner made, the traps. Keep it short enough
to be read: remove what turned out to be wrong or no longer true.

Change only `CLAUDE.md` and `.claude/`, commit them, and say in a few lines
what you changed and why.
