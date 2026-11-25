"""Tests for what Marionette 1.7 changed, and for the upgrade of an installation already in use.

Run from the repository root:
    python3 tests/test_release_1_7.py
Prints one line per check and ends with "bad N of M". The upgrade checks build a real 1.6 installation from the
repository history (git), so they are skipped, and said so, when the history is not there.
"""
import hashlib
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


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def tool_files(F):
    d = os.path.join(F, 'tools')
    return sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)) and not n.endswith('.pyc'))


# ============================================================== the new behaviour, on a fresh database
W = tempfile.mkdtemp(prefix='m17_')
DB = os.path.join(W, 'm.db')
door, ME, MAR = mdb.init(DB, 'Dana Owner', 'dana@example.com', timezone='UTC')
ENV = dict(os.environ, MARIONETTE_DB=DB)
MR = os.path.join(DB_T, 'mrun.py')


def mr(*a):
    return run([MR] + list(a), env=ENV)


rc, out, _ = mr('version')
check('version: a new database records the current release', rc == 0 and out['installed'] == mdb.VERSION and out['programs'] == mdb.VERSION, out)
rc, out, _ = mr('run-start', '--kind', 'session')
R = str(out['run'])
rc, out, _ = mr('record', '--run', R, '--channel', 'Claude sessions', '--type', 'session', '--external-id', 's1.md',
                '--title', 'session', '--read', 'full')
S = str(out['id'])
rc, out, _ = mr('party', '--run', R, '--name', 'Ahmed Partner', '--email', 'ahmed@example.com', '--source', S,
                '--quote', 'Ahmed will review it')
AH = str(out['id'])
rc, out, _ = mr('new-item', '--run', R, '--type', 'reply_needed', '--title', 'Ahmed asks you to review the contract',
                '--holder', 'me', '--requested-by', AH, '--due', '2026-12-01', '--details',
                '{"request": "review the contract"}', '--source', S, '--quote', 'please review the contract')
I1 = str(out['id'])
check('an item is created', rc == 0, out)

rc, out, _ = mr('act', '--run', R, '--item', I1, '--action', 'hand_over', '--params', json.dumps({'holder': int(AH)}),
                '--source', S, '--quote', 'I sent it to Ahmed')
check('a hand-over without a new title is refused', rc == 2 and 'title' in out['refused'], out)
rc, out, _ = mr('act', '--run', R, '--item', I1, '--action', 'hand_over',
                '--params', json.dumps({'holder': int(AH), 'title': 'Ahmed reviews the contract'}),
                '--source', S, '--quote', 'I sent it to Ahmed')
check('a hand-over that does not re-decide the dates is refused', rc == 2 and 're-decides' in out['refused'], out)
rc, out, _ = mr('act', '--run', R, '--item', I1, '--action', 'hand_over',
                '--params', json.dumps({'holder': int(AH), 'title': 'Ahmed reviews the contract', 'due': None,
                                        'next_check': '2026-12-03'}), '--source', S, '--quote', 'I sent it to Ahmed')
check('a hand-over with the new title and dates is accepted', rc == 0, out)
row = door.one('SELECT t.title, f.due, f.next_check, f.holder_id FROM thing t JOIN followup f ON f.thing_id=t.id '
               'WHERE t.id=?', (int(I1),))
check('the hand-over rewrote the title and the dates', row['title'] == 'Ahmed reviews the contract' and
      row['due'] is None and row['next_check'] == '2026-12-03' and row['holder_id'] == int(AH), dict(row))
rc, out, _ = mr('act', '--run', R, '--item', I1, '--action', 'set_next_check', '--params', '{"next_check": null}')
check('removing the last date of an open item is refused', rc == 2 and 'keeps a due date' in out['refused'], out)
rc, out, _ = mr('act', '--run', R, '--item', I1, '--action', 'rename', '--params', '{"title": "Ahmed reviews v2"}',
                '--source', S, '--quote', 'v2 sent')
check('an item can be renamed, with its source', rc == 0, out)

