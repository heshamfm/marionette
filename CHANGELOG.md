# Changelog

## 1.7 (2026-11-22)

### Why this release exists

Four problems were found in the author's installation on 21 and 22 November 2026. Three of them
can happen in any installation, and one more problem sat behind all of them: until now a fix
reached only new installations. Every earlier "Upgrading" note asked the owner to copy files by
hand, and none could repair data the old programs had left wrong.

1. **An item handed over still looked like the owner's.** The owner sent a contract to a colleague
   for review, and the run recorded the hand-over. Two days later the run's message listed the same
   contract under "waiting for you, due today". The hand-over had changed only who holds the next
   step: the title still said "asks you to review", the type still read "reply needed from me", and
   the old date stayed. The message was built from the date, not from who holds the step.
2. **Checks that came were never done.** Of 138 open items, 84 had a next check in the past, most
   of them five days old, and 12 had no date at all. Every brief marked them "CHECK DUE", but no
   step said what a run does then, so nothing happened, and items waiting on other people were
   never chased.
3. **A problem reported was saved in a shorter text than the one shown.** The owner asked a session
   to report two problems to the auditor. The session saved a short description and showed the
   owner a much longer text "ready to copy". Nothing made the saved text complete, nothing let a
   session add to an issue, and nothing said that what the owner is shown as saved must be what is
   saved. The issues register itself existed only in the author's installation.
4. **A rule was carried out with a condition its owner never stated.** (Specific to the author's
   rules, so not published as a rule; the general lesson is.) A spam rule was implemented with an
   extra precondition the owner had not said, and a real case slipped through it.

### What changed

- **Upgrade for installations already in use** (`templates/db/upgrade.py`, new). `--check` reports,
  file by file, what would change and changes nothing. `--apply` copies the database and programs
  first into `archive/upgrade_<from>_to_<to>_<time>/`, replaces only the program files that are
  exactly a published copy (a file the owner changed is kept, and the new one put beside it as
  `<name>.new-<release>`; if one of the core programs that only work together was changed, it changes
  nothing and the owner decides), adds new types and permission lines without removing or changing any,
  applies the data fixes of each release in order through the database program (so each one is in
  the history of changes), and records the release in the database (`meta marionette_version`),
  `state.json` and `runs.log`. `--undo` puts everything back and moves the upgraded database aside.
  It refuses while another run is writing (`--run R` names the caller's own run). If it stops half way,
  it says so, and `--undo` puts back the copy taken before it. The skill runs it at the start of any session or run that
  finds an older installation, and tells the owner what changed and how to undo it.
  `mrun.py version` prints the release.
- **Hand-over** (`mdb.py`): handing an item over now requires its new title (written for the new
  holder) and its dates in the same action. "Reply needed" and "decision needed" name the holder
  when it is not the owner. The brief has a section ON THE USER, the only list a message may show
  as waiting for the owner. The status page says who holds each late item. Items can be renamed
  (`act --action rename`) with the source that changed the title.
- **Dates and checks due** (`mdb.py`, `mrun.py`): an open item can no longer lose its last date, and a
  conversion or a reopening cannot leave one without a date.
  The brief lists every check that came (CHECKS DUE). The end-of-run check now names, as a
  violation, every check the run left unhandled (handled = anything the run recorded on the item) and
  every open item with no date. A story line is now written to the history of changes with its run,
  like every other change. The move from
  files gives undated items a next check on the day after the move, and the upgrade does the same
  for existing databases.
- **Issues register** (`mrun.py`, `seed_v0.1.py`): a new type, issue (reported, in progress,
  resolved), for problems in how Marionette itself works. `issue-new` takes the parts of one fixed
  template (what happened; what was found, quoting the sources; the owner's words, required when
  the owner reported it; what is asked) and builds the text itself, always adding the step "find
  the similar cases and fix them all"; it refuses a missing part. `issue-append` adds text word for
  word; `issue` prints an issue exactly as stored; `issues` lists them; the brief shows the open ones.
- **The undo of the move from files** counts the changes made after the move by the last change of
  the move, not by time: two changes in the same second were missed.
- **A source read in part can be read in full later** (`mrun.py record --read`): fixed earlier in
  the author's installation and not published until now.
- **Rules** (`SKILL.md`, `templates/setup.md` for new installations, `templates/db/upgrades/1.7.md`
  proposed to existing owners): who holds the next step decides what waits for the owner; a
  hand-over rewrites the item; every check that comes is handled that day; what the owner is shown
  as saved is printed from where it is saved; problems go to the issues register in its template;
  a rule is carried out in the owner's words, with no condition added.
- **Project**: tests for all of the above, including an upgrade of a real 1.6 installation rebuilt
  from this repository's history (`tests/test_release_1_7.py`); the tests run on every push on
  Python 3.9 to 3.13; `CONTRIBUTING.md`; an issue template.

### Upgrading

Replace the skill folder with this one. The next session or scheduled run finds the installation
older than 1.7 and upgrades it as described above, then shows the owner the rules proposed for the
manual. Nothing is lost: everything is copied first, and `upgrade.py --undo` goes back. An
installation still on files is not touched; it moves to the database as before, and the move now
includes these changes.

## 1.6 (2026-11-20)

### Why this release exists

Two problems happened in the author's own installation after 1.5 was published, and both
can happen in any installation.

1. Two sessions drafted the same meeting follow-up 4 minutes apart. Each one checked for
   an existing draft, found none, and created its own. A check before creating a draft is
   not enough when two sessions check at the same moment.
2. A scheduled run left a channel unread and gave "not enough time" as its reason. The
   end-of-run check accepted it, because the reason code looked valid. A channel that is
   left unread to save time is exactly the kind of gap Marionette exists to prevent.

### What changed

- `SKILL.md`: before creating any mail draft, the session checks existing drafts (whoever
  made them), sent mail, the thread and the inbox for the same purpose. Right after
  creating a draft, it lists the drafts again; if another draft for the same purpose has
  an earlier draft id, it discards its own new draft at once and says so. The check after
  creating is what leaves only one draft.
- `templates/db/mrun.py`: `skip` refuses any reason that rests on time, length or
  consumption (in English or Arabic). A run may leave a channel unread only for a real
  reason: the tool is missing, the page did not open, permission was refused, the channel
  is not due yet, or it was read in part with what remains named.

### Upgrading

Replace the skill folder with this one. For an installation already on the database, copy
`marionette/templates/db/mrun.py` over `followup/tools/mrun.py`. Nothing else changes and
nothing in the database is touched.

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
