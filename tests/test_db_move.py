"""Tests for the move from files to the database (marionette/templates/db/migrate.py) and for the run-time layer
(mrun.py) after the move. Run from the repository root: python3 tests/test_db_move.py
Ends with "bad N of M"; exit code 1 when any check fails."""
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(ROOT, 'marionette', 'templates', 'db')
TEMPLATES = os.path.join(ROOT, 'marionette', 'templates')
APPROVAL = 'Yes, move my Marionette to the database.'
res = []


def check(name, cond, info=''):
    res.append((name, cond, str(info)[:400]))


def run(args, cwd=None):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=cwd)
    out = p.stdout
    try:
        out = json.loads(out)
    except ValueError:
        pass
    return p.returncode, out, p.stderr


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def starter(F, language='English', days=(0, 1, 2, 3, 4), filled=True):
    """A followup folder as Setup creates it, with some history when filled."""
    for d in ('items', 'sessions', 'reminders', 'inbox', 'outputs', 'data/drafts', 'archive', 'view', 'jobs', 'tools'):
        os.makedirs(os.path.join(F, d), exist_ok=True)
    write(os.path.join(F, 'state.json'), json.dumps({
        'version': 1, 'mode': 'live',
        'owner': {'name': 'Test Owner', 'address_as': 'Test', 'language': language, 'email': 'owner@example.com',
                  'timezone': 'Europe/London', 'working_days': list(days)},
        'lock': {'holder': None, 'since': None},
        'watermarks': {'mail': '2026-11-15 09:00', 'calendar': '2026-11-15 09:00'},
        'last_audit': None, 'triggers': {}, 'jobs': {}, 'skill_synced_decision': 'D1'}))
    write(os.path.join(F, 'channels.md'), '# Channels\n\n## mail\nstatus: enabled\nhow: all mail.\n\n'
                                          '## calendar\nstatus: enabled\nhow: events.\n')
    write(os.path.join(F, 'jobs.md'), '# Jobs\n\n| id | what | schedule | period | notes |\n|----|------|----------|--------|-------|\n')
    write(os.path.join(F, 'index.tsv'), 'key\tstatus\ttype\tdeadline\trecord\tcounterparty\ttitle\tlast_event\n')
    write(os.path.join(F, 'drafts.tsv'), 'draft_id\titem_key\tchannel\tcreated\tstatus\tlast_checked\tnote\n')
    write(os.path.join(F, 'questions.md'), '# Questions\n\n## Open\n\n## Answered\n')
    write(os.path.join(F, 'decisions.md'), '# Decisions\n\n- D1 | 2026-11-10 | Marionette set up | owner\n')
    write(os.path.join(F, 'data', 'disposition.tsv'),
          'source\tsource_id\tdate\tsender\tsubject\tdisposition\tkey_or_reason\trun\n')
    write(os.path.join(F, 'rules_by_subject.md'), '# Rules by subject\n')
    write(os.path.join(F, 'runs.log'), '')
    write(os.path.join(F, 'sessions', 'move.md'), '# session\n')
    shutil.copy(os.path.join(TEMPLATES, 'brief.py'), os.path.join(F, 'tools', 'brief.py'))
    shutil.copy(os.path.join(TEMPLATES, 'run_gate.py'), os.path.join(F, 'tools', 'run_gate.py'))
    if not filled:
        return
    rows = [('mail-t1-1', 'open', 'reply_needed', '2026-11-20', 'Bob Smith bob@example.org', 'Reply to Bob'),
            ('mail-t2-1', 'waiting_on_others', 'my_commitment', '', 'Alice alice@example.org', 'Send Alice the plan'),
            ('cal-e1-1', 'done', 'their_commitment', '2026-11-10', 'Dave', 'Dave sends the contract'),
            ('mail-t3-1', 'postponed', 'decision_needed', 'next month', '', 'Choose a vendor'),
            ('mail-t4-1', 'closed_no_action', 'fyi', '', 'news@example.org', 'Newsletter'),
            ('mail-t5-1', 'open', 'fyi', '', '', 'Office closed on Friday')]
    with open(os.path.join(F, 'index.tsv'), 'a', encoding='utf-8') as f:
        for k, s, t, dl, cp, title in rows:
            f.write(f'{k}\t{s}\t{t}\t{dl}\t\t{cp}\t{title}\t2026-11-16\n')
            write(os.path.join(F, 'items', k + '.md'),
                  f'key: {k}\nopened: 2026-11-14\nsource: mail\ncounterparty: {cp}\n\n## Needed\nWhat {k} needs.\n\n'
                  f'## Story\n- 2026-11-14 10:00 | first event of {k}\n- 2026-11-16 11:00 | later event of {k}\n')
    with open(os.path.join(F, 'drafts.tsv'), 'a', encoding='utf-8') as f:
        f.write('d0\tmail-t1-1\tmail\t2026-11-15\tsuperseded\t\t\n')
        f.write('d1\tmail-t1-1\tmail\t2026-11-16\twaiting\t\t\n')
        f.write('d2\tmail-t2-1\tmail\t2026-11-15\tsent_as_is\t\t\n')
    for d in ('d0', 'd1', 'd2'):
        write(os.path.join(F, 'data', 'drafts', d + '.txt'), f'To: bob@example.org\nSubject: Re: {d}\n\nHello.\n')
    write(os.path.join(F, 'questions.md'), '# Questions\n\n## Open\n- 2026-11-16 10:00 | Q1 | mail-t3-1 | Which '
                                           'vendor, A or B? | A\n\n## Answered\n')
    write(os.path.join(F, 'reminders', 'bank.md'), 'Call the bank\ndue: 2026-11-19 09:00\ndelivered:\n')
    with open(os.path.join(F, 'data', 'disposition.tsv'), 'a', encoding='utf-8') as f:
        f.write('mail\tt1\t2026-11-16\tbob@example.org\tpricing\tlinked\tmail-t1-1\t1\n')
        f.write('mail\tz9\t2026-11-16\tads@example.org\tsale\tignored\tmarketing\t1\n')
    with open(os.path.join(F, 'jobs.md'), 'a', encoding='utf-8') as f:
        f.write('| morning | morning brief | working days 07:30 | day | |\n')
    write(os.path.join(F, 'jobs', 'morning.md'), 'Write the morning brief.\n')


