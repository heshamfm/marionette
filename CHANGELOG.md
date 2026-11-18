# Changelog

## 1.5 (2026-11-18)

### Why this release exists

Version 1.4 was incomplete, and should not have been published as it was. It taught the
skill how to behave when an installation keeps its memory in a database, but it did not
include the database program, and it offered no way to move an existing installation to
it. Its changelog said so in one line, but that was not enough: anyone reading "adds
installations that keep their memory in a database" would expect to be able to use one.
Nobody outside the author's own installation could. This release ships what 1.4
promised.

### What changed

- The database programs are now in `marionette/templates/db/`:
  - `mdb.py`, the only program that writes the memory. It checks who may do each action
    (the owner, Claude or the program), refuses with a reason, records every change in a
    history that cannot be changed or deleted, and never deletes anything. An action in
    the owner's name needs the owner's own words, quoted from a session.
  - `mrun.py`, what every run and session uses: the brief, the status page, the
    end-of-run check, and one command for each thing a run records.
  - `schema_v0.1.sql` and `seed_v0.1.py`: the tables, the types of things and the
    permission rules.
  - `db_usage.md`: for each step the files version did by editing a file, the command
    that does it now.
  - `doors/`: `brief.py`, `run_gate.py` and `build_status.py` keep their names and
    commands, and read the database.
  - `migrate.py`: the move from files to the database.
- The owner's settings are no longer fixed in the programs: time zone, working days,
  the first day of the week (used for weekly jobs) and the language of the brief, status
  page and end-of-run check (English or Arabic) come from `state.json` when the database
  is created.
- Setup creates new installations on the database (step 4b). If Python 3.9 or later
  with `sqlite3` is missing, it stays on files and can move later.
- The move has two steps. The check changes nothing in the installation and reports
  what it found and carried over, what does not fit, and every choice it made. The apply
  runs only after the owner approves, refuses while a run holds the lock or while
  anything does not fit, moves the old files unchanged into `archive/before_db_<date>/`,
  and leaves a read-only note at each old path. `--undo` puts the files back; nothing
  is deleted in either direction.
- The move never guesses: a type or status in the owner's own words is given its
  meaning with `--map`, and a job schedule it cannot read must be rewritten in a fixed
  form. Choices it does make (for example, a reminder with no date becomes due at the
  moment of the move, so it is shown at once, as before) are listed in the report.
- Two new tests: `tests/test_db_door.py` and `tests/test_db_move.py`.
- Files that a test run had created by mistake (`__pycache__`) were removed from the
  repository, and a `.gitignore` keeps them out.

### How it was tested

- The 204 checks of the database program, and 51 checks of the move: a check that
  changes nothing, an apply, an undo and a second move, the refusals, a new Arabic
  installation with a Sunday-to-Thursday week, and the brief, status page and
  end-of-run check after the move.
- A check, apply and undo on a copy of the author's own installation from before its
  move: 393 items, 524 reading lines, 48 drafts, 42 reminders, 8 questions and 11 jobs.
  Every item, draft, question and reminder was carried over. The trial found two faults,
  both fixed before release: the same email thread listed twice in the reading register
  was refused the second time (it is now recorded once), and a loose reading of job
  schedules read "Sun-Thu 07:30" as a weekly job on Thursday (schedules are now read
  strictly, and anything else is reported, not guessed).

### What did not change

The rules: what becomes an item, the late rule, the closed list of reasons to ignore
something, the limits on sending and deleting. Installations that have not moved keep
working on files exactly as before.

## 1.4 (2026-11-18)

### Why this release exists

The owner's own installation moved its memory from plain files to a single database
file, with one program that every run and session must write through. The skill still
described only the files. A session that followed the skill to the letter would have
tried to write an item, a draft or a question into files that are now read-only, and
what was agreed in that session would not have been saved.

### What changed

- A new short section, "Where the memory is kept". An installation keeps its memory in
  plain files (still the default that Setup creates) or in a database.
- When the installation holds `tools/db_usage.md`, the memory is the database that file
  names, and every read and write goes through the program it names. The old files
  (items, index, drafts, questions, reminders, the reading register, and the watermarks
  and lock in `state.json`) become read-only history.
- Wherever the skill names one of those files, the same step is done through the
  database instead. If the program refuses an action, its reason is followed; nothing
  is written around it.

### What did not change

Installations that keep their memory in files work exactly as before. Setup still
creates files. The database program itself is not part of this repository.

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
