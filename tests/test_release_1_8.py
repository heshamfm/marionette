"""Tests for what Marionette 1.8 changed, and for the upgrade of a 1.7 installation.

Run from the repository root:
    python3 tests/test_release_1_8.py
Prints one line per check and ends with "bad N of M". The upgrade checks build a real 1.7 installation from the
repository history (git), so they are skipped, and said so, when the history is not there.
"""
import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_T = os.path.join(ROOT, 'marionette', 'templates', 'db')
sys.path.insert(0, DB_T)
import mdb  # noqa: E402

res = []


def check(name, cond, info=''):
    res.append((name, bool(cond), str(info)[:300]))


def run(args, cwd=None, env=None):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=cwd, env=env)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = p.stdout
    return p.returncode, out, p.stderr


# ============================================================== a fresh installation folder
F = tempfile.mkdtemp(prefix='m18_')
os.makedirs(os.path.join(F, 'db'))
DB = os.path.join(F, 'db', 'marionette.db')
door, ME, MAR = mdb.init(DB, 'Dana Owner', 'dana@example.com', timezone='UTC')
ENV = dict(os.environ, MARIONETTE_DB=DB)
MR = os.path.join(DB_T, 'mrun.py')


def mr(*a):
    return run([MR] + list(a), env=ENV)


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


check('a new database records release 1.8 and dates its guards',
      mdb.VERSION.startswith('1.8') and door.meta('unclassified_guard_since') and door.meta('marionette_party_id'))
rc, out, _ = mr('run-start', '--kind', 'session')
R = str(out['run'])
rc, out, _ = mr('record', '--run', R, '--channel', 'Claude sessions', '--type', 'session', '--external-id', 's1.md',
                '--title', 'session', '--read', 'full')
S = str(out['id'])
rc, out, _ = mr('party', '--run', R, '--name', 'Ahmed Partner', '--email', 'ahmed@example.com', '--source', S,
                '--quote', 'Ahmed will review it')
AH = str(out['id'])


def item(title, holder='me', typ='commitment', details=None, **kw):
    args = ['new-item', '--run', R, '--type', typ, '--title', title, '--holder', holder, '--source', S,
            '--quote', 'quote for ' + title, '--details', json.dumps(details or {'text': 'x'})]
    if typ == 'commitment':
        args += ['--promised-by', kw.get('promised_by', 'me')]
    args += ['--next-check', kw.get('next_check', '2026-12-01')]
    return mr(*args)


rc, out, _ = item('Send the proposal to Ahmed')
I1 = str(out['id'])
check('an item is created', rc == 0, out)

# --- duplicate story lines: never written twice, and retracted without deleting
rc, a, _ = mr('story', '--run', R, '--item', I1, '--source', S, '--quote', 'Ahmed asked again on Monday')
rc2, b, _ = mr('story', '--run', R, '--item', I1, '--source', S, '--quote', 'Ahmed asked again on Monday')
n = con().execute('SELECT count(*) FROM evidence WHERE thing_id=? AND quote=?', (int(I1), 'Ahmed asked again on Monday')).fetchone()[0]
check('story: the same line twice is written once', rc == 0 and rc2 == 0 and b.get('already') and n == 1, (b, n))
rc, c2, _ = mr('act', '--run', R, '--item', I1, '--action', 'complete', '--params', '{}', '--source', S,
               '--quote', 'Ahmed asked again on Monday')
check('the door itself reuses an identical line from another path', con().execute(
    'SELECT count(*) FROM evidence WHERE thing_id=? AND quote=?', (int(I1), 'Ahmed asked again on Monday')).fetchone()[0] == 1)
# a duplicate made the old way (before 1.8), then retracted
c = con()
c.execute('INSERT INTO evidence(thing_id,source_id,quote) VALUES(?,?,?)', (int(I1), int(S), 'old duplicate'))
c.execute('INSERT INTO evidence(thing_id,source_id,quote) VALUES(?,?,?)', (int(I1), int(S), 'old duplicate'))
c.commit()
dup = c.execute("SELECT max(id) FROM evidence WHERE quote='old duplicate'").fetchone()[0]
rc, out, _ = mr('act', '--run', R, '--item', I1, '--action', 'retract_evidence', '--params',
                json.dumps({'evidence_id': dup, 'reason': 'duplicate of the line above'}))
