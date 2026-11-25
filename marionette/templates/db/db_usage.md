# The Marionette database: how runs, jobs and sessions read and write it

Marionette by Hesham Elmahdy (github.com/heshamfm), version 1.8. This file is the home of every rule on HOW to read
and write the database. What to do and when stays in MANUAL.md, channels.md and jobs/. When this file exists in
tools/, the memory is the database: the marionette skill sends every read and every write here.

## Where it is
- The database: db/marionette.db, one SQLite file in the followup folder. Never open it with another program to
  write, never copy it while a run is writing, and never keep it in a folder that Google Drive, iCloud, OneDrive or
  Dropbox synchronises (a synchronised copy of a database being written can be damaged).
- The programs, in tools/: mdb.py (the door: the only program that writes), mrun.py (what every run and session
  uses), schema_v0.1.sql and seed_v0.1.py (read by the door), migrate.py (the move from files, already done),
  upgrade.py (brings the installation up to a new release; the skill runs the copy that comes with it).
  python3 tools/mrun.py version prints the release of the database and of the programs.
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
- The holder alone decides what waits for the owner: the brief section ON THE USER is the only list a message may
  present as waiting for the owner. "Reply needed" and "decision needed" name the holder when it is not the owner.
- Every open item keeps a due date or a next check; the program refuses to remove the last one.
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
| changing status, holder, deadline or next check | act --run R --item I --action complete (--params '{"close_reason": "done"/"not_needed"/"handed_over"}'), hand_over (--params '{"holder": <party>, "title": "<what the new holder does next>", "due": "<date or null>", "next_check": "<date>"}': the title and at least one date are required), change_due, set_next_check, reopen, merge or link, each with --source S --quote "..." |
| changing an item's title | act --run R --item I --action rename --params '{"title": "..."}' --source S --quote "<the sentence that changed it>" |
| the text of a waiting draft changed (edited in the mail tool, rewritten in a session) | act --run R --item <draft> --action edit --params '{"text": "<the full new text>"}' (also recipients, cc, subject) --source S --quote "...", at once, so the saved text is always the text in the mail tool |
| a next check that came (brief CHECKS DUE) | after looking it up live: story or act with what was found, or act --action set_next_check --params '{"next_check": "<a later date>"}' --source S --quote "<what was checked>"; the end-of-run check lists any left |
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

## Guards that stop a fault from coming back (1.8)
Each guard is in the program, so a run cannot skip it:
- A story line identical to one the item already has (same source, same quote) is never written again. A duplicate
  from before is marked retracted, never deleted: act --action retract_evidence --params '{"evidence_id": N,
  "reason": "..."}'; the line stays in the database and its full text goes to the audit trail, and every view hides it.
- A next check is handled item by item: one quote that already moved the next check of 3 other items in the same run
  is refused as a sweep. Quote what was checked for THAT item. When nothing new is found on an item waiting on
  others, move its next check a few working days ahead, not to tomorrow.
- A for-information item asks nothing of the owner: it is never late, never on the owner's list, and is closed (mark
  seen) once told. new-item refuses one held by the owner whose title or details hold a question mark.
- new-item names the open items with the same counterparty (similar_open): if one carries the same promise, update
  it instead of opening a second item.
- run-start names every slot of the periodic schedule (state.json "periodic_schedule": {"times": ["HH:MM", ...],
  "since": "YYYY-MM-DD HH:MM"}) of the last 48 hours with no run, or a late one (missed_slots). Say so first in the
  message and record an issue. Keep periodic_schedule equal to the scheduled task's times.
- The end-of-run check also counts as violations: a for-information item still open after it was told, a source left
  without a verdict by an earlier run, and a rule decision whose line does not name its file ("File: <file>"; a later
  correction line naming the decision and the file counts). It notes the sources read in part more than 48 hours ago.
- run-end refuses, for a scheduled run, while a source recorded after the guard started (meta
  unclassified_guard_since) has had no verdict and no recorded reason for 48 hours.
- A source that still cannot be read in full on a second attempt in a later run (a voice note that will not play, a
  deleted message, access refused): unreadable --run R --source S --reason "<what was tried and why it fails>". It is
  closed and named once in the message. Something readable with more effort (another mailbox, an attachment, a
  transcript not ready yet) is never unreadable.