def migrate(F, *extra):
    return run([os.path.join(DB_DIR, 'migrate.py'), '--followup', F, '--approval', APPROVAL,
                '--session-file', 'sessions/move.md', *extra])


# ---------------- reading job schedules: strict, never guessed ----------------
sys.path.insert(0, DB_DIR)
import migrate as mig  # noqa: E402
CASES = {'Sun-Thu 07:30': {'every': 'day', 'at': '07:30', 'days': ['sun', 'mon', 'tue', 'wed', 'thu']},
         'every day 09:00, covering meetings since the last run': {'every': 'day', 'at': '09:00'},
         '07:30': {'every': 'day', 'at': '07:30'},
         'working days 07:30': {'every': 'day', 'at': '07:30', 'days': 'WORKDAYS'},
         'Sunday 08:50': {'every': 'week', 'day': 'sun', 'at': '08:50'},
         'Mon 9:05': {'every': 'week', 'day': 'mon', 'at': '09:05'},
         'day 1, 09:00': {'every': 'month', 'day': 1, 'at': '09:00'},
         '-': None, '': None, 'daily post draft': None, 'Wednesday': None, 'day 30 09:00': None,
         'sunday morning 08:00': None}
for text, want in CASES.items():
    got = mig.parse_schedule(text)
    check(f'schedule "{text}" is read as {want}', got == want, got)

