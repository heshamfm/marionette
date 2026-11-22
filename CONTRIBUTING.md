# Contributing to Marionette

Thank you for helping. Marionette keeps other people's commitments, so every change is held to
four rules.

1. **A change starts from a real problem.** Say what went wrong, for whom and when, and what you
   found, quoting the source (a log line, the brief, a test). The issue template asks for exactly
   that.
2. **Fix the class, not the case.** Before proposing a fix, look for the other places the same
   kind of problem can happen (other actions, other channels, other messages) and fix them in the
   same change.
3. **Every installation already in use gets the fix.** A change to the programs or the data ships
   with what `marionette/templates/db/upgrade.py` needs to bring an existing installation up to it:
   the hashes of the files the previous release published, in `PUBLISHED` (a file cannot hold its
   own hash), the new release in `RELEASES`, a data step if
   old data must be repaired, and the rules it proposes for the owner's manual in
   `templates/db/upgrades/<release>.md`. The owner's manual is never written by a program.
4. **Tested, and nothing of one user in the programs.** Add checks to the tests; run them all
   (see README, Tests). No name, company, channel or place of any one user goes into the skill or
   the programs.

Every release has a `CHANGELOG.md` entry that says why it exists, what changed, and how an
installation already in use is upgraded.

Keep the line "Marionette by Hesham Elmahdy (github.com/heshamfm)" and the `NOTICE` file unchanged
(see `LICENSE`).