rc, it, _ = mr('item', I1)
check('retract: the line is hidden from the item and kept in the database',
      [x['quote'] for x in it['story']].count('old duplicate') == 1 and
      con().execute("SELECT count(*) FROM evidence WHERE quote='old duplicate'").fetchone()[0] == 2, it.get('story'))
rc, out, _ = mr('act', '--run', R, '--item', I1, '--action', 'retract_evidence', '--params',
                json.dumps({'evidence_id': dup, 'reason': 'x'}))
check('retract: a reason of a few words is required', rc == 2, out)

# --- checks due handled item by item
ids = []
for k in range(5):
    rc, out, _ = item(f'Waiting item {k}', holder=AH, typ='commitment', promised_by=AH)
    ids.append(str(out['id']))
outs = [mr('act', '--run', R, '--item', i, '--action', 'set_next_check', '--params', '{"next_check": "2026-12-05"}',
           '--source', S, '--quote', 'swept the mailbox, nothing new') for i in ids]
check('set_next_check: one quote moves at most 3 items in a run (a sweep is refused)',
      [o[0] for o in outs] == [0, 0, 0, 2, 2] and 'bulk sweep' in str(outs[3][1]), [o[0] for o in outs])

# --- for-information items: never late, never on the user, never a question
INFO = {'what_happened': 'x', 'why_it_matters': 'y'}
rc, out, _ = item('Is a reply to the review needed?', typ='for_info', details=INFO)
check('new-item refuses a for-information item that asks the user something', rc == 2 and 'question mark' in str(out), out)
rc, out, _ = item('The certificate renewed itself', typ='for_info', next_check='2026-01-01', details=INFO)
FI = str(out['id'])
c = con()
c.execute("UPDATE thing SET created_at='2026-01-01 09:00' WHERE id=?", (int(FI),))
c.commit()
rc, late, _ = mr('late')
rc, brief, _ = run([MR, 'brief'], env=ENV)
on_user = brief.split('## ON THE USER')[1].split('##')[0]
check('a for-information item is never late and never on the user',
      int(FI) not in [x['id'] for x in late] and 'certificate renewed' not in on_user)

# --- similar open items are shown when a new one shares the counterparty
rc, out, _ = item('Ahmed sends the signed copy', holder=AH, typ='commitment', promised_by=AH)
check('new-item names the open items with the same counterparty', rc == 0 and out.get('similar_open'), out)

# --- the end-of-run check
open(os.path.join(F, 'channels.md'), 'w').write('# channels\n')
open(os.path.join(F, 'decisions.md'), 'w').write(
    '- D1 | 2026-01-01 | rule | Mail from X is archived. | session | File: rules_by_subject.md\n'
    '- D2 | 2026-01-02 | rule | Reports are in English. | session\n'
    '- D3 | 2026-01-03 | قاعدة | لا ألقاب في المسودات. | جلسة\n'
    '- D4 | 2026-01-04 | correction | D3 File: rules_by_subject.md\n')
mr('verdict', '--run', R, '--source', S, '--verdict', 'linked')
rc, out, _ = mr('run-end', '--run', R)
check('the session run ends', rc == 0, out)
rc, out, _ = mr('run-start', '--kind', 'schedule')
R2 = str(out['run'])
p = subprocess.run([sys.executable, MR, 'gate', '--run', R2, '--channels-file', os.path.join(F, 'channels.md')],
                   capture_output=True, text=True, env=ENV)
check('gate: a for-information item still open after it was told is a violation', 'certificate renewed' in p.stdout,
      p.stdout)
check('gate: a rule decision without its file is a violation, a corrected one is not',
      'D2' in p.stdout and 'D1 ' not in p.stdout and 'Rule decision D3' not in p.stdout, p.stdout)

