"""Tests for mdb.py, the Marionette database door (Marionette 1.5, updated for 1.7).

Run from the repository root:
    python3 tests/test_db_door.py [work_folder]
It creates a fresh database in the work folder (default: a new temporary folder),
prints one line per check and ends with "bad N of M".
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'marionette', 'templates', 'db')
sys.path.insert(0, HERE)
import mdb  # noqa: E402

work = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='mdbtest_')
os.makedirs(work, exist_ok=True)
DB = os.path.join(work, 'test_marionette.db')
if os.path.exists(DB):
    os.remove(DB)

CLOCK = ['2026-11-17 10:00:00']
# a user whose week runs Sunday to Thursday, so the weekly checks below fall on Sunday
door, ME, MAR = mdb.init(DB, 'Test User', 'user@example.com', now=lambda: CLOCK[0],
                         workdays=['sun', 'mon', 'tue', 'wed', 'thu'], week_start='sun')
results = []


def audits():
    return door.one('SELECT count(*) FROM audit')[0]


def things():
    return door.one('SELECT count(*) FROM thing')[0]


def ok(name, fn):
    a0 = audits()
    try:
        r = fn()
        if audits() <= a0:
            results.append((name, 'NO AUDIT LINE'))
        else:
            results.append((name, 'accepted'))
        return r
    except Exception as e:
        results.append((name, 'WRONGLY REFUSED: ' + str(e)[:110]))


def bad(name, fn, expect):
    a0, t0 = audits(), things()
    try:
        fn()
        results.append((name, 'NOT REFUSED'))
    except (mdb.Refused, sqlite3.DatabaseError) as e:
        msg = str(e)
        if expect.lower() not in msg.lower():
            results.append((name, f'REFUSED FOR ANOTHER REASON: {msg[:110]}'))
        elif audits() != a0 or things() != t0:
            results.append((name, 'REFUSED BUT LEFT ROWS BEHIND'))
        else:
            results.append((name, 'refused: ' + msg[:90]))
    except Exception as e:
        results.append((name, 'CRASHED: ' + repr(e)[:110]))


def check(name, cond, detail=''):
    results.append((name, 'yes' if cond else 'NO ' + detail))


USER_EV = {}


def do(*a, **k):
    # every action in the user's name carries his words from a session, unless the test gives its own
    actor = a[1] if len(a) > 1 else k.get('actor')
    if actor == 'user' and 'evidence' not in k and USER_EV:
        k['evidence'] = USER_EV
    return door.do(*a, **k)


# ---------- the database itself ----------
check('journal mode is TRUNCATE', door.one('PRAGMA journal_mode')[0] == 'truncate')
check('foreign keys are on', door.one('PRAGMA foreign_keys')[0] == 1)
check('4 groups', door.one('SELECT count(*) FROM grp')[0] == 4)
check('23 types', door.one('SELECT count(*) FROM type')[0] == 23)
check('every type has an Arabic name and statuses',
      door.one("SELECT count(*) FROM type WHERE name_ar='' OR json_array_length(statuses)=0")[0] == 0)
bad('create the database a second time', lambda: mdb.init(DB, 'X'), 'already exists')
check('the user and Marionette are parties',
      door.one('SELECT count(*) FROM party WHERE thing_id IN (?,?)', (ME, MAR))[0] == 2)

# every permission line has a program step, and every action of the specification has a permission line
missing = sorted({r['action'] for r in door.conn.execute('SELECT DISTINCT action FROM action_rule')
                  if not hasattr(door, 'a_' + r['action'])})
check('every permission line has a program step', not missing, str(missing))
SPEC = {
    'followup': ['create', 'hand_over', 'change_due', 'defer', 'complete', 'reopen', 'merge', 'cancel', 'mark_late'],
    'decision_needed': ['record_decision'], 'for_info': ['create', 'show', 'mark_seen', 'convert'],
    'reminder': ['create', 'show', 'mark_seen', 'defer', 'cancel'],
    'draft': ['create', 'edit', 'send', 'mark_sent_as_is', 'mark_sent_edited', 'abandon'],
    'deferred_check': ['create', 'execute', 'cancel'],
    'party': ['create', 'confirm', 'edit', 'link_org', 'change_relation', 'merge', 'deactivate'],
    'area': ['create', 'rename', 'archive'], 'project': ['create', 'pause', 'end'],
    'channel': ['create', 'update_watermark', 'mark_unavailable', 'stop'],
    'source': ['record', 'read', 'verdict', 'correct_verdict', 'reset_verdict'],
    'external_record': ['update_state'], 'file': ['register', 'mark_missing', 'propose_delete', 'delete'],
    'decision': ['create', 'supersede'], 'rule': ['create', 'edit_text', 'pause', 'cancel'],
    'job': ['create', 'edit', 'execute', 'mark_period_done', 'pause'], 'run': ['start', 'close'],
}
gaps = [f'{s}.{a}' for s, acts in SPEC.items() for a in acts
        if not door.one('SELECT 1 FROM action_rule WHERE scope=? AND action=?', (s, a))]
check('every action of the specification has a permission line', not gaps, str(gaps))

# nothing of one user's own setup is written in the program
code = (open(os.path.join(HERE, 'mdb.py'), encoding='utf-8').read()
        + open(os.path.join(HERE, 'seed_v0.1.py'), encoding='utf-8').read())
code = code.replace('Marionette by Hesham Elmahdy (github.com/heshamfm)', '')  # the author's notice, required
words = [w for w in ('linkedin', 'odoo', 'gmail', 'hesham', 'odootec', 'meetgeek', 'plaud', 'google', 'cairo')
         if re.search(w, code, re.I)]
check('no channel, company, person or place of one user in the program', not words, str(words))

# ---------- the user's words ----------
SCH = int(door.meta('sessions_channel_id'))
check('the channel of sessions with Claude exists from the start', door.thing(SCH)['type'] == 'channel')
SESS0 = door.do('record', 'claude', type='session', params={'title': 'session with the user', 'channel_id': SCH,
                                                            'external_id': 'session-1'})['id']
bad('an action in the name of the user with no words of his', lambda: door.do(
    'create', 'user', type='area', params={'title': 'x'}), 'his own words')
USER_EV.update({'source': SESS0, 'quote': 'Go ahead.', 'position': 'turn 3'})
CEV = {'source': SESS0, 'quote': 'Sam from Acme will send the form.'}
bad('Claude creates a party with no evidence', lambda: door.do('create', 'claude', type='party', params={
    'title': 'Guess', 'kind': 'person'}), 'needs evidence')

# ---------- reference records ----------
bad('Claude adds a channel', lambda: do('create', 'claude', type='channel',
                                        params={'title': 'mail', 'connection': 'mcp'}), 'only by: user')
MAIL = ok('the user adds a channel', lambda: do('create', 'user', type='channel',
                                                params={'title': 'mail', 'connection': 'mcp'}))['id']
CHAT = ok('the user adds a second channel', lambda: do('create', 'user', type='channel',
                                                       params={'title': 'chat', 'connection': 'mcp'}))['id']
bad('the user creates a party with no kind', lambda: do('create', 'user', type='party',
                                                        params={'title': 'x'}), 'person, an org')
bad('Claude sets the relation of a new party', lambda: do('create', 'claude', type='party', evidence=CEV, params={
    'title': 'Acme', 'kind': 'org', 'relation': 'client'}), 'only the user sets')
ACME = ok('Claude creates an organisation', lambda: do('create', 'claude', type='party', evidence=CEV, params={
    'title': 'Acme', 'kind': 'org', 'handles': [{'kind': 'domain', 'value': 'acme.example'}]}))['id']
SAM = ok('Claude creates a person with an email', lambda: do('create', 'claude', type='party', evidence=CEV, params={
    'title': 'Sam', 'kind': 'person', 'handles': [{'kind': 'email', 'value': 'sam@acme.example'}]}))['id']
SAM2 = ok('Claude creates a second record for the same person', lambda: do('create', 'claude', type='party', evidence=CEV,
                                                                          params={'title': 'S. Smith',
                                                                                  'kind': 'person'}))['id']
bad('the same email on two parties, other letter case', lambda: do('edit', 'user', target=SAM2, params={
    'handles': [{'kind': 'email', 'value': 'SAM@acme.example'}]}), 'merge the two parties')
bad('Claude changes a party relation', lambda: do('change_relation', 'claude', target=ACME,
                                                  params={'relation': 'client'}), 'only by: user')
ok('the user changes a party relation', lambda: do('change_relation', 'user', target=ACME,
                                                   params={'relation': 'client'}))
bad('Claude deactivates a party', lambda: do('deactivate', 'claude', target=SAM2), 'only by: user')
bad('the user deactivates the user party', lambda: do('deactivate', 'user', target=ME), 'never deactivated')
bad('Claude creates an area', lambda: do('create', 'claude', type='area', params={'title': 'Sales'}), 'only by: user')
AREA = ok('the user creates an area', lambda: do('create', 'user', type='area', params={'title': 'Sales'}))['id']
bad('a project with no area', lambda: do('create', 'user', type='project', params={'title': 'P'}), 'missing: area_id')
PROJ = ok('the user creates a project', lambda: do('create', 'user', type='project',
                                                   params={'title': 'Acme rollout', 'area_id': AREA}))['id']

# ---------- sources ----------
RUN = ok('the program starts a run', lambda: do('start', 'program', type='run'))['id']
bad('Claude starts a run', lambda: do('start', 'claude', type='run'), 'only by: program')
SESS = ok('Claude records a session with Claude', lambda: do('record', 'claude', type='session', run=RUN, params={
    'title': 'session', 'channel_id': CHAT, 'external_id': 's1'}))['id']
MSG = ok('Claude records a message', lambda: do('record', 'claude', type='message', run=RUN, params={
    'title': 'Acme asks for a proposal', 'channel_id': MAIL, 'external_id': 'T1'}))['id']
bad('the same source recorded twice', lambda: do('record', 'claude', type='message', params={
    'title': 'again', 'channel_id': MAIL, 'external_id': 'T1'}), 'already recorded as thing')
bad('a source on something that is not a channel', lambda: do('record', 'claude', type='message', params={
    'title': 'x', 'channel_id': ACME, 'external_id': 'T9'}), 'not a channel')
bad('an external record without its kind', lambda: do('record', 'claude', type='external_record', params={
    'title': 'x', 'channel_id': MAIL, 'external_id': 'R1'}), 'record_kind')
bad('an action in the name of the user resting on an email, not on his words', lambda: door.do(
    'create', 'user', type='area', evidence={'source': MSG, 'quote': 'x'}, params={'title': 'x'}),
    'never on another source')
bad('an action in the name of the user resting on an inference', lambda: door.do(
    'create', 'user', type='area', evidence={**USER_EV, 'inferred': True}, params={'title': 'x'}),
    'never on another source or an inference')
bad('a verdict on a source not read in full', lambda: do('verdict', 'claude', target=MSG,
                                                         params={'verdict': 'ignored', 'reason': 'x'}), 'read in full')
bad('a partial read with no reason', lambda: do('read', 'claude', target=MSG, params={'read_state': 'partial'}),
    'missing: reason')
ok('Claude reads the message in full', lambda: do('read', 'claude', target=MSG, params={'read_state': 'full'}))
bad('the user records a verdict', lambda: do('verdict', 'user', target=MSG, params={'verdict': 'ignored'}),
    'only by: claude')
bad('ignored with no reason', lambda: do('verdict', 'claude', target=MSG, params={'verdict': 'ignored'}),
    'missing: reason')
bad('linked with nothing tying it to a thing', lambda: do('verdict', 'claude', target=MSG,
                                                          params={'verdict': 'linked'}), 'tying this source')
EV = {'source': MSG, 'quote': 'We will send the signed form by Thursday.', 'position': 'line 3'}

# ---------- follow-up things ----------
bad('Claude opens a commitment with no evidence', lambda: do('create', 'claude', type='commitment', params={
    'title': 'Acme sends the form', 'holder': SAM, 'promised_by': SAM, 'details': {'text': 'x'}}), 'needs evidence')
bad('a commitment with no text', lambda: do('create', 'claude', type='commitment', evidence=EV, params={
    'title': 'Acme sends the form', 'holder': SAM, 'promised_by': SAM}), 'needs in details: text')
bad('a commitment with no promiser', lambda: do('create', 'claude', type='commitment', evidence=EV, params={
    'title': 'Acme sends the form', 'holder': SAM, 'details': {'text': 'x'}}), 'promised_by')
bad('a follow-up thing with no next step holder', lambda: do('create', 'claude', type='commitment', evidence=EV,
                                                             params={'title': 't', 'promised_by': SAM,
                                                                     'details': {'text': 'x'}}), 'missing: holder')
bad('a next step holder that is not a party', lambda: do('create', 'claude', type='commitment', evidence=EV,
                                                         params={'title': 't', 'holder': AREA, 'promised_by': SAM,
                                                                 'details': {'text': 'x'}}), 'is not a party')
C1 = ok('Claude opens a commitment with evidence', lambda: do('create', 'claude', type='commitment', evidence=EV,
                                                              params={'title': 'Acme sends the signed form',
                                                                      'holder': SAM, 'promised_by': SAM,
                                                                      'promised_to': ME, 'due': '2026-11-19',
                                                                      'area_id': AREA, 'project_id': PROJ,
                                                                      'details': {'text': EV['quote']}}))['id']
check('the commitment starts open', door.status_of(C1) == 'open')
check('the creation is tied to its evidence in the audit trail',
      door.one("SELECT count(*) FROM audit WHERE thing_id=? AND evidence_id IS NOT NULL", (C1,))[0] >= 1)
check('the promiser and the beneficiary are linked by role',
      door.one("SELECT count(*) FROM link WHERE from_id=? AND role IN ('promised_by','promised_to')", (C1,))[0] == 2)
ok('Claude links the message after the thing exists', lambda: do('verdict', 'claude', target=MSG,
                                                                 params={'verdict': 'linked'}))
bad('Claude corrects a verdict with no evidence', lambda: do('correct_verdict', 'claude', target=MSG,
                                                             params={'verdict': 'ignored', 'reason': 'x'}),
    'needs evidence')
bad('the user records a verdict correction to an unknown value', lambda: do('correct_verdict', 'user', target=MSG,
                                                                            params={'verdict': 'maybe'}),
    'linked, informed or ignored')
bad('Claude defers a thing', lambda: do('defer', 'claude', target=C1), 'only by: user')
bad('Claude hands the next step over with no evidence', lambda: do('hand_over', 'claude', target=C1,
                                                                   params={'holder': ME}), 'needs evidence')
bad('a hand-over with no new title (1.7)', lambda: do('hand_over', 'claude', target=C1, evidence=EV,
                                                     params={'holder': ME}), 'missing: title')
bad('a hand-over that does not re-decide the dates (1.7)', lambda: do('hand_over', 'claude', target=C1, evidence=EV,
                                                                     params={'holder': ME, 'title': 'T'}),
    're-decides the dates')
ok('Claude hands the next step over with evidence, a new title and dates', lambda: do(
    'hand_over', 'claude', target=C1, evidence=EV,
    params={'holder': ME, 'title': door.thing(C1)['title'], 'due': door.one(
        'SELECT due FROM followup WHERE thing_id=?', (C1,))[0] or '2026-12-01'}))
check('the change of holder keeps the old and the new value',
      door.one("SELECT count(*) FROM audit WHERE thing_id=? AND field='followup.holder_id' AND old_value=? "
               "AND new_value=?", (C1, str(SAM), str(ME)))[0] == 1)
ok('the user defers a thing', lambda: do('defer', 'user', target=C1))
bad('a status not in the list of the type', lambda: door.conn.execute(
    "UPDATE followup SET status='seen' WHERE thing_id=?", (C1,)) and (_ for _ in ()).throw(mdb.Refused('x')),
    'status not allowed')
bad('Claude completes with no evidence', lambda: do('complete', 'claude', target=C1), 'needs evidence')
bad('a close reason outside the list', lambda: do('complete', 'user', target=C1, params={'close_reason': 'x'}),
    'close reason is')
ok('Claude completes with evidence', lambda: do('complete', 'claude', target=C1, evidence=EV))
check('the close reason is recorded', door.one('SELECT close_reason FROM followup WHERE thing_id=?',
                                               (C1,))[0] == 'done')
bad('complete a thing already done', lambda: do('complete', 'user', target=C1), 'not allowed while the status')
ok('Claude reopens with evidence', lambda: do('reopen', 'claude', target=C1, evidence=EV))
bad('Claude cancels', lambda: do('cancel', 'claude', target=C1), 'only by: user')
ok('the user cancels', lambda: do('cancel', 'user', target=C1))
bad('Claude reopens a thing the user cancelled', lambda: do('reopen', 'claude', target=C1, evidence=EV),
    'not allowed while the status is "cancelled"')
ok('the user reopens it', lambda: do('reopen', 'user', target=C1))

# late
bad('mark late before the due date', lambda: do('mark_late', 'program', target=C1), 'not late')
CLOCK[0] = '2026-11-20 09:00:00'
bad('Claude marks late', lambda: do('mark_late', 'claude', target=C1), 'only by: program')
ok('the program marks late after the due date', lambda: do('mark_late', 'program', target=C1))
bad('mark late twice', lambda: do('mark_late', 'program', target=C1), 'already marked late')
check('the late thing is listed as due', any(r['id'] == C1 and r['why'] == 'late' for r in door.due()))

# merge
C2 = ok('Claude opens a second commitment from the same message', lambda: do(
    'create', 'claude', type='commitment', evidence=EV, params={'title': 'same promise', 'holder': SAM,
                                                               'promised_by': SAM, 'details': {'text': 'x'}}))['id']
EV2 = {'source': SESS, 'quote': 'another thing', 'position': 'minute 4'}
C3 = ok('Claude opens a commitment from another source', lambda: do(
    'create', 'claude', type='commitment', evidence=EV2, params={'title': 'other', 'holder': ME,
                                                                'promised_by': ME, 'details': {'text': 'y'}}))['id']
bad('Claude merges things from different sources', lambda: do('merge', 'claude', target=C3, evidence=EV2,
                                                              params={'into': C1}), 'same source')
ok('Claude merges things from the same source', lambda: do('merge', 'claude', target=C2, evidence=EV,
                                                           params={'into': C1}))
check('the merged thing is done, reason merged, linked to the kept one',
      door.status_of(C2) == 'done' and door.one('SELECT close_reason FROM followup WHERE thing_id=?',
                                                (C2,))[0] == 'merged'
      and door.one("SELECT 1 FROM link WHERE from_id=? AND to_id=? AND role='merged_into'", (C2, C1)))

# decision needed, reply needed with Marionette as the one asking
Q = ok('Claude opens a question from Marionette to the user', lambda: do(
    'create', 'claude', type='reply_needed', evidence=EV2, params={'title': 'which record?', 'holder': ME,
                                                                  'requested_by': MAR,
                                                                  'details': {'request': 'Which record?'}}))['id']
D1 = ok('Claude opens a decision needed', lambda: do('create', 'claude', type='decision_needed', evidence=EV2, params={
    'title': 'keep or drop?', 'holder': ME, 'details': {'question': 'Keep it?', 'options': ['keep', 'drop'],
                                                        'recommendation': 'keep'}}))['id']
bad('record a decision with no text', lambda: do('record_decision', 'user', target=D1), 'missing: decision')
ok('the user records the decision', lambda: do('record_decision', 'user', target=D1, params={'decision': 'keep'}))
check('a recorded decision closes the thing', door.status_of(D1) == 'done')
bad('record a decision on a commitment', lambda: do('record_decision', 'user', target=C1,
                                                    params={'decision': 'x'}), 'no action "record_decision"')

# for information
FI = ok('Claude opens a for-information thing', lambda: do('create', 'claude', type='for_info', evidence=EV, params={
    'title': 'Acme changed its address', 'holder': ME,
    'details': {'what_happened': 'new address', 'why_it_matters': 'invoices'}}))['id']
check('for information starts as new', door.status_of(FI) == 'new')
ok('the program shows it in the report', lambda: do('show', 'program', target=FI))
bad('complete a for-information thing', lambda: do('complete', 'user', target=FI), 'not allowed while the status')
bad('Claude marks it seen', lambda: do('mark_seen', 'claude', target=FI), 'only by: user')
NEWC = ok('Claude converts it into a reply needed', lambda: do('convert', 'claude', target=FI, evidence=EV, params={
    'new_type': 'reply_needed', 'title': 'answer Acme', 'holder': ME, 'requested_by': SAM, 'next_check': '2026-11-20',
    'details': {'request': 'confirm the new address'}}))
bad('a conversion into an open item with no date (1.7)', lambda: do('convert', 'claude', target=FI, evidence=EV, params={
    'new_type': 'reply_needed', 'title': 'answer Acme again', 'holder': ME, 'requested_by': SAM,
    'details': {'request': 'confirm'}}), 'keeps a due date')
check('the converted thing is new and linked', NEWC and door.one(
    "SELECT 1 FROM link WHERE from_id=? AND to_id=? AND role='converted_from'", (NEWC['new_id'], FI)))
ok('the user marks it seen', lambda: do('mark_seen', 'user', target=FI))
M2 = do('record', 'claude', type='message', run=RUN, params={'title': 'news', 'channel_id': MAIL,
                                                             'external_id': 'T2'})['id']
do('read', 'claude', target=M2, params={'read_state': 'full'})
ok('Claude ignores a newsletter with a reason', lambda: do('verdict', 'claude', target=M2, params={
    'verdict': 'ignored', 'reason': 'newsletter'}))
bad('an informed verdict with no for-information thing', lambda: do('correct_verdict', 'claude', target=M2,
                                                                    evidence=EV, params={'verdict': 'informed'}),
    'tying this source')
bad('clear an ignored verdict with no proof the user acted', lambda: do(
    'reset_verdict', 'program', target=M2, params={'reason': 'x'}), 'act_source')
bad('the proof is an incoming message', lambda: do(
    'reset_verdict', 'program', target=M2, params={'reason': 'x', 'act_source': MSG}), 'user sent')
ok('the program clears an ignored verdict when the user acted on the source', lambda: do(
    'reset_verdict', 'program', target=M2, params={'reason': 'the user said he replied', 'act_source': SESS0}))
check('the cleared source has no verdict again', door.status_of(M2) == 'none')
do('verdict', 'claude', target=M2, params={'verdict': 'ignored', 'reason': 'newsletter'})

# reminder
bad('a reminder with no date', lambda: do('create', 'user', type='reminder', params={
    'title': 'call', 'holder': ME, 'details': {'text': 'call Sam'}}), 'needs a due date')
RM = ok('the user creates a reminder', lambda: do('create', 'user', type='reminder', params={
    'title': 'call Sam', 'holder': ME, 'due': '2026-11-22', 'details': {'text': 'call Sam'}}))['id']
bad('show a reminder before its date', lambda: do('show', 'program', target=RM), 'not due yet')
CLOCK[0] = '2026-11-22 08:00:00'
check('the reminder is listed as due on its day', any(r['id'] == RM for r in door.due()))
ok('the program shows the reminder on its day', lambda: do('show', 'program', target=RM))
bad('Claude defers the reminder', lambda: do('defer', 'claude', target=RM, params={'due': '2026-11-25'}),
    'only by: user')
bad('the user defers it with no new date', lambda: do('defer', 'user', target=RM), 'missing: due')
ok('the user defers it to a new date', lambda: do('defer', 'user', target=RM, params={'due': '2026-11-25'}))
check('a deferred reminder is scheduled again', door.status_of(RM) == 'scheduled')

# drafts and sending
bad('a reply draft with nothing it answers', lambda: do('create', 'claude', type='draft', params={
    'title': 'reply', 'holder': ME, 'details': {'text': 'Hi', 'channel_id': MAIL, 'recipients': ['sam'],
                                               'kind': 'reply'}}), 'replies_to')
bad('the user writes a draft through the program', lambda: do('create', 'user', type='draft', params={
    'title': 'x', 'holder': ME, 'details': {'text': 'Hi', 'channel_id': MAIL, 'recipients': ['s'], 'kind': 'new'}}),
    'only by: claude')
DR = ok('Claude writes a reply draft', lambda: do('create', 'claude', type='draft', params={
    'title': 'reply to Acme', 'holder': ME, 'details': {'text': 'Thank you.', 'channel_id': MAIL,
                                                       'recipients': ['sam@acme.example'], 'kind': 'reply',
                                                       'replies_to': MSG}}))['id']
bad('Claude sends a draft that no job may send', lambda: do('send', 'claude', target=DR), 'draft only')
bad('a job allowed to send with no approved text', lambda: do('create', 'user', type='job', params={
    'title': 'j', 'instructions': 'i', 'schedule': {'every': 'day', 'at': '07:30'},
    'send_permission': 'approved_text'}), 'CHECK')
bad('a job schedule that is not understood', lambda: do('create', 'user', type='job', params={
    'title': 'j', 'instructions': 'i', 'schedule': 'daily'}), 'schedule is JSON')
bad('a weekly job with no day', lambda: do('create', 'user', type='job', params={
    'title': 'j', 'instructions': 'i', 'schedule': {'every': 'week', 'at': '09:00'}}), 'names its day')
JOB = ok('the user creates a job that may send one approved text', lambda: do('create', 'user', type='job', params={
    'title': 'polite decline', 'instructions': 'decline politely', 'schedule': {'every': 'day', 'at': '07:30'},
    'channels': [CHAT],
    'send_permission': 'approved_text', 'approved_texts': ['Thank you, not at this time.']}))['id']
DR2 = ok('Claude writes a draft for that job', lambda: do('create', 'claude', type='draft', params={
    'title': 'decline', 'holder': ME, 'details': {'text': 'Thank you, not at this time.', 'channel_id': CHAT,
                                                 'recipients': ['x'], 'kind': 'new', 'job_id': JOB}}))['id']
bad('Claude sends it on a channel that is draft only', lambda: do('send', 'claude', target=DR2),
    'channel of this draft is draft only')
door.conn.execute("UPDATE channel SET send_policy='approved_text' WHERE thing_id=?", (CHAT,))
ok('Claude sends the approved text on a channel that allows it', lambda: do('send', 'claude', target=DR2))
DR4 = do('create', 'claude', type='draft', params={'title': 'later', 'holder': ME, 'due': '2026-12-30', 'details': {
    'text': 'Later', 'channel_id': CHAT, 'recipients': ['x'], 'kind': 'new'}})['id']
bad('Claude abandons its draft before its time has passed', lambda: do('abandon', 'claude', target=DR4,
                                                                       params={'reason': 'x'}), 'time has passed')
DR3 = do('create', 'claude', type='draft', params={'title': 'decline 2', 'holder': ME, 'due': '2026-11-21', 'details': {
    'text': 'Something else', 'channel_id': CHAT, 'recipients': ['x'], 'kind': 'new', 'job_id': JOB}})['id']
bad('Claude sends a text the user did not approve', lambda: do('send', 'claude', target=DR3), 'user approved')
bad('Claude abandons its draft with no reason', lambda: do('abandon', 'claude', target=DR3), 'missing: reason')
ok('Claude abandons its own draft with a reason', lambda: do('abandon', 'claude', target=DR3,
                                                             params={'reason': 'its time passed'}))
DR5 = do('create', 'claude', type='draft', params={'title': 'v1', 'holder': ME, 'details': {
    'text': 'v1', 'channel_id': CHAT, 'recipients': ['x'], 'kind': 'new'}})['id']
DR6 = do('create', 'claude', type='draft', params={'title': 'v2', 'holder': ME, 'details': {
    'text': 'v2', 'channel_id': CHAT, 'recipients': ['x'], 'kind': 'new'}})['id']
bad('Claude abandons a draft as replaced by an older one', lambda: do('abandon', 'claude', target=DR6,
    params={'reason': 'r', 'superseded_by': DR5}), 'newer draft')
ok('Claude abandons a draft a newer draft replaced', lambda: do('abandon', 'claude', target=DR5,
    params={'reason': 'replaced', 'superseded_by': DR6}))
check('the replaced draft is linked to the newer one', door.one(
    "SELECT 1 FROM link WHERE from_id=? AND to_id=? AND role='superseded_by'", (DR5, DR6)) is not None)
bad('Claude abandons a draft gone from the mail without evidence', lambda: do('abandon', 'claude', target=DR4,
    params={'reason': 'gone', 'gone_from_mail': True}), 'with evidence')
ok('Claude abandons a draft gone from the mail, with evidence', lambda: do('abandon', 'claude', target=DR4,
    params={'reason': 'gone', 'gone_from_mail': True}, evidence=EV))
ok('the program records a draft sent with changes', lambda: do('mark_sent_edited', 'program', target=DR,
                                                               params={'sent_text': 'Thanks!'}))

# deferred check
bad('a deferred check with no date', lambda: do('create', 'claude', type='deferred_check', evidence=EV, params={
    'title': 'wait 10 days', 'holder': MAR, 'details': {'condition': 'c', 'if_true': 'a', 'if_false': 'b'}}),
    'next_check')
DC = ok('Claude creates a deferred check', lambda: do('create', 'claude', type='deferred_check', evidence=EV, params={
    'title': 'wait 10 days', 'holder': MAR, 'next_check': '2026-12-02',
    'details': {'condition': 'no reply', 'if_true': 'disconnect', 'if_false': 'nothing'}}))['id']
ok('the check is linked to what it is about', lambda: do('link', 'claude', target=DC, evidence=EV,
                                                         params={'to_id': C1, 'role': 'about'}))
bad('execute the check before its date', lambda: do('execute', 'program', target=DC, params={'result': True}),
    'not due yet')
bad('Claude cancels the check while its thing is open', lambda: do('cancel', 'claude', target=DC),
    'has ended')
CLOCK[0] = '2026-12-02 09:00:00'
bad('execute with no result', lambda: do('execute', 'program', target=DC), 'true or false')
ok('the program executes the check on its date', lambda: do('execute', 'program', target=DC, params={'result': False}))

# party merge
bad('Claude merges parties on a similar name', lambda: do('merge', 'claude', target=SAM2, evidence=EV,
                                                          params={'into': SAM}), 'same email')
EVM = {'source': MSG, 'quote': 'From: S. Smith <sam@acme.example>'}
ok('Claude merges parties on the same email shown in the quote', lambda: do(
    'merge', 'claude', target=SAM2, evidence=EVM, params={'into': SAM, 'email': 'sam@acme.example'}))
check('the merged party is inactive and linked', door.status_of(SAM2) == 'inactive' and door.one(
    "SELECT 1 FROM link WHERE from_id=? AND to_id=? AND role='merged_into'", (SAM2, SAM)))
bad('merge the user party away', lambda: do('merge', 'user', target=ME, params={'into': SAM}), 'never merged')
ok('Claude links a person to an organisation', lambda: do('link_org', 'claude', target=SAM, evidence=EVM,
                                                          params={'org_id': ACME, 'role_in_org': 'buyer'}))
ok('Claude confirms a party with evidence', lambda: do('confirm', 'claude', target=SAM, evidence=EVM))

# files
FH = 'a3f9c2' + '0' * 58
F1 = ok('the program registers a stored file', lambda: do('register', 'program', type='file', params={
    'original_name': 'call.mp4', 'stored_name': 'video/2024/20241101_Rec_Call_a3f9c2.mp4', 'sha256': FH,
    'size': 900_000_000, 'lives': 'store', 'downloaded_at': '2024-11-01', 'from_source': MSG}))['id']
bad('the same file registered twice', lambda: do('register', 'program', type='file', params={
    'original_name': 'copy.mp4', 'stored_name': 's', 'sha256': FH, 'lives': 'store'}), 'already registered')
bad('Claude registers a file', lambda: do('register', 'claude', type='file', params={
    'original_name': 'x', 'lives': 'provider_link'}), 'only by: program')
bad('a file recorded as a message source', lambda: do('record', 'program', type='file', params={
    'channel_id': MAIL, 'external_id': 'F'}), 'registered by the program')
bad('propose deleting before the size of a large file is set', lambda: do('propose_delete', 'program', target=F1),
    'not set')
door.conn.execute("INSERT INTO meta(key,value) VALUES('large_file_bytes','500000000')")
CLOCK[0] = '2026-10-01 09:00:00'
bad('propose deleting before 2 years', lambda: do('propose_delete', 'program', target=F1), '2 years')
CLOCK[0] = '2026-12-02 09:00:00'
PD = ok('the program asks the user about a large file after 2 years', lambda: do('propose_delete', 'program',
                                                                                 target=F1))
check('the question is a decision needed held by the user', PD and door.one(
    "SELECT 1 FROM followup f JOIN thing t ON t.id=f.thing_id WHERE f.thing_id=? AND t.type='decision_needed' "
    "AND f.holder_id=?", (PD['question_id'], ME)))
bad('ask about the same file twice', lambda: do('propose_delete', 'program', target=F1), 'already open')
bad('the program deletes a file', lambda: do('delete', 'program', target=F1), 'only by: user')
ok('the user records that he deleted it', lambda: do('delete', 'user', target=F1))
check('the deleted file stays recorded', door.one('SELECT status FROM file WHERE thing_id=?',
                                                  (F1,))[0] == 'deleted_by_user')

# decisions and rules
EVD = {'source': SESS, 'quote': 'Stop counting tokens.'}
bad('Claude records a decision that is not the user words', lambda: do('create', 'claude', type='decision',
                                                                       evidence=EVD, params={
    'verbatim': 'Stop counting.', 'said_at': '2026-11-16'}), 'verbatim text')
bad('Claude records a decision from an inference', lambda: do('create', 'claude', type='decision', evidence={
    **EVD, 'inferred': True}, params={'verbatim': EVD['quote'], 'said_at': '2026-11-16'}), 'inference')
bad('the user records a decision through Claude without Claude', lambda: do('create', 'user', type='decision',
                                                                            params={'verbatim': 'x',
                                                                                    'said_at': 'y'}),
    'only by: claude')
DEC = ok('Claude records the user decision word for word', lambda: do(
    'create', 'claude', type='decision', evidence=EVD, params={'verbatim': EVD['quote'], 'said_at': '2026-11-16'}))['id']
bad('change the wording of a decision', lambda: door.conn.execute(
    "UPDATE decision SET verbatim='x' WHERE thing_id=?", (DEC,)) and (_ for _ in ()).throw(mdb.Refused('x')),
    'never changes')
RU = ok('Claude writes a rule from the decision', lambda: do('create', 'claude', type='rule', params={
    'text': 'No token counts in reports.', 'decision_id': DEC, 'enforced_by': 'claude'}))['id']
bad('Claude edits the rule text', lambda: do('edit_text', 'claude', target=RU, params={'text': 'x'}),
    'only by: user')
DEC2 = do('create', 'claude', type='decision', evidence={'source': SESS, 'quote': 'Count again.'},
          params={'verbatim': 'Count again.', 'said_at': '2026-11-20'})['id']
bad('Claude supersedes a decision', lambda: do('supersede', 'claude', target=DEC, params={'by': DEC2}),
    'only by: user')
ok('the user supersedes a decision', lambda: do('supersede', 'user', target=DEC, params={'by': DEC2}))
bad('a rule from a superseded decision', lambda: do('create', 'claude', type='rule', params={
    'text': 't', 'decision_id': DEC, 'enforced_by': 'claude'}), 'decision in force')

# jobs
DJ = [x for x in door.due_jobs() if x['job_id'] == JOB]
check('a daily job missed for 11 days lists 11 periods, oldest first',
      len(DJ) == 11 and DJ[0]['period'] == '2026-11-22' and DJ[-1]['period'] == '2026-12-02', str(len(DJ)))
check('the missed periods are marked late, the current one is not',
      all(x['late'] for x in DJ[:-1]) and not DJ[-1]['late'])
ok('Claude executes a job that has a period due', lambda: do('execute', 'claude', target=JOB, run=RUN))
ok('the program marks the oldest period done', lambda: do('mark_period_done', 'program', target=JOB,
                                                          params={'period': '2026-11-22'}))
bad('mark the same period again', lambda: do('mark_period_done', 'program', target=JOB,
                                             params={'period': '2026-11-22'}), 'not a due period')
bad('mark a period that has not come', lambda: do('mark_period_done', 'program', target=JOB,
                                                  params={'period': '2026-12-25'}), 'not a due period')
check('the done period leaves the list', len([x for x in door.due_jobs() if x['job_id'] == JOB]) == 10)
WJ = do('create', 'user', type='job', params={'title': 'weekly', 'instructions': 'i',
                                              'schedule': {'every': 'week', 'day': 'sun', 'at': '09:00'}})['id']
check('a weekly job created on a Wednesday has its first period on Sunday',
      [x['period'] for x in door.due_jobs() if x['job_id'] == WJ] == [])
CLOCK[0] = '2026-12-06 09:30:00'
check('the weekly period comes on Sunday at its time',
      [x['period'] for x in door.due_jobs() if x['job_id'] == WJ] == ['2026-12-06'])
CLOCK[0] = '2026-12-02 09:00:00'
ok('the user pauses a job', lambda: do('pause', 'user', target=JOB))
bad('Claude executes a paused job', lambda: do('execute', 'claude', target=JOB), 'not allowed while the status')

# runs
bad('close a run while a source has no verdict and no reason', lambda: do('close', 'program', target=RUN),
    'no verdict and no recorded reason')
ok('a source that could not be read is recorded with its reason', lambda: do(
    'read', 'claude', target=SESS, run=RUN, params={'read_state': 'failed', 'reason': 'transcript not ready'}))
ok('the run closes complete with gaps', lambda: do('close', 'program', target=RUN))
check('the run status says complete with gaps', door.status_of(RUN) == 'complete_with_gaps')
RUN2 = do('start', 'program', type='run')['id']
ok('a run with every source judged closes complete', lambda: do('close', 'program', target=RUN2))
check('the second run is complete', door.status_of(RUN2) == 'complete')
bad('close a closed run', lambda: do('close', 'program', target=RUN), 'not allowed while the status')

# values Claude inferred
INF = ok('Claude marks a value it inferred', lambda: do('create', 'claude', type='commitment', evidence=EV, params={
    'title': 'inferred due', 'holder': SAM, 'promised_by': SAM, 'due': '2026-12-10',
    'details': {'text': 'next week'}, '_inferred': ['due']}))['id']
check('the inferred value stays marked', json.loads(door.one('SELECT details FROM followup WHERE thing_id=?',
                                                             (INF,))[0]).get('_inferred') == ['due'])
bad('the user marks a value as inferred', lambda: do('change_due', 'user', target=INF, params={
    'due': '2026-12-11', '_inferred': ['due']}), 'only Claude')
bad('confirm a value that is not marked', lambda: do('confirm_values', 'user', target=INF,
                                                     params={'names': ['holder']}), 'not marked')
ok('the user confirms the inferred value', lambda: do('confirm_values', 'user', target=INF, params={'names': ['due']}))
check('the mark is gone once confirmed', json.loads(door.one('SELECT details FROM followup WHERE thing_id=?',
                                                              (INF,))[0]).get('_inferred') == [])

# the guarantees
bad('delete a thing', lambda: door.conn.execute('DELETE FROM thing WHERE id=?', (SAM2,)) and
    (_ for _ in ()).throw(mdb.Refused('x')), 'ever deleted')
bad('edit an audit line', lambda: door.conn.execute("UPDATE audit SET note='x'") and
    (_ for _ in ()).throw(mdb.Refused('x')), 'append-only')
bad('delete an audit line', lambda: door.conn.execute('DELETE FROM audit') and
    (_ for _ in ()).throw(mdb.Refused('x')), 'append-only')
bad('an unknown actor', lambda: do('create', 'someone', type='area', params={'title': 'x'}), 'unknown actor')
bad('an unknown action', lambda: do('fly', 'user', target=C1), 'no action "fly"')
ids = [r[0] for r in door.conn.execute('SELECT id FROM thing ORDER BY rowid')]
check('numbers are unique across all types and never reused', len(ids) == len(set(ids)) and ids == sorted(ids))
check('every thing has a creation line in the audit trail', door.one(
    "SELECT count(*) FROM thing t WHERE NOT EXISTS (SELECT 1 FROM audit a WHERE a.thing_id=t.id "
    "AND a.action IN ('create','record','register','start'))")[0] == 0)

# two writers at once
other = mdb.Door(DB, timeout=0.3)
door.conn.execute('BEGIN IMMEDIATE')
try:
    bad('a second writer while the first is writing', lambda: other.do('create', 'user', type='area',
                                                                       evidence=USER_EV,
                                                                       params={'title': 'z'}), 'locked')
finally:
    door.conn.execute('ROLLBACK')
ok('the second writer succeeds once the first has finished', lambda: other.do(
    'create', 'user', type='area', evidence=USER_EV, params={'title': 'Finance'}))

# the command line
cli = [sys.executable, os.path.join(HERE, 'mdb.py'), '--db', DB]
r = subprocess.run(cli + ['do', 'defer', '--actor', 'claude', '--target', str(C1)], capture_output=True, text=True)
check('the command line refuses with exit code 2 and says why',
      r.returncode == 2 and 'only by: user' in json.loads(r.stdout)['refused'], r.stdout + r.stderr)
r = subprocess.run(cli + ['history', str(C1)], capture_output=True, text=True)
check('the command line shows the history of a thing', r.returncode == 0 and len(json.loads(r.stdout)) > 5,
      r.stderr)
r = subprocess.run(cli + ['allowed', '--type', 'for_info'], capture_output=True, text=True)
check('the command line lists allowed actions with Arabic names', r.returncode == 0 and any(
    x['action_ar'] == 'تعليم بالاطلاع' for x in json.loads(r.stdout)), r.stderr)

door.conn.close()
other.conn.close()
for n, v in results:
    print(' -', n, '=>', v)
bad_n = sum(1 for n, v in results if v.split(':')[0].split(' ')[0] in
            ('NOT', 'WRONGLY', 'REFUSED', 'NO', 'CRASHED'))
print('database', DB)
print('bad', bad_n, 'of', len(results))
sys.exit(1 if bad_n else 0)
