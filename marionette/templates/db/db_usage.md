# The Marionette database: how runs, jobs and sessions read and write it

Marionette by Hesham Elmahdy (github.com/heshamfm), version 1.5. This file is the home of every rule on HOW to read
and write the database. What to do and when stays in MANUAL.md, channels.md and jobs/. When this file exists in
tools/, the memory is the database: the marionette skill sends every read and every write here.

## Where it is
- The database: db/marionette.db, one SQLite file in the followup folder. Never open it with another program to
  write, never copy it while a run is writing, and never keep it in a folder that Google Drive, iCloud, OneDrive or
  Dropbox synchronises (a synchronised copy of a database being written can be damaged).
- The programs, in tools/: mdb.py (the door: the only program that writes), mrun.py (what every run and session
  uses), schema_v0.1.sql and seed_v0.1.py (read by the door), migrate.py (the move from files, already done).
- Run them from the followup folder: python3 tools/mrun.py <command>. Output is JSON, except brief, status and gate,
  which print text in the owner's language. A refusal prints {"refused": "..."} and exit code 2: nothing was
  written. Read the reason and act on it; never work around a refusal by another route.
- The old memory files (index.tsv, items/, drafts.tsv, data/drafts/, questions.md, reminders/, data/disposition.tsv)
  were moved, unchanged, into archive/before_db_<date>/. Each old path holds a read-only placeholder that points
  here. Never write there and never recreate them. The old content is history: search it only when a question needs
  what happened before the move.

## One rule above all
Every write goes through mrun.py, which calls the door. Never write the database with SQL and never edit it by hand.
The door checks who may do each action (Claude, the owner, the program), refuses with a reason, and writes every
change to an audit trail that is never changed or deleted. Nothing is ever deleted: a thing is closed or cancelled.
An action in the owner's name (postpone, cancel, mark a "for information" item seen, a reminder the owner asked for,
create a channel or a job) needs the owner's own words quoted from the session: record the session first
(record --channel "Claude sessions" --type session --external-id sessions/<file>.md), then pass its number as
--session or --source, with --quote "<the owner's words>".

## Words
- Item types: commitment (a promise; --promised-by me for the owner's own, or the other party for theirs),
  reply_needed (someone waits for the owner's reply; --requested-by), decision_needed, for_info.
- "Open" means the next step is the owner's: holder = me. "Waiting on others" means the next step is another
  party's: holder = that party. A deadline written in words and not as a date counts as no deadline.
- WHO is "me", a party number, or the email address of a recorded party.

## File action → command
| What the files version did | What to do now |
|---|---|
| the lock in state.json | python3 tools/mrun.py run-start --kind schedule (prints the run number R; refused with "locked" while another run wrote in the last 30 minutes: wait 2 minutes, retry up to 3 times, then log and stop). At the end, also after a failure: run-end --run R (add --failed on failure). |
| python3 tools/brief.py | the same command still works; it calls mrun.py brief (add --full-questions when needed) |
| grep index.tsv / read items/<key>.md | mrun.py find "<name, company, domain or words>", then mrun.py item <number or old key> |
| a line in data/disposition.tsv for each thread, event, meeting, chat or file | record --run R --channel <channel> --type message/calendar_event/meeting/external_record/published_content --external-id <its id in the channel> --title "<sender, subject>" --date <date> --details '{"sender": "...", "direction": "incoming"}' as soon as it is listed; after reading it in full, the same command with --read full (or --read partial/failed --reason "<what is left and why>") |
| filling the disposition | verdict --run R --source S --verdict linked (after an item quotes it or links it), informed (after a for_info item quotes it), or ignored --reason "<code>: <one sentence>" (the codes are the closed list in MANUAL.md section 3) |
| a new item in index.tsv and items/ | new-item --run R --type commitment/reply_needed/decision_needed/for_info --title "..." --holder me/<who> [--promised-by WHO] [--requested-by WHO] --due YYYY-MM-DD[ HH:MM] and/or --next-check YYYY-MM-DD --details '{"text" / "request" / "question" / "what_happened" + "why_it_matters": "..."}' --source S --quote "<the exact sentence>". A person or company not yet recorded: party --run R --name "..." --email ... --source S --quote "..." first. Values you inferred: --inferred holder,due |
| a story line "- YYYY-MM-DD HH:MM \| text" | story --run R --item I --source S --quote "<exact sentence>" |
| changing status, holder, deadline or next check | act --run R --item I --action complete (--params '{"close_reason": "done"/"not_needed"/"handed_over"}'), hand_over (--params '{"holder": <party>}'), change_due, set_next_check, reopen, merge or link, each with --source S --quote "..." |
| a row in drafts.tsv and data/drafts/<id>.txt | right after the draft is created in the mail tool: draft --run R --item I --channel <channel> --kind reply/forward/new --replies-to <message id> --recipients '["..."]' [--cc '[...]'] --subject "..." --text-file <a file holding the full text> --mail-draft-id <the draft id in the mail tool>. The door refuses a second waiting draft for the same item |
| the fate of a draft | act --run R --item <draft> --action mark_sent_as_is, or mark_sent_edited --params '{"sent_text": "<the full sent text>"}', or abandon --params '{"reason": "..."}' |
| a question in questions.md | ask --run R --question "<the full question, options and recommendation>" --about I --source S --quote "..."; the owner's answer: act --item <question> --action record_decision --params '{"decision": "<the owner's words>"}' --source <session> --quote "<the owner's words>" |
| a reminder file in reminders/ | remind --run R --text "..." --due "YYYY-MM-DD HH:MM" --session <session source> --quote "<the owner's words asking for it>"; once delivered: act --item <reminder> --action show --actor program |
| a watermark in state.json | watermark --run R --channel <name> --at "YYYY-MM-DD HH:MM", only after the channel was read in full |
| a line in view/run_skips.tsv | skip --run R --channel <name> --code tool_absent/page_failed/permission_refused/not_due/partly_read --text "<one plain sentence>" |
| python3 tools/run_gate.py --start ... | the same command still works; it calls mrun.py gate --run R (exit code 1 when a channel was left without a valid reason or something read is not classified) |
| python3 tools/build_status.py | the same command still works; it calls mrun.py status --out view/status.md --live-check "<time and result of the live check>" |
| state.json jobs.<id>.last_period | python3 tools/mdb.py --db db/marionette.db due-jobs lists every due period; after a job: python3 tools/mdb.py --db db/marionette.db do execute --actor claude --target <job> --run R, then do mark_period_done --actor program --target <job> --params '{"period": "<period>"}' --run R |
| a new job the owner asks for | python3 tools/mdb.py --db db/marionette.db do create --type job --actor user --params '{"title": "<id>", "instructions": "<the text of jobs/<id>.md>", "schedule": {"every": "day", "at": "07:30"}}' --evidence '{"source": <session>, "quote": "<the owner's words>"}'; jobs.md and jobs/<id>.md are still written as before |

## What stays in files
MANUAL.md, channels.md, jobs.md, jobs/, rules_by_subject.md, decisions.md, sessions/, runs.log, improvements.md,
outputs/, inbox/, view/ (built from the database), archive/, and state.json (mode, owner settings, scheduled task
ids, last_audit; no watermarks and no lock).