brief = subprocess.run([sys.executable, MR, 'brief'], capture_output=True, text=True, env=ENV).stdout
check('the type names the holder when it is not the owner', 'reply needed from Ahmed Partner' in brief, brief[:600])
on_user = brief.split('## ON THE USER')[1].split('##')[0]
check('an item held by someone else is not in ON THE USER', 'Ahmed reviews v2' not in on_user, on_user)

# a check that came, and an item with no date (as old data can hold), make the end-of-run check fail
rc, out, _ = mr('new-item', '--run', R, '--type', 'commitment', '--title', 'Send Bo the plan', '--holder', 'me',
                '--promised-by', 'me', '--next-check', '2026-01-02', '--details', '{"text": "send the plan"}',
                '--source', S, '--quote', 'I will send the plan')
I2 = str(out['id'])
mr('verdict', '--run', R, '--source', S, '--verdict', 'linked')
mr('run-end', '--run', R)   # the next run meets the check that came
rc, out, _ = mr('run-start', '--kind', 'session')
R = str(out['run'])
c = sqlite3.connect(DB)
c.execute("UPDATE followup SET due=NULL, next_check=NULL WHERE thing_id=?", (int(I1),))
c.commit()
c.close()
brief = subprocess.run([sys.executable, MR, 'brief'], capture_output=True, text=True, env=ENV).stdout
check('the brief lists the check that came', f'- {I2} | next_check 2026-01-02' in brief.split('## CHECKS DUE')[1],
      brief[-800:])
rc, out, _ = mr('watermark', '--run', R, '--channel', 'Claude sessions', '--at', '2026-11-22 10:00')
mr('verdict', '--run', R, '--source', S, '--verdict', 'linked')
p = subprocess.run([sys.executable, MR, 'gate', '--run', R, '--channels-file', os.devnull], capture_output=True,
                   text=True, env=ENV)
check('the end-of-run check names the check left unhandled', p.returncode == 1 and f'Item {I2}: its next check' in
      p.stdout, p.stdout)
check('the end-of-run check names the open item with no date', f'Item {I1} is open with no due date' in p.stdout,
      p.stdout)
mr('act', '--run', R, '--item', I2, '--action', 'set_next_check', '--params', '{"next_check": "2099-01-01"}',
   '--source', S, '--quote', 'checked: nothing new')
c = sqlite3.connect(DB)
c.execute("UPDATE followup SET next_check='2099-01-01' WHERE thing_id=?", (int(I1),))
c.commit()
c.close()
p = subprocess.run([sys.executable, MR, 'gate', '--run', R, '--channels-file', os.devnull], capture_output=True,
                   text=True, env=ENV)
check('once each check is handled the end-of-run check passes', p.returncode == 0, p.stdout)

# issues
rc, out, _ = mr('issue-new', '--run', R, '--title', 'x', '--reported-by', 'run 3', '--context', 'c',
                '--description', 'short', '--source', S, '--quote', 'q')
check('an issue written as a free description is refused', rc == 2 and 'template' in out['refused'], out)
rc, out, _ = mr('issue-new', '--run', R, '--title', 'Hand-over kept the old title', '--reported-by', 'Dana, owner',
                '--context', 'run 12 message', '--what-happened', 'An item handed to Ahmed was shown as mine today.',
                '--found', 'The hand-over changed only the holder: "holder_id 1 -> 5".',
                '--asked', 'Make the hand-over rewrite the title and the dates, then check the others.',
                '--source', S, '--quote', 'Did I not send it to Ahmed?')
check('an issue the owner reported needs the owner\'s words', rc == 2 and 'owner_words' in out['refused'], out)
rc, out, _ = mr('issue-new', '--run', R, '--title', 'Hand-over kept the old title', '--reported-by', 'Dana, owner',
                '--context', 'run 12 message', '--what-happened', 'An item handed to Ahmed was shown as mine today.',
                '--found', 'The hand-over changed only the holder: "holder_id 1 -> 5".',
                '--owner-words', 'Did I not send it to Ahmed already?',
                '--asked', 'Make the hand-over rewrite the title and the dates, then check the others.',
                '--source', S, '--quote', 'Did I not send it to Ahmed?')
