# Marionette by Hesham Elmahdy (github.com/heshamfm)

Marionette is a personal follow-up system that runs as a Claude skill. It makes sure
nothing you are asked for, promise, are promised, draft or decide gets lost.

It reads your email, calendar, meeting notes and other connected tools on a schedule,
turns every request and commitment into a tracked item, prepares reply drafts for you
to review, and reminds you of what is late. Everything it remembers lives in plain
files on your own computer.

Version 1.2, 2026-11-13.

## What you get

- The skill folder `marionette/`: the skill itself (`SKILL.md`) and the setup
  templates it reads only on first use (`templates/`).
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
- Python 3.9 or later on your computer, for the small script that lists what is late.
  Without it Marionette still works, but reads more on every run.

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

Marionette is in daily use by its author. Setup by other users has not been tested
yet.

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

`python3 tests/test_brief.py` checks the late rule in `marionette/templates/brief.py`.
`python3 tests/test_run_gate.py` checks the end-of-run check in
`marionette/templates/run_gate.py`.
