# Audits — the convention

Independent reviews of this system live here, one file per audit, never edited
after they are written.

## Where things are written, and by whom

| file | written by | rule |
|---|---|---|
| `designs/audits/YYYY-MM-DD-<slug>.md` | **the auditor only** | one file per audit run. Append-only within a run; never revised afterwards |
| `designs/TODO.md` | **the builder only** | the single status board. Absorbs audit findings *with attribution* after verification |
| `designs/HANDOFF.md` | **the builder only** | the builder's running work log |
| `src/`, `config/`, `tests/` | **the builder only** | the auditor does not change behaviour |

The two roles share one branch, `audit-full-system-architecture`. That works
only because they touch disjoint files — `TODO.md` and `HANDOFF.md` are
append-heavy and will conflict on every push if both write them. **An auditor
that needs something recorded on the board writes it in its own audit file and
lets the builder reconcile it.**

Scratch scripts belong in the session scratchpad, not in the repo.

## Why audits are never edited

They are dated primary sources. Editing one destroys the record of what was
believed, and when. When an audit is superseded, `TODO.md` says so and cites it;
the audit itself stays as written — including the parts that turned out to be
wrong, which are the most useful parts for calibrating the next one.

The two existing audits, `first-principles-claim-note-audit.md` (agent A) and
`full-system-architecture-audit.md` (agent B), follow this rule. Between them
they found six real defects the builder had missed, three in code written the
same day. Two of agent B's eight claims the builder rated differently, with
reasoning recorded on the board. **That ratio — six confirmed, two contested —
is what a healthy audit looks like.** An audit where everything is confirmed was
probably reading the builder's notes rather than the code.

## The one rule that matters most

**Read the code and the measurements before reading `HANDOFF.md` or `TODO.md`.**

Those two files are the builder's account of what is true. An auditor primed by
them finds gaps *inside the builder's frame*, which are the cheap ones. What
made agents A and B valuable is that they read the source. Read the builder's
notes last, to check whether a finding was already known — not first, to learn
where to look.