# --- missed scheduled runs are named at run start
st = {'periodic_schedule': {'times': ['09:00', '15:00'], 'since': '2000-01-01 00:00'}}
json.dump(st, open(os.path.join(F, 'state.json'), 'w'))
rc, out, _ = mr('run-end', '--run', R2, '--failed')
rc, out, _ = mr('run-start', '--kind', 'schedule')
R3 = str(out['run'])
check('run-start names the scheduled runs of the last 48 hours that did not happen', rc == 0 and out.get('missed_slots'),
      out)

# --- run-end refuses a source left unclassified for more than 48 hours
c = con()
c.execute("UPDATE meta SET value='2000-01-01 00:00' WHERE key='unclassified_guard_since'")
c.commit()
rc, out, _ = mr('record', '--run', R3, '--channel', 'Claude sessions', '--type', 'session', '--external-id', 'old.md',
                '--title', 'an old source never classified')
OLD = str(out['id'])
c = con()
c.execute("UPDATE thing SET created_at='2026-01-01 09:00' WHERE id=?", (int(OLD),))
c.commit()
rc, out, _ = mr('run-end', '--run', R3)
check('run-end refuses while a source read more than 48 hours ago has no verdict', rc == 2 and 'no verdict' in str(out),
      out)
rc, out, _ = mr('unreadable', '--run', R3, '--source', OLD, '--reason', 'voice note would not play on two tries')
check('unreadable closes a source on a second attempt in a later run', rc == 0, out)
rc, out, _ = mr('run-end', '--run', R3)
check('then run-end succeeds', rc == 0, out)

# --- the panel: data, and applying what the owner submitted
rc, out, _ = mr('run-start', '--kind', 'session')
R4 = str(out['run'])
rc, out, _ = item('Prepare the board pack')
P1 = str(out['id'])
rc, out, _ = item('Answer the vendor')
P2 = str(out['id'])
rc, out, _ = mr('ask', '--run', R4, '--question', 'Which hotel for the offsite?', '--source', S, '--quote', 'q',
                '--recommend', 'Hotel A')
Q1 = str(out['id'])
pd = os.path.join(F, 'panel.json')
rc, out, _ = mr('panel-data', '--out', pd)
data = json.load(open(pd, encoding='utf-8'))
check('panel-data writes the sections the page shows', rc == 0 and {'on_you', 'late', 'questions', 'delegated',
                                                                      'for_info', 'waiting', 'drafts'} <= set(data), out)
batch = {'batches': [{'id': 'b20260101T0900aaaa', 'submitted_at': '2026-01-01 09:00', 'lines': [
    {'item': int(P1), 'action': 'done', 'reason': ''},
    {'item': int(P2), 'action': 'delegate_full', 'reason': 'Write the reply politely and keep it short'},
    {'item': int(Q1), 'action': 'answer', 'answer': 'Hotel A', 'accepted': True, 'reason': ''},
    {'item': int(FI), 'action': 'strike', 'reason': ''},
    {'item': int(ids[0]), 'action': 'not_needed', 'reason': ''},
    {'item': 999999, 'action': 'done', 'reason': 'no such item'}]}]}
bf = os.path.join(F, 'batch.json')
json.dump(batch, open(bf, 'w'))
rc, out, _ = mr('apply-panel', '--run', R4, '--file', bf, '--out', os.path.join(F, 'r1.json'))
r1 = json.load(open(os.path.join(F, 'r1.json')))['b20260101T0900aaaa']
oks = [x['ok'] for x in r1['lines']]
check('apply-panel applies each line and reports the refusals beside them', oks == [True, True, True, True, False, False],
      r1)
c = con()
st1 = c.execute('SELECT status FROM followup WHERE thing_id=?', (int(P1),)).fetchone()[0]
hold = c.execute('SELECT holder_id FROM followup WHERE thing_id=?', (int(P2),)).fetchone()[0]
actor = c.execute("SELECT actor FROM audit WHERE thing_id=? AND field='followup.status' ORDER BY id DESC",
                  (int(P1),)).fetchone()[0]
quote = c.execute('SELECT quote FROM evidence WHERE thing_id=? ORDER BY id DESC', (int(P1),)).fetchone()[0]
check('a done button closes the item in the owner\'s name, quoting the panel', st1 == 'done' and actor == 'user' and
      quote.startswith('On the panel'), (st1, actor, quote))
