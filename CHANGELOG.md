# Changelog

## 1.3 (2026-11-13)

### Why this release exists

A reader asked in public: what happens to the original task when the promise changes in
a later meeting? The intended answer was "the record is updated". A review of the
published text showed that nothing guaranteed it:

- An item's key comes from its source. A later meeting is a new source, so a run could
  open a second item for the same promise, and the first one would then show as late
  against a date that no longer applied.
- Only Story lines were protected from being overwritten. Nothing said the old wording
  must be written down before the item was changed.
- Nothing said what to do when it is unclear whether the new terms replace the old
  promise or add a second one.

### What changed

- A promise that changes belongs to the item that already carries it, whatever source
  the change came from. No second item is opened.
- The change is written first as a Story line with both versions, the source and the
  date. Only then are "Needed", the title and the deadline updated. The old version
  always survives.
- When it is not certain that it is the same promise, nothing is merged or overwritten:
  both items stay open and the owner gets one question that states both in full.
- The auditor lists open items with the same counterparty and an overlapping subject,
  and raises each pair as a question with a proposal to merge. It never merges.

To update an existing installation: replace the skill, and add the paragraph "A promise
that changes" (section 3) and the auditor's new check (section 6) from
templates/setup.md to your MANUAL.md.

## 1.2 (2026-11-13)

### Why this release exists

A paid survey invitation with a same-day bonus reached the author's mailbox. A scheduled
run read the message in full, labelled it, marked it read, archived it, and told the
owner nothing. The reminder the next day went the same way. The owner found out two days
later, when he asked why nothing had come of it.

Two things had gone wrong, and neither was a reading problem:

- A quick housekeeping step archived that kind of mail first and was told to stay
  "light", so the part of the rule that said "report what needs the owner" was never
  reached. Reading a message is not handling it.
- When the owner sent his reply to the invitation, no item was opened to wait for the
  answer. So when the answer came, nothing connected it to an open matter.

A check of the inbox the same week found three more messages that runs had read and
never tied to anything.

### What changed

- Everything is tied to something. Whatever a run reads ends with one line in
  data/disposition.tsv: linked to an item, or ignored for a reason from a short closed
  list. What has neither is shown to the owner in every message until it is classified.
- Record first, archive last. Nothing is marked read, labelled or archived before its
  disposition is written.
- Money, a deadline, a paid invitation, a client message, a security alert or a needed
  decision always becomes an item in the same run and is named in that run's message
  with its deadline. A deadline before the next scheduled run is sent at once.
- A draft the owner sends that expects an answer keeps an item open as waiting on others.
- Every open item carries a deadline or a next_check date.
- The end-of-run check (templates/run_gate.py) now lists what was read and not
  classified, rejects invalid dispositions, and names open items with no date.
- The auditor samples the ignored lines and reads them in full.

To update an existing installation: replace the skill, copy templates/run_gate.py to
tools/run_gate.py, create data/disposition.tsv with the header line from
templates/setup.md, and add the paragraphs "Everything is tied to something" (section 1)
and "Dispositions" (section 3) from templates/setup.md to your MANUAL.md.

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