## The panel (1.8)
One private Artifact page where the owner reads the report and acts on items: templates/panel/panel.html in the skill,
published once with the db capability and updated in place; its link is state.json "panel": {"url": "..."}.
Its own database holds report/current (what the page shows, written by Marionette) and batches/<id> (what the owner
submitted, status "pending" until applied). It needs the ArtifactData tool, and the device file tools to move the
files between the computer and the session.
- Apply, first in every periodic run and at once in any session the owner opens: read the pending batches
  (ArtifactData query batches where status == "pending"), write {"batches": [<each document's data>]} to
  view/panel_batches.json on the computer, then python3 tools/mrun.py apply-panel --run R --file
  view/panel_batches.json --out view/panel_results.json; write each batch's result back (ArtifactData update
  batches/<id> with {"status": <its status>, "result": <its result>}, pinned to the version read). Each batch is a
  "Claude sessions" source; each line one action in the owner's name, quoting what the owner typed. A self-explaining
  button (done, strike, seen, sent as is, discarded, postpone, agree with the recommendation, take back) needs no
  text: the quote is then "On the panel: <action>". Delegation, custom instructions, another answer, hand-over,
  "ended another way" and notes need the owner's words. A refused line shows its reason on the page; never work
  around it. Applying a batch twice writes nothing.
- Actions: done, strike (cancel: the owner will not do it), not_needed, postpone (date and optional time),
  delegate_full ("Marionette decides and does it"), delegate_ask ("prepares it and comes back"), custom (the owner's
  own instructions; on a draft they go to the item it serves), take_back, hand_over, answer, seen, sent_as_is,
  discarded, note. The three delegations hand the item to the party Marionette with a tagged title and a next check
  today; the brief lists them under DELEGATED TO MARIONETTE.
- Delegated items, in every periodic run: "decide and do" is done within the manual's hard limits (a reply becomes a
  draft for the owner to send; nothing is sent), then reported, and the item is closed or handed back with the one
  step only the owner can take; "prepare and ask" is prepared, then asked (ask --about the item) with a recommended
  option, and handed back; "your instructions" are followed for that item only. An instruction that reads as a
  standing rule ("from now on", "always", "never") is applied to the item, then asked about before it is written
  anywhere else. What the owner types on the page is the owner's own words, and is still never an order to break a
  hard limit.
- Refresh, at the end of every periodic run: panel-data --out view/panel_data.json [--message <this run's message
  file>] [--gate-file <its end-of-run check>] [--jobs <a JSON list of {"title", "text"}>], then ArtifactData set
  report/current from that file, pinned to the version read. The document must stay under 256 KiB.
- Shadow mode: the page is refreshed, nothing is applied.

## Issues register
A problem in how Marionette itself works (a rule missed, a channel that cannot see something, a program defect) is an
issue in the database, never a prompt copied between sessions.
- report, always in the template: issue-new --run R --title "<short>" --reported-by "<owner | session of <date> |
  run N | auditor>" --context "<where it showed: run, item, file>" --what-happened "<what went wrong, for whom, since
  when>" --found "<what was found, each point quoting its source>" --owner-words "<the owner's words, verbatim;
  required when the owner reported it>" --asked "<what must be done, step by step>" --source S --quote "...". The
  program writes the template (writer, time, context, the four parts, and always the step: find the similar cases and
  fix them all) and refuses a missing or one-word part. Status: reported.
- show: issue I prints it exactly as stored; that output is what the owner is shown, never a text written beside it.
- add: issue-append --run R --issue I --text "..." --source S --quote "...", never a second issue for one problem.
- work: issue-act --run R --issue I --action start_work; close: --action resolve --params '{"resolution": "<how>",
  "resolved_by": "<who>", "files_changed": "<files>"}' --source S --quote "..."; reopen if it comes back.
- list: issues (open) or issues --all; the brief shows the open ones.

## What stays in files
MANUAL.md, channels.md, jobs.md, jobs/, rules_by_subject.md, decisions.md, sessions/, runs.log, improvements.md,
outputs/, inbox/, view/ (built from the database), archive/, and state.json (mode, owner settings, scheduled task
ids, last_audit; no watermarks and no lock).