ISS = str(out.get('id'))
check('an issue in the template is accepted and printed back as saved',
      rc == 0 and 'Did I not send it to Ahmed already?' in out['saved_text'] and 'similar cases' in out['saved_text'],
      out)
rc, out, _ = mr('issue-append', '--run', R, '--issue', ISS, '--text', 'It happened twice more on 21 Nov.',
                '--source', S, '--quote', 'q')
p = subprocess.run([sys.executable, MR, 'issue', ISS], capture_output=True, text=True, env=ENV)
check('text added to an issue is kept word for word and shown', 'It happened twice more on 21 Nov.' in p.stdout,
      p.stdout)
rc, out, _ = mr('issue-act', '--run', R, '--issue', ISS, '--action', 'resolve', '--params',
                '{"resolution": "hand_over now requires a title and dates"}', '--source', S, '--quote', 'q')
check('an issue is resolved with how', rc == 0 and out['status'] == 'resolved', out)

rc, out, _ = mr('issue-new', '--run', R, '--title', 'Another', '--reported-by', 'Dana', '--context', 'session',
                '--what-happened', 'Something went wrong for Dana in the session today.',
                '--found', 'The brief showed the wrong section for this item.',
                '--asked', 'Find why and fix it, then check the others.', '--source', S, '--quote', 'q')
check('the owner named only by name must give her words', rc == 2 and 'owner_words' in out['refused'], out)
rc, out, _ = mr('issue-new', '--run', R, '--title', 'Found by a run', '--reported-by', 'run 12', '--context', 'gate',
                '--what-happened', 'A channel could not be read by run 12 today.',
                '--found', 'The tool was absent: "tool_absent" in the end-of-run check.',
                '--asked', 'Find why the tool was absent and fix it, then check the others.',
                '--source', S, '--quote', 'q')
check('an issue a run found may go without the owner\'s words', rc == 0, out)
rc, out, _ = mr('new-item', '--run', R, '--type', 'for_info', '--title', 'FYI x', '--holder', 'me', '--next-check',
                '2099-01-01', '--details', '{"what_happened": "x happened", "why_it_matters": "it matters"}',
                '--source', S, '--quote', 'x')
FI = str(out['id'])
rc, out, _ = mr('act', '--run', R, '--item', FI, '--action', 'convert', '--params',
                json.dumps({'new_type': 'commitment', 'title': 'Do x', 'holder': ME, 'promised_by': ME,
                            'details': {'text': 'do x'}}), '--source', S, '--quote', 'x')
check('a conversion that makes an open item with no date is refused', rc == 2 and 'keeps a due date' in
      out.get('refused', ''), out)
rc, out, _ = mr('new-item', '--run', R, '--type', 'commitment', '--title', 'Old check', '--holder', 'me',
                '--promised-by', 'me', '--next-check', '2026-01-05', '--details', '{"text": "t"}', '--source', S,
                '--quote', 'q')
OC = str(out['id'])
rc, out, _ = mr('run-end', '--run', R)
rc, out, _ = mr('run-start', '--kind', 'session')
R2 = str(out['run'])
mr('story', '--run', R2, '--item', OC, '--source', S, '--quote', 'checked: still waiting on Bo')
mr('watermark', '--run', R2, '--channel', 'Claude sessions', '--at', '2026-11-22 11:00')
p = subprocess.run([sys.executable, MR, 'gate', '--run', R2, '--channels-file', os.devnull], capture_output=True,
                   text=True, env=ENV)
check('a check handled with a story line of what was found is accepted', f'Item {OC}:' not in p.stdout, p.stdout)
R = R2

# a source read in part can be read in full later
rc, out, _ = mr('record', '--run', R, '--channel', 'Claude sessions', '--type', 'session', '--external-id', 's2.md',
                '--title', 's2', '--read', 'partial', '--reason', 'long')
rc, out, _ = mr('record', '--run', R, '--channel', 'Claude sessions', '--type', 'session', '--external-id', 's2.md',
                '--title', 's2', '--read', 'full')
check('a source recorded as partly read is moved to fully read', rc == 0 and out.get('read_state') == 'full', out)