check('delegation hands the item to Marionette', hold == MAR)
check('a question is answered with the recommendation', c.execute(
    'SELECT status FROM followup WHERE thing_id=?', (int(Q1),)).fetchone()[0] == 'done')
rc, brief, _ = run([MR, 'brief'], env=ENV)
check('the brief lists delegated items', 'DELEGATED TO MARIONETTE (1)' in brief)
rc, out, _ = mr('apply-panel', '--run', R4, '--file', bf, '--out', os.path.join(F, 'r2.json'))
r2 = json.load(open(os.path.join(F, 'r2.json')))['b20260101T0900aaaa']
check('applying the same batch twice writes nothing the second time',
      all(x.get('already') for x in r2['lines'] if x['ok']), r2)

# --- 1.8.1: chat check and spam that could not be marked
d2 = mdb.Door(DB)
d2.ctx = {'actor': 'program', 'action': 'create', 'run': None, 'evidence_id': None, 'held': None}
d2.conn.execute('BEGIN IMMEDIATE')
wch = d2.new_thing('channel', 'whatsapp_web')
d2.conn.execute("INSERT INTO channel(thing_id,connection) VALUES(?,?)", (wch, 'chrome'))
d2.conn.execute('COMMIT')
R5 = R4
rc, out, _ = mr('record', '--run', R5, '--channel', 'whatsapp_web', '--type', 'message', '--external-id', 'Ahmed 09:00',
                '--title', 'Ahmed on chat: can we meet?', '--read', 'full')
WS = str(out['id'])
rc, out, _ = mr('new-item', '--run', R5, '--type', 'reply_needed', '--title', 'Ahmed asks to meet', '--holder', 'me',
                '--requested-by', AH, '--next-check', '2026-12-01', '--details', '{"request": "meet"}', '--source', WS,
                '--quote', 'can we meet?')
WI = str(out['id'])
rc, brief, _ = run([MR, 'brief'], env=ENV)
check('the brief lists an item resting on a chat under CHAT CHECK',
      'CHAT CHECK' in brief and ('- ' + WI + ' |') in brief.split('## CHAT CHECK')[1].split('##')[0], brief[-600:])
check('the ask-once section is gone', 'ASK ONCE' not in brief)
rc, out, _ = mr('record', '--run', R5, '--channel', 'whatsapp_web', '--type', 'message', '--external-id', 'spam 1',
                '--title', 'Lottery winner', '--read', 'full')
mr('verdict', '--run', R5, '--source', str(out['id']), '--verdict', 'ignored', '--reason',
   'spam_unmarked:scam:chat:the report button was missing')
p = subprocess.run([sys.executable, MR, 'gate', '--run', R5, '--channels-file', os.path.join(F, 'channels.md')],
                   capture_output=True, text=True, env=ENV)
check('the end-of-run check lists spam that could not be marked, apart from the ignored ones',
      'could not be marked (1)' in p.stdout and 'Lottery winner' in p.stdout.split('could not be marked')[1], p.stdout)

# the published programs carry nothing of one user
code = ''.join(open(os.path.join(DB_T, f), encoding='utf-8').read() for f in ('mdb.py', 'mrun.py', 'upgrade.py'))
code = code.replace('Marionette by Hesham Elmahdy (github.com/heshamfm)', '')
check('no name, company or place of one user in the programs',
      not [w for w in ('hesham', 'odootec', 'cairo', 'هشام', 'ماريونيت (claude)') if w in code.lower()])
check('the panel page ships with the skill', os.path.exists(os.path.join(ROOT, 'marionette', 'templates', 'panel',
                                                                         'panel.html')))

# ============================================================== the upgrade of a 1.7 installation
git = shutil.which('git')
have = git and subprocess.run([git, 'cat-file', '-e', '6d135bb:marionette/templates/db/mdb.py'], cwd=ROOT,
                              capture_output=True).returncode == 0
if not have:
    print('SKIPPED: the upgrade checks need the repository history (git, release 1.7 at 6d135bb)')