tmp = tempfile.mkdtemp(prefix='marionette_move_')
try:
    # ---------------- an installation with history ----------------
    F = os.path.join(tmp, 'a', 'followup')
    starter(F)
    before = {p: open(os.path.join(F, p), encoding='utf-8').read() for p in ('index.tsv', 'drafts.tsv', 'questions.md')}
    rc, out, err = migrate(F)
    check('the check passes on a normal installation', rc == 0 and out.get('ready_to_apply'), (out, err))
    check('the check changes nothing in the installation',
          all(open(os.path.join(F, p), encoding='utf-8').read() == t for p, t in before.items())
          and not os.path.exists(os.path.join(F, 'db', 'marionette.db')))
    c = out.get('counts', {}) if isinstance(out, dict) else {}
    check('every item, draft, question, reminder and job is counted in and out',
          (c.get('items'), c.get('drafts'), c.get('questions'), c.get('reminders'), c.get('jobs'))
          == (c.get('items_in_files'), c.get('drafts_in_files'), c.get('questions_in_files'),
              c.get('reminders_in_files'), c.get('jobs_in_files')) == (6, 3, 1, 1, 1), c)
    check('the choices the program made are reported', any('next month' in x for x in out.get('choices', [])), out)

    rc, out, err = migrate(F, '--apply')
    check('apply succeeds', rc == 0 and out.get('applied'), (out, err))
    db = os.path.join(F, 'db', 'marionette.db')
    con = sqlite3.connect(db)
    st = dict(con.execute("SELECT json_extract(f.details,'$.old_key'), f.status FROM followup f WHERE "
                          "json_extract(f.details,'$.old_key') IS NOT NULL").fetchall())
    check('statuses carried over', st == {'mail-t1-1': 'open', 'mail-t2-1': 'open', 'cal-e1-1': 'done',
                                          'mail-t3-1': 'deferred', 'mail-t4-1': 'seen', 'mail-t5-1': 'new'}, st)
    holder = con.execute("SELECT f.holder_id FROM followup f WHERE json_extract(f.details,'$.old_key')='mail-t2-1'"
                         ).fetchone()[0]
    check('waiting on others: the next step is with the other party', holder != 1, holder)
    stories = con.execute("SELECT count(*) FROM evidence e JOIN followup f ON f.thing_id=e.thing_id WHERE "
                          "json_extract(f.details,'$.old_key')='mail-t1-1' AND e.quote LIKE '- 2026-11-1%'").fetchone()[0]
    check('every story line of an item is kept as its evidence', stories == 2, stories)
    dr = dict(con.execute("SELECT json_extract(details,'$.old_draft_id'), status FROM followup f JOIN thing t ON "
                          "t.id=f.thing_id WHERE t.type='draft'").fetchall())
    check('drafts carried over', dr == {'d0': 'abandoned', 'd1': 'ready', 'd2': 'sent_as_is'}, dr)
    wm = dict(con.execute("SELECT t.title, ch.watermark FROM channel ch JOIN thing t ON t.id=ch.thing_id").fetchall())
    check('watermarks carried over', wm.get('mail') == '2026-11-15 09:00', wm)
    runs = con.execute('SELECT status FROM run').fetchall()
    check('the move is one run, closed', runs == [('complete',)] or runs == [('complete_with_gaps',)], runs)
    meta = dict(con.execute('SELECT key, value FROM meta').fetchall())
    check('owner settings in the database', meta.get('timezone') == 'Europe/London' and meta.get('language') == 'en'
          and meta.get('week_start') == 'mon', meta)
    con.close()
    where = out.get('old_files', '')
    check('the old files are kept unchanged in the archive',
          open(os.path.join(F, where, 'index.tsv'), encoding='utf-8').read() == before['index.tsv'])
    ph = open(os.path.join(F, 'index.tsv'), encoding='utf-8').read()
    check('a placeholder at each old path points to the database', 'tools/db_usage.md' in ph and where in ph, ph)
    check('the placeholder is read-only', not os.stat(os.path.join(F, 'index.tsv')).st_mode & stat.S_IWUSR)
    check('the items folder is read-only', not os.stat(os.path.join(F, 'items')).st_mode & stat.S_IWUSR)
    check('db_usage.md is installed, which tells the skill the memory is the database',
          os.path.exists(os.path.join(F, 'tools', 'db_usage.md')))
    s = json.load(open(os.path.join(F, 'state.json'), encoding='utf-8'))
    check('state.json no longer holds watermarks or the lock, and keeps the old ones',
          'watermarks' not in s and 'lock' not in s and s['before_db']['watermarks']['mail'] == '2026-11-15 09:00'
          and s['memory']['kind'] == 'database', s)
    check('the move is written in runs.log', 'move to the database' in open(os.path.join(F, 'runs.log')).read())

    rc, out, err = migrate(F, '--apply')
    check('a second move is refused', rc == 2 and 'already' in str(out), (out, err))

    # the run tools work after the move
    rc, out, err = run([os.path.join(F, 'tools', 'brief.py')], cwd=F)
    check('the brief runs on the database', rc == 0 and 'Reply to Bob' in out and 'Drafts waiting (1)' in out,
          (out, err))
    rc, out, err = run([os.path.join(F, 'tools', 'mrun.py'), 'run-start'], cwd=F)
    R = str(out.get('run')) if isinstance(out, dict) else ''
    check('a run starts', rc == 0 and R, (out, err))
    rc, out, err = run([os.path.join(F, 'tools', 'run_gate.py'), '--run', R], cwd=F)
    check('the end-of-run check flags channels left unread', rc == 1 and 'without an accepted reason' in out, out)
    run([os.path.join(F, 'tools', 'mrun.py'), 'watermark', '--run', R, '--channel', 'mail', '--at', '2026-11-18 10:00'],
        cwd=F)
    run([os.path.join(F, 'tools', 'mrun.py'), 'skip', '--run', R, '--channel', 'calendar', '--code', 'tool_absent',
         '--text', 'The calendar tool was not loaded.'], cwd=F)
    rc, out, err = run([os.path.join(F, 'tools', 'run_gate.py'), '--run', R], cwd=F)
    check('the end-of-run check passes when each channel is read or has a reason', rc == 0 and 'tool is absent' in out,
          (out, err))
    rc, out, err = run([os.path.join(F, 'tools', 'build_status.py'), '--live-check', 'checked'], cwd=F)
    page = open(os.path.join(F, 'view', 'status.md'), encoding='utf-8').read() if rc == 0 else err
    check('the status page is built, with the draft dated from before the move',
          '## Waiting for you' in page and 'since 2026-11-16' in page, page)
    rc, out, err = run([os.path.join(F, 'tools', 'mrun.py'), 'run-end', '--run', R], cwd=F)
    check('the run closes', rc == 0, (out, err))

    # ---------------- undo, then move again ----------------
    rc, out, err = run([os.path.join(F, 'tools', 'migrate.py'), '--followup', F, '--undo'])
    check('undo succeeds and reports the changes made after the move',
          rc == 0 and out.get('undone') and out.get('database_changes_after_move', 0) > 0, (out, err))
    check('undo puts every old file back unchanged',
          all(open(os.path.join(F, p), encoding='utf-8').read() == t for p, t in before.items())
          and os.path.isfile(os.path.join(F, 'items', 'mail-t1-1.md')))
    s = json.load(open(os.path.join(F, 'state.json'), encoding='utf-8'))
    check('undo restores the watermarks and the files version of the tools',
          s.get('watermarks', {}).get('mail') == '2026-11-15 09:00' and 'memory' not in s
          and not os.path.exists(os.path.join(F, 'tools', 'db_usage.md'))
          and 'index.tsv' in open(os.path.join(F, 'tools', 'brief.py'), encoding='utf-8').read(), s)
    check('undo deletes nothing: the database is kept aside',
          os.path.exists(os.path.join(F, out.get('kept_in', 'x'), 'db', 'marionette.db')))
    rc, out, err = migrate(F, '--apply')
    check('after an undo the installation can move again', rc == 0 and out.get('applied'), (out, err))

    # ---------------- refusals ----------------
    G = os.path.join(tmp, 'b', 'followup')
    starter(G)
    with open(os.path.join(G, 'index.tsv'), 'a', encoding='utf-8') as f:
        f.write('x-1\tstrange\treply_needed\t\t\tBob bob@example.org\tOdd status\t\n')
    rc, out, err = migrate(G, '--apply')
    check('apply refuses when something does not fit, and changes nothing',
          rc == 1 and out.get('problems') and not os.path.exists(os.path.join(G, 'db', 'marionette.db'))
          and 'x-1' in open(os.path.join(G, 'index.tsv')).read(), (out, err))
    mp = os.path.join(tmp, 'map.json')
    write(mp, json.dumps({'statuses': {'strange': 'open'}}))
    rc, out, err = migrate(G, '--map', mp)
    check('an installation with its own words passes with --map', rc == 0 and out.get('ready_to_apply'), (out, err))
    s = json.load(open(os.path.join(G, 'state.json')))
    import datetime
    import zoneinfo
    s['lock'] = {'holder': 'periodic',
                 'since': datetime.datetime.now(zoneinfo.ZoneInfo('Europe/London')).strftime('%Y-%m-%d %H:%M')}
    write(os.path.join(G, 'state.json'), json.dumps(s))
    rc, out, err = migrate(G, '--apply', '--map', mp)
    check('apply refuses while a run holds the lock', rc != 0 and 'lock' in (str(out) + err)
          and not os.path.exists(os.path.join(G, 'db', 'marionette.db')), (out, err))

    # ---------------- a new installation, in Arabic, Sunday to Thursday ----------------
    H = os.path.join(tmp, 'c', 'followup')
    starter(H, language='Arabic', days=(6, 0, 1, 2, 3), filled=False)
    # the way the skill runs it: the programs copied into tools/db_install/, run from the followup folder
    shutil.copytree(DB_DIR, os.path.join(H, 'tools', 'db_install'), ignore=shutil.ignore_patterns('__pycache__'))
    rc, out, err = run([os.path.join('tools', 'db_install', 'migrate.py'), '--followup', '.', '--approval', APPROVAL,
                        '--session-file', 'sessions/move.md', '--apply'], cwd=H)
    check('a new, empty installation moves at once, run from tools/db_install', rc == 0 and out.get('applied'),
          (out, err))
    rc, out, err = run([os.path.join('tools', 'brief.py')], cwd=H)
    check('its brief runs from the database', rc == 0 and 'Marionette brief' in out, (out, err))
    con = sqlite3.connect(os.path.join(H, 'db', 'marionette.db'))
    meta = dict(con.execute('SELECT key, value FROM meta').fetchall())
    check('its week starts on Sunday and its language is Arabic',
          meta.get('week_start') == 'sun' and meta.get('language') == 'ar', meta)
    con.close()
    rc, out, err = run([os.path.join(H, 'tools', 'build_status.py'), '--live-check', 'x'], cwd=H)
    page = open(os.path.join(H, 'view', 'status.md'), encoding='utf-8').read() if rc == 0 else err
    check('its status page is written in Arabic', '## ينتظرك أنت' in page, page)
finally:
    for dp, dn, fn in os.walk(tmp):
        for n in dn + fn:
            os.chmod(os.path.join(dp, n), 0o755)
    shutil.rmtree(tmp)

bad = [r for r in res if not r[1]]
for name, ok, info in res:
    print((' - ' if ok else ' X ') + name + ('' if ok else ' => ' + info))
print(f'bad {len(bad)} of {len(res)}')
sys.exit(1 if bad else 0)