# the published programs carry nothing of one user
code = ''.join(open(os.path.join(DB_T, f), encoding='utf-8').read() for f in ('mdb.py', 'mrun.py', 'upgrade.py'))
code = code.replace('Marionette by Hesham Elmahdy (github.com/heshamfm)', '')
check('no name, company or place of one user in the programs',
      not [w for w in ('hesham', 'odootec', 'cairo', 'هشام') if w in code.lower()])

# ============================================================== the upgrade of a 1.6 installation
git = shutil.which('git')
have = git and subprocess.run([git, 'cat-file', '-e', '4e50d13:marionette/templates/db/mdb.py'], cwd=ROOT,
                              capture_output=True).returncode == 0
if not have:
    print('SKIPPED: the upgrade checks need the repository history (git, release 1.6 at 4e50d13)')
else:
    OLD = tempfile.mkdtemp(prefix='m16_')
    os.makedirs(os.path.join(OLD, 'doors'))
    for f in ('mdb.py', 'mrun.py', 'schema_v0.1.sql', 'seed_v0.1.py', 'migrate.py', 'db_usage.md', 'doors/brief.py',
              'doors/run_gate.py', 'doors/build_status.py'):
        data = subprocess.run([git, 'show', f'4e50d13:marionette/templates/db/{f}'], cwd=ROOT, capture_output=True
                              ).stdout
        open(os.path.join(OLD, f), 'wb').write(data)
    F = tempfile.mkdtemp(prefix='inst16_')
    os.makedirs(os.path.join(F, 'tools'))
    os.makedirs(os.path.join(F, 'db'))
    for f in os.listdir(OLD):
        if f != 'doors':
            shutil.copyfile(os.path.join(OLD, f), os.path.join(F, 'tools', f))
    for f in os.listdir(os.path.join(OLD, 'doors')):
        shutil.copyfile(os.path.join(OLD, 'doors', f), os.path.join(F, 'tools', f))
    json.dump({'mode': 'live', 'memory': {'kind': 'database', 'version': '1.5'}},
              open(os.path.join(F, 'state.json'), 'w'))
    open(os.path.join(F, 'runs.log'), 'w').write('')
    # the 1.6 database, built by the 1.6 door, with an open item that has no date (as moves from files left them)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import mdb, json\n"
            "d, me, mar = mdb.init(sys.argv[2], 'Old Owner', 'old@example.com', timezone='UTC')\n"
            "d.conn.execute('BEGIN IMMEDIATE')\n"
            "t = d.new_thing('commitment', 'Undated promise')\n"
            "d.conn.execute(\"INSERT INTO followup(thing_id,status,holder_id,details) VALUES(?,'open',?,?)\", "
            "(t, me, json.dumps({'text': 'x'})))\n"
            "d.conn.execute('COMMIT')\nprint(t)\n")
    p = subprocess.run([sys.executable, '-c', code, os.path.join(F, 'tools'), os.path.join(F, 'db', 'marionette.db')],
                       capture_output=True, text=True)
    UNDATED = int(p.stdout.strip() or 0)
    check('a 1.6 installation is built', p.returncode == 0 and UNDATED, p.stderr)
    # the owner changed one program by hand
    with open(os.path.join(F, 'tools', 'run_gate.py'), 'a') as f:
        f.write('\n# changed by the owner\n')
    before = {n: sha(os.path.join(F, 'tools', n)) for n in tool_files(F)}
    dbsha = sha(os.path.join(F, 'db', 'marionette.db'))
    UP = os.path.join(DB_T, 'upgrade.py')

    rc, out, _ = run([UP, '--followup', F, '--check'])
    acts = {x['file']: x['action'] for x in out.get('files', [])} if isinstance(out, dict) else {}
    check('check: reads the installation as 1.6', rc == 0 and out['installed'] == '1.6', out)
    check('check: untouched published programs are to be replaced', acts.get('mdb.py') == 'replace' and
          acts.get('mrun.py') == 'replace', acts)
    check('check: the program the owner changed is kept', acts.get('run_gate.py') == 'keep_changed', acts)
    check('check: the new types, permission lines and the undated item are counted',
          out['data']['types_added'] == ['issue'] and out['data']['permission_lines_added'] > 0 and
          out['data']['open_items_given_a_next_check'] == 1, out.get('data'))
    check('check changes nothing', dbsha == sha(os.path.join(F, 'db', 'marionette.db')) and before == {
        n: sha(os.path.join(F, 'tools', n)) for n in tool_files(F)})

    # a run that is writing holds the upgrade back
    lk = sqlite3.connect(os.path.join(F, 'db', 'marionette.db'))
    lk.close()
    code_lock = ("import sys; sys.path.insert(0, sys.argv[1]); import mdb\n"
                 "d = mdb.Door(sys.argv[2]); r = d.do('start', 'program', type='run', params={'title': 'x'}); print(r['id'])")
    p = subprocess.run([sys.executable, '-c', code_lock, os.path.join(F, 'tools'),
                        os.path.join(F, 'db', 'marionette.db')], capture_output=True, text=True)
    RUN = p.stdout.strip()
    rc, out, _ = run([UP, '--followup', F, '--apply'])
    check('apply refuses while a run is writing', rc == 2 and 'is writing' in str(out), out)
    rc, out, _ = run([UP, '--followup', F, '--check'])
    check('check still changes nothing while a run writes', rc == 0)
    code_end = ("import sys; sys.path.insert(0, sys.argv[1]); import mdb\n"
                "d = mdb.Door(sys.argv[2]); d.do('close', 'program', int(sys.argv[3]))")
    subprocess.run([sys.executable, '-c', code_end, os.path.join(F, 'tools'), os.path.join(F, 'db', 'marionette.db'),
                    RUN], capture_output=True, text=True)

    rc, out, err = run([UP, '--followup', F, '--apply', '--approval', 'yes, upgrade'])
    check('apply succeeds', rc == 0 and out.get('applied'), (out, err))
    check('apply: the copy before the upgrade holds the database and the programs', rc == 0 and
          os.path.exists(os.path.join(F, out['copy'], 'db', 'marionette.db')) and
          sha(os.path.join(F, out['copy'], 'tools', 'mdb.py')) == before['mdb.py'], out)
    check('apply: the untouched programs are the new ones',
          sha(os.path.join(F, 'tools', 'mdb.py')) == sha(os.path.join(DB_T, 'mdb.py')) and
          sha(os.path.join(F, 'tools', 'mrun.py')) == sha(os.path.join(DB_T, 'mrun.py')))
    check('apply: the owner\'s changed program is untouched and the new one is beside it',
          sha(os.path.join(F, 'tools', 'run_gate.py')) == before['run_gate.py'] and
          os.path.exists(os.path.join(F, 'tools', 'run_gate.py.new-' + mdb.VERSION)))
    c = sqlite3.connect(os.path.join(F, 'db', 'marionette.db'))
    check('apply: the release is recorded in the database',
          c.execute("SELECT value FROM meta WHERE key='marionette_version'").fetchone()[0] == mdb.VERSION)
    check('apply: the issue type and the new permission lines are there',
          c.execute("SELECT 1 FROM type WHERE code='issue'").fetchone() and
          c.execute("SELECT 1 FROM action_rule WHERE scope='followup' AND action='rename'").fetchone())
    check('apply: the open item with no date got a next check',
          c.execute('SELECT next_check FROM followup WHERE thing_id=?', (UNDATED,)).fetchone()[0] is not None)
    check('apply: the change is in the audit trail as a program action',
          c.execute("SELECT 1 FROM audit WHERE thing_id=? AND field='followup.next_check' AND actor='program'",
                    (UNDATED,)).fetchone())
    c.close()
    check('apply: state.json and runs.log say so',
          json.load(open(os.path.join(F, 'state.json')))['memory']['version'] == mdb.VERSION and
          ('upgrade 1.6 -> ' + mdb.VERSION) in open(os.path.join(F, 'runs.log')).read())
    rc, out, _ = run([os.path.join(F, 'tools', 'mrun.py'), 'brief'], cwd=F)
    check('the upgraded installation runs (brief)', rc == 0 and 'ON THE USER' in str(out), str(out)[:300])
    rc, out, _ = run([UP, '--followup', F, '--apply'])
    check('a second apply changes nothing', rc == 0 and out.get('applied') is False, out)

    rc, out, _ = run([UP, '--followup', F, '--undo'])
    check('undo succeeds', rc == 0 and out.get('undone') and out['back_on'] == '1.6', out)
    check('undo counts only the changes made after the upgrade, not the upgrade\'s own',
          out.get('changes_after_upgrade_kept_aside') == 0, out)
    check('undo: the programs are back as they were',
          all(sha(os.path.join(F, 'tools', n)) == h for n, h in before.items()))
    c = sqlite3.connect(os.path.join(F, 'db', 'marionette.db'))
    check('undo: the database is back as it was',
          not c.execute("SELECT 1 FROM type WHERE code='issue'").fetchone() and
          c.execute('SELECT next_check FROM followup WHERE thing_id=?', (UNDATED,)).fetchone()[0] is None)
    c.close()
    check('undo deletes nothing: the upgraded database is kept aside',
          os.path.exists(os.path.join(F, out['aside'], 'db', 'marionette.db')))
    # the session doing the upgrade has its own run open: it names it, and the upgrade goes on
    p = subprocess.run([sys.executable, '-c', code_lock, os.path.join(F, 'tools'),
                        os.path.join(F, 'db', 'marionette.db')], capture_output=True, text=True)
    OWN = p.stdout.strip()
    rc, out, _ = run([UP, '--followup', F, '--apply', '--run', OWN])
    check('after an undo the installation can upgrade again, by the session whose own run is open',
          rc == 0 and out.get('applied'), out)
    run([UP, '--followup', F, '--undo', '--run', OWN])

    # a program of the core set changed by the owner: nothing is changed, the owner decides
    with open(os.path.join(F, 'tools', 'mrun.py'), 'a') as f:
        f.write('\n# changed by the owner\n')
    core_before = sha(os.path.join(F, 'tools', 'mdb.py'))
    rc, out, _ = run([UP, '--followup', F, '--apply', '--run', OWN])
    check('a changed core program stops the upgrade before anything changes',
          rc == 2 and 'mrun.py' in out.get('refused', '') and sha(os.path.join(F, 'tools', 'mdb.py')) == core_before,
          out)
    shutil.copyfile(os.path.join(OLD, 'mrun.py'), os.path.join(F, 'tools', 'mrun.py'))

    # an upgrade that stops half way (another writer holds the database during the data step) can be undone
    import threading
    import time
    hold = sqlite3.connect(os.path.join(F, 'db', 'marionette.db'), isolation_level=None, check_same_thread=False)
    started = threading.Event()

    def writer():
        hold.execute('BEGIN IMMEDIATE')
        started.set()
        time.sleep(12)
        hold.execute('ROLLBACK')
    th = threading.Thread(target=writer)
    th.start()
    started.wait()
    rc, out, _ = run([UP, '--followup', F, '--apply', '--run', OWN])
    th.join()
    check('an upgrade stopped half way says so, with no traceback', rc == 2 and 'half way' in out.get('refused', ''),
          out)
    rc, out, _ = run([UP, '--followup', F, '--apply', '--run', OWN])
    check('a second attempt is refused until the half-done upgrade is undone',
          rc == 2 and '--undo' in out.get('refused', ''), out)
    rc, out, _ = run([UP, '--followup', F, '--undo', '--run', OWN])
    check('undo after a half-done upgrade puts the programs back',
          rc == 0 and sha(os.path.join(F, 'tools', 'mdb.py')) == before['mdb.py'], out)
    rc, out, _ = run([UP, '--followup', F, '--apply', '--run', OWN])
    check('then the upgrade succeeds', rc == 0 and out.get('applied'), out)

bad = [r for r in res if not r[1]]
for name, good, info in res:
    print((' - ' if good else ' X ') + name + ('' if good else ' => ' + info))
print(f'bad {len(bad)} of {len(res)}')
sys.exit(1 if bad else 0)