else:
    G = tempfile.mkdtemp(prefix='inst17_')
    os.makedirs(os.path.join(G, 'tools'))
    os.makedirs(os.path.join(G, 'db'))
    for f in ('mdb.py', 'mrun.py', 'schema_v0.1.sql', 'seed_v0.1.py', 'migrate.py', 'upgrade.py', 'db_usage.md',
              'doors/brief.py', 'doors/run_gate.py', 'doors/build_status.py'):
        data = subprocess.run([git, 'show', f'6d135bb:marionette/templates/db/{f}'], cwd=ROOT, capture_output=True
                              ).stdout
        open(os.path.join(G, 'tools', os.path.basename(f)), 'wb').write(data)
    json.dump({'mode': 'live', 'memory': {'kind': 'database', 'version': '1.7'}}, open(os.path.join(G, 'state.json'), 'w'))
    open(os.path.join(G, 'runs.log'), 'w').write('')
    open(os.path.join(G, 'decisions.md'), 'w').write('- D41 | 2026-01-01 | rule | x | s\n')
    code = ("import sys, json; sys.path.insert(0, sys.argv[1]); import mdb\n"
            "d, me, mar = mdb.init(sys.argv[2], 'Old Owner', 'old@example.com', timezone='UTC')\n"
            "d.conn.execute('BEGIN IMMEDIATE')\n"
            "t = d.new_thing('commitment', 'Promise')\n"
            "d.conn.execute(\"INSERT INTO followup(thing_id,status,holder_id,next_check,details) VALUES(?,'open',?,"
            "'2026-12-01',?)\", (t, me, json.dumps({'text': 'x'})))\n"
            "s = d.new_thing('session', 'old session')\n"
            "ch = int(d.meta('sessions_channel_id'))\n"
            "d.conn.execute(\"INSERT INTO source(thing_id,channel_id,external_id,read_state) VALUES(?,?,'o.md','full')\", (s, ch))\n"
            "for _ in range(3): d.conn.execute('INSERT INTO evidence(thing_id,source_id,quote) VALUES(?,?,?)', (t, s, 'same line'))\n"
            "d.conn.execute('COMMIT')\nprint(t)\n")
    p = subprocess.run([sys.executable, '-c', code, os.path.join(G, 'tools'), os.path.join(G, 'db', 'marionette.db')],
                       capture_output=True, text=True)
    T17 = int(p.stdout.strip() or 0)
    check('a 1.7 installation is built', p.returncode == 0 and T17, p.stderr)
    UP = os.path.join(DB_T, 'upgrade.py')
    rc, out, _ = run([UP, '--followup', G, '--check'])
    check('check: reads the installation as 1.7 and counts the duplicates',
          rc == 0 and out['installed'] == '1.7' and out['data']['duplicate_story_lines_retracted'] == 2, out)
    rc, out, err = run([UP, '--followup', G, '--apply', '--approval', 'yes'])
    check('apply succeeds', rc == 0 and out.get('applied'), (out, err))
    g = sqlite3.connect(os.path.join(G, 'db', 'marionette.db'))
    meta = dict(g.execute('SELECT key, value FROM meta').fetchall())
    check('apply: release, guard dates and the decision number are recorded',
          meta.get('marionette_version') == mdb.VERSION and meta.get('unclassified_guard_since') and
          meta.get('decision_file_rule_from') == '42', meta)
    check('apply: the duplicates are retracted, never deleted',
          g.execute("SELECT count(*) FROM audit WHERE action='retract_evidence'").fetchone()[0] == 2 and
          g.execute("SELECT count(*) FROM evidence WHERE quote='same line'").fetchone()[0] == 3)
    check('apply: the permission line for retracting exists', g.execute(
        "SELECT count(*) FROM action_rule WHERE action='retract_evidence'").fetchone()[0] >= 2)
    rc, out, _ = run([UP, '--followup', G, '--check'])
    check('a second check finds it up to date', rc == 0 and out['installed'] == mdb.VERSION, out)

bad = [r for r in res if not r[1]]
for name, good, info in res:
    print((' - ' if good else ' X ') + name + ('' if good else ' => ' + info))
print(f'bad {len(bad)} of {len(res)}')
sys.exit(1 if bad else 0)
