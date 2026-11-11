# Changelog

## 1.1 (2026-11-11)

### Why this release exists

In the first weeks of real use by its author, three things went wrong. All three had
the same root: rules were kept as text in more than one place, and nothing checked
that a run had followed them.

- The owner decided a rule: never skip a channel to save time or usage. It was logged
  as a decision but never written into the manual or the run instructions. Over three
  days, four runs in a row skipped the spam folder, the chat list, the group moderation
  queues and a partner portal, and said so only deep inside the log. Once the rule was
  written where the run reads it, the next run read everything and found a real client
  request that had been sitting in spam for two days.
- The manual had a size limit. Because it was over the limit, new rules the owner had
  decided were left out of it.
- The manual and the short run instructions carried the same rules twice, so they
  could drift apart.

### What changed

- One home per rule. Each rule lives in exactly one file. Rules that always apply are
  in `MANUAL.md`. Rules about one person, client, sender or desk are in the new
  `rules_by_subject.md` and are looked up when that subject comes up. Rules for a
  channel stay in `channels.md`, and for a job in its file under `jobs/`.
- A decision that is a rule is not finished until it names the file that carries it.
  The auditor checks this.
- Every scheduled run ends with a small script, `tools/run_gate.py`. It lists every
  enabled channel the run did not read and accepts only a real reason: the tool was
  missing, the page would not load, permission was refused, the channel was not due
  yet, or it was partly read and the run says what remains. Its output is the first
  thing the owner sees in the run's message. "I chose to keep the run short" is not
  accepted.
- The manual no longer has a size limit that blocks a rule. A rule the owner decides
  is written at once; the auditor reports when the manual grows large.

### What it costs

In the author's installation the periodic run now reads about a quarter more text per
run, because it reads the always-rules in the manual as well as its order of steps.
An interactive session reads less than before.

### What is still open

- The check has been tried on recorded past runs and in tests, but at the time of
  this release it had not yet been through a live scheduled run.
- Marionette depends on the owner's computer being on. Runs missed while it is off
  are caught up later, but nothing reads the channels in the meantime.

### Updating an existing installation

Copy `marionette/templates/run_gate.py` to `tools/run_gate.py` in your Marionette
folder, create an empty `view/run_skips.tsv` and a `rules_by_subject.md`, and ask
Marionette in a session to bring your `MANUAL.md` in line with the 1.1 template. It
will show you the change before it makes it.

## 1.0 (2026-11-11)

First public release.
