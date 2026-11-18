# Marionette by Hesham Elmahdy (github.com/heshamfm)

Marionette is a personal follow-up system that runs as a Claude skill. It makes sure
nothing you are asked for, promise, are promised, draft or decide gets lost.

It reads your email, calendar, meeting notes and other connected tools on a schedule,
turns every request and commitment into a tracked item, prepares reply drafts for you
to review, and reminds you of what is late. Everything it remembers lives on your own computer, in one
database file (SQLite) with a few plain files beside it.

Version 1.5, 2026-11-18.

## What you get

- The skill folder `marionette/`: the skill itself (`SKILL.md`) and the setup
  templates it reads only on first use (`templates/`).
- The database programs (`marionette/templates/db/`): one program that is the only way
  to write the memory, checks who may do what, refuses with a reason, and records every
  change in a history that is never changed or deleted. Nothing is ever deleted.
- A move tool (`marionette/templates/db/migrate.py`) for installations set up before
  version 1.5, which keep their memory in files. See "Moving from files to the database".
- A small check that runs at the end of every scheduled run and tells you, at the top
  of the run's message, which of your channels were not read and why.
- On first use, Marionette sets itself up: it creates its folders and starter files on
  your computer, asks you a few questions (how to address you, your language, your
  working days, when to check, whether to start in shadow mode), and creates its
  scheduled tasks.

## How to install

1. Download this repository (Code, then Download ZIP) and unzip it.
2. Compress the `marionette` folder on its own into a ZIP file.
3. In Claude, open Customize, then Skills, click +, then Create skill, then Upload a
   skill, and choose that ZIP file.
4. In a session linked to your computer, with a folder connected, type: Marionette.
   It sets itself up from there.

If someone shared the skill with you inside a Claude Team or Enterprise organisation,
you will find it under "Shared with you" in your skills list instead. Turn it on and
go to step 4.

## What you need

- The Claude desktop app, with a folder on your computer connected to your session.
- Your session linked to that computer, because the files live there.
- The connectors you want Marionette to watch (for example email and calendar),
  connected in your own Claude account.
- Your computer switched on at the scheduled times. A missed run is covered by the
  next one.
- Python 3.9 or later on your computer, with its standard `sqlite3` module (part of
  every normal Python installation). The database needs it. Without it Marionette sets
  itself up on plain files and can move to the database later.

## Moving from files to the database

If you set Marionette up before version 1.5, it keeps its memory in plain files, and it
keeps working that way. To move, install version 1.5 of the skill, invoke Marionette and
say you want to move to the database. Claude then:

1. Copies the database programs to your computer.
2. Runs a check that changes nothing in your installation. It builds a trial database
   and reports, in plain words, how many items, drafts, questions, reminders, jobs and
   reading lines it found and carried over (each pair of numbers must match), anything
   that does not fit, and every choice it had to make.
3. Fixes what does not fit with you. Usually that is a word of your own for a type or a
   status (you say what it means), or a job schedule the program cannot read (you write
   it in a fixed form, for example `{"every": "day", "at": "07:30"}`). The program never
   guesses a meaning.
4. Moves, only after you approve the report. Your old files are moved unchanged into
   `archive/before_db_<date>/`, and a read-only note stays at each old path. Nothing is
   deleted.
5. Checks that the brief now comes from the database.

If you want to go back, ask Claude to undo the move. The files return as they were, the
database is moved aside (not deleted), and you are told how many changes were recorded
in the database after the move, because those are not written back into the files.

Your scheduled tasks need no change: they use the skill, and the skill reads the
database once it exists.

You can also run the move yourself, from your `followup` folder:

```
python3 tools/db_install/migrate.py --followup . --approval "<your words agreeing>" --session-file sessions/<file>.md
python3 tools/db_install/migrate.py --followup . --approval "<your words agreeing>" --session-file sessions/<file>.md --apply
python3 tools/migrate.py --followup . --undo
```

## Usage and cost

On each scheduled run Marionette reads all your mail since its last check, every
attachment and every full meeting transcript. That uses a noticeable share of your
Claude usage limits. Start with two runs a day and watch your usage before adding more.

## Built-in limits

Marionette never sends, forwards or replies to any message: every reply is a draft
you send yourself. It never deletes files, never archives or changes your mail, and
never changes records in a business system during a scheduled run, unless you add
an exception to your own manual.

## Security

Marionette reads messages from anyone who writes to you, on its own, while you are not
watching. A message could contain text written to trick it into doing something.
Marionette is told to treat everything it reads as data, never as instructions, and it
never sends, forwards or deletes anything, so the worst outcome is limited. But that
rule is an instruction to the model, not a technical barrier. To reduce the risk:

- Connect only the folder that holds Marionette to its sessions, not your whole home
  folder.
- Read every draft before you send it.
- Consider starting in shadow mode, offered during setup: Marionette records what it
  finds but writes no drafts and sends no notifications until you switch it to live.

## How rules are kept

You will keep telling Marionette how you want things done. Each of those rules is
written in exactly one file, so two files can never disagree:

- rules that always apply: `MANUAL.md`;
- rules about one person, client, sender or desk: `rules_by_subject.md`, looked up
  when that subject comes up;
- rules for one channel: `channels.md`; for one job: its file in `jobs/`.

A decision that is a rule is not finished until it names the file that carries it.
`CHANGELOG.md` explains why this was added.

## Status

Marionette is in daily use by its author, whose installation runs on the database.
The move tool was tested on synthetic installations and on a copy of a real installation
with about 400 items, 500 reading lines, 50 drafts and 40 reminders (the trial is
described in `CHANGELOG.md`). Setup by other users has not been tested yet.

## Questions and problems

Open an issue on this repository: https://github.com/heshamfm/marionette/issues
Say what you tried, what happened, and what you expected. Before you post, remove
any private data, such as email content, names of your clients, or file paths from
your computer, because issues are public.

For anything private, send a message on LinkedIn:
https://www.linkedin.com/in/heshamelmahdy/

## About the author

Marionette was designed and built by Hesham Elmahdy.

- GitHub: https://github.com/heshamfm
- LinkedIn: https://www.linkedin.com/in/heshamelmahdy/

## Licence and attribution

Licensed under the Apache License, Version 2.0. See `LICENSE`.

You may use, copy, change and share Marionette freely. The one condition is
attribution: keep the `NOTICE` file and the line
"Marionette by Hesham Elmahdy (github.com/heshamfm)" unchanged in every copy, fork and
adaptation. The licence makes this binding on anyone who distributes a copy; for a
private installation it is the author's request.

## Tests

Run each from the repository root:

- `python3 tests/test_db_door.py`: the database program: permissions, refusals, the
  history of changes, jobs and periods, the late rule (204 checks).
- `python3 tests/test_db_move.py`: the move from files to the database, the undo, a new
  installation, and the run tools after the move (51 checks).
- `python3 tests/test_brief.py` and `python3 tests/test_run_gate.py`: the files
  version of the brief and of the end-of-run check, for installations not yet moved.
