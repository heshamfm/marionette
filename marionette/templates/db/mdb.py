#!/usr/bin/env python3
"""Marionette by Hesham Elmahdy (github.com/heshamfm): the database door, version 1.5.

This program is the only door for writing to the Marionette database.
- Judgment (which action is needed, and why) belongs to the user or to Claude.
- This program executes the action and records it. It reads who may do what
  from the table action_rule, refuses an action that is not allowed and says
  why, and writes every change to the audit trail in the same transaction.
- Nothing is ever deleted. Nothing about one user's own channels, clients or
  people is written here: those are data in the user's database.

Command line (all output is JSON):
  python3 mdb.py --db FILE init --user-name NAME [--user-email ADDRESS] [--timezone ZONE]
                 [--workdays mon,tue,wed,thu,fri] [--week-start mon] [--language en]
  python3 mdb.py --db FILE do ACTION --actor user|claude|program [--target ID] [--type CODE]
                 [--params JSON] [--evidence JSON] [--run ID]
  python3 mdb.py --db FILE show ID
  python3 mdb.py --db FILE history ID
  python3 mdb.py --db FILE allowed [--type CODE]
  python3 mdb.py --db FILE due
  python3 mdb.py --db FILE due-jobs
  python3 mdb.py --db FILE late
An action in the user's name needs --evidence quoting his words from a session with Claude.
Claude marks values it inferred with "_inferred": ["name", ...] in --params; they stay marked until confirmed.
--evidence is {"source": ID, "quote": "...", "position": "...", "quote_date": "...", "inferred": false}.
A refused action prints {"refused": "<reason>"} and exits with code 2; nothing is written.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import sqlite3
import sys
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(HERE, 'schema_v0.1.sql')
SEED_FILE = os.path.join(HERE, 'seed_v0.1.py')
ACTORS = ('user', 'claude', 'program')
STATUS_TABLE = {'party': 'party', 'area': 'area', 'project': 'project', 'channel': 'channel',
                'file': 'file', 'decision': 'decision', 'rule': 'rule', 'job': 'job', 'run': 'run'}
NO_VERDICT = 'none'
# statuses of a follow-up thing that is still alive
ACTIVE = ('open', 'deferred', 'new', 'scheduled', 'shown', 'ready')
WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
SESSIONS_CHANNEL = 'Claude sessions'
# why a thing is late, in the language the database was created with
LATE_TEXT = {'en': ('the due time was {d}', 'not addressed since {d}'),
             'ar': ('كان الموعد {d}', 'لم تتناوله منذ ظهر يوم {d}')}
DEFAULT_TZ = 'UTC'   # used only when the database has no meta "timezone"; init records the user's zone


def local_now(tz=DEFAULT_TZ):
    """The wall-clock time of the user's time zone, never the clock of the machine the program runs on."""
    return datetime.datetime.now(zoneinfo.ZoneInfo(tz)).strftime('%Y-%m-%d %H:%M:%S')


def parse_schedule(text):
    """A job schedule is JSON, for example:
    {"every": "day", "at": "07:30", "days": ["sun","mon","tue","wed","thu"]}
    {"every": "week", "day": "sun", "at": "09:00"}
    {"every": "month", "day": 1, "at": "09:00"}
    The period of a daily job is its date, of a weekly job the date of the first day of its week (meta
    "week_start", set when the database is created), of a monthly job its month."""
    try:
        s = json.loads(text) if isinstance(text, str) else dict(text)
    except (ValueError, TypeError):
        raise Refused('a job schedule is JSON, for example {"every": "day", "at": "07:30"}')
    every = s.get('every')
    if every not in ('day', 'week', 'month'):
        raise Refused('a job schedule says every day, week or month')
    at = str(s.get('at', ''))
    try:
        datetime.datetime.strptime(at, '%H:%M')
    except ValueError:
        raise Refused('a job schedule needs the time "at" as HH:MM')
    if every == 'day':
        days = s.get('days') or list(WEEKDAYS)
        if not set(days) <= set(WEEKDAYS):
            raise Refused('days are written mon, tue, wed, thu, fri, sat, sun')
        s['days'] = days
    elif every == 'week' and s.get('day') not in WEEKDAYS:
        raise Refused('a weekly job names its day: mon, tue, wed, thu, fri, sat or sun')
    elif every == 'month' and not (isinstance(s.get('day'), int) and 1 <= s['day'] <= 28):
        raise Refused('a monthly job names its day of the month, 1 to 28')
    return s


def occurrences(sched, first_day, now_dt, week_start='mon'):
    """Every (period, due time) of a schedule from first_day up to now, oldest first."""
    hh, mm = map(int, sched['at'].split(':'))
    d = first_day
    out = []
    while d <= now_dt.date() and len(out) < 400:
        wd = WEEKDAYS[d.weekday()]
        hit = ((sched['every'] == 'day' and wd in sched['days'])
               or (sched['every'] == 'week' and wd == sched['day'])
               or (sched['every'] == 'month' and d.day == sched['day']))
        when = datetime.datetime(d.year, d.month, d.day, hh, mm)
        if hit and when <= now_dt:
            if sched['every'] == 'day':
                period = d.isoformat()
            elif sched['every'] == 'week':
                # the period is the date of the first day of the user's week
                period = (d - datetime.timedelta(days=(d.weekday() - WEEKDAYS.index(week_start)) % 7)).isoformat()
            else:
                period = d.strftime('%Y-%m')
            out.append((period, when.strftime('%Y-%m-%d %H:%M')))
        d += datetime.timedelta(days=1)
    return out


class Refused(Exception):
    """An action the rules do not allow. The message says why."""


def load_seed():
    spec = importlib.util.spec_from_file_location('marionette_seed', SEED_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def connect(path, timeout=5.0):
    conn = sqlite3.connect(path, timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=TRUNCATE')
    return conn


class Door:
    def __init__(self, path, now=None, timeout=5.0, tz=None):
        self.path = path
        if tz:
            self._tz = tz
        self.conn = connect(path, timeout)
        self._now = now
        self.audit_lines = 0

    # ---------- basics ----------
    def now(self):
        if self._now:
            return self._now() if callable(self._now) else self._now
        if not hasattr(self, '_tz'):
            try:
                self._tz = self.meta('timezone', DEFAULT_TZ)
            except sqlite3.Error:
                self._tz = DEFAULT_TZ
        return local_now(self._tz)

    def passed(self, when, inclusive=False):
        """True when the date or time `when` is in the past. A bare date counts as the whole day."""
        n = self.now()
        if len(when) == 10:
            n = n[:10]
        return when <= n if inclusive else when < n

    def one(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def meta(self, key, default=None):
        r = self.one('SELECT value FROM meta WHERE key=?', (key,))
        return r['value'] if r else default

    def thing(self, tid):
        r = self.one('SELECT t.*, ty.grp FROM thing t JOIN type ty ON ty.code=t.type WHERE t.id=?', (tid,))
        if not r:
            raise Refused(f'no thing with number {tid}')
        return r

    def type_row(self, code):
        r = self.one('SELECT * FROM type WHERE code=?', (code,))
        if not r:
            raise Refused(f'unknown type "{code}"')
        return r

    def table_of(self, type_code, grp):
        if grp == 'followup':
            return 'followup'
        if type_code in STATUS_TABLE:
            return STATUS_TABLE[type_code]
        if grp == 'source':
            return 'source'
        raise Refused(f'type "{type_code}" has no table')

    def status_of(self, tid):
        t = self.thing(tid)
        table = self.table_of(t['type'], t['grp'])
        if table == 'source':
            r = self.one('SELECT verdict FROM source WHERE thing_id=?', (tid,))
            return (r['verdict'] or NO_VERDICT) if r else None
        r = self.one(f'SELECT status FROM {table} WHERE thing_id=?', (tid,))
        return r['status'] if r else None

    # ---------- permission, read from action_rule ----------
    def permit(self, type_code, grp, action, actor, current):
        rows = None
        for scope in (type_code, grp, '*'):
            rows = self.conn.execute('SELECT * FROM action_rule WHERE scope=? AND action=?',
                                     (scope, action)).fetchall()
            if rows:
                break
        if not rows:
            raise Refused(f'there is no action "{action}" for type "{type_code}"')
        mine = [r for r in rows if r['actor'] == actor]
        if not mine:
            who = sorted({r['actor'] for r in rows})
            raise Refused(f'"{action}" on "{type_code}" may be done only by: {", ".join(who)}')
        if current is None:
            fit = [r for r in mine if r['from_status'] is None]
        else:
            fit = [r for r in mine if r['from_status'] is None or r['from_status'] == current]
        if not fit:
            allowed = sorted({r['from_status'] for r in mine if r['from_status']})
            raise Refused(f'"{action}" is not allowed while the status is "{current}"; '
                          f'allowed from: {", ".join(allowed) or "a new thing only"}')
        return fit[0]

    # ---------- writing helpers (every change goes to audit) ----------
    def audit(self, tid, action, field=None, old=None, new=None, note=None):
        def s(v):
            if v is None or isinstance(v, str):
                return v
            return json.dumps(v, ensure_ascii=False)
        row = [self.now(), self.ctx['actor'], self.ctx['run'], tid, action, field, s(old), s(new),
               self.ctx.get('evidence_id'), note]
        if self.ctx.get('held') is not None:
            # a creation with evidence: its rows wait until the evidence exists, so every row carries it
            self.ctx['held'].append(row)
            return
        self.write_audit(row)

    def write_audit(self, row):
        self.conn.execute('INSERT INTO audit(at,actor,run_id,thing_id,action,field,old_value,new_value,'
                          'evidence_id,note) VALUES(?,?,?,?,?,?,?,?,?,?)', row)
        self.audit_lines += 1

    def release_held(self):
        held, self.ctx['held'] = self.ctx.get('held') or [], None
        for row in held:
            if row[8] is None:
                row[8] = self.ctx.get('evidence_id')
            self.write_audit(row)

    def set(self, table, tid, field, value):
        key = 'id' if table == 'thing' else 'thing_id'
        old = self.one(f'SELECT {field} FROM {table} WHERE {key}=?', (tid,))[0]
        if old == value:
            return
        self.conn.execute(f'UPDATE {table} SET {field}=? WHERE {key}=?', (value, tid))
        self.audit(tid, self.ctx['action'], f'{table}.{field}', old, value)

    def set_many(self, table, tid, changes):
        """Change several columns in one statement, so checks that tie them together see the final values."""
        cols = list(changes)
        old = self.one(f'SELECT {",".join(cols)} FROM {table} WHERE thing_id=?', (tid,))
        diff = [c for c in cols if old[c] != changes[c]]
        if not diff:
            return
        self.conn.execute(f'UPDATE {table} SET {",".join(c + "=?" for c in diff)} WHERE thing_id=?',
                          [changes[c] for c in diff] + [tid])
        for c in diff:
            self.audit(tid, self.ctx['action'], f'{table}.{c}', old[c], changes[c])

    def details_table(self, tid):
        t = self.thing(tid)
        table = self.table_of(t['type'], t['grp'])
        if table not in ('followup', 'source'):
            raise Refused('inference marks are kept on follow-up things and sources; '
                          'links and evidence carry their own mark')
        return table

    def mark_inferred(self, tid, names):
        if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
            raise Refused('_inferred is a list of the names of the values Claude inferred')
        table = self.details_table(tid)
        cur = json.loads(self.one(f'SELECT details FROM {table} WHERE thing_id=?', (tid,))[0])
        self.set_details(table, tid, {'_inferred': sorted(set(cur.get('_inferred', [])) | set(names))})

    def set_details(self, table, tid, changes):
        cur = json.loads(self.one(f'SELECT details FROM {table} WHERE thing_id=?', (tid,))[0])
        for k, v in changes.items():
            if cur.get(k) != v:
                self.audit(tid, self.ctx['action'], f'details.{k}', cur.get(k), v)
                cur[k] = v
        self.conn.execute(f'UPDATE {table} SET details=? WHERE thing_id=?',
                          (json.dumps(cur, ensure_ascii=False), tid))

    def set_status(self, tid, new):
        t = self.thing(tid)
        table = self.table_of(t['type'], t['grp'])
        if table == 'source':
            self.set('source', tid, 'verdict', None if new == NO_VERDICT else new)
        else:
            self.set(table, tid, 'status', new)

    def new_thing(self, type_code, title, area_id=None, project_id=None):
        if not title or not str(title).strip():
            raise Refused('every thing needs a title')
        for ref, kind in ((area_id, 'area'), (project_id, 'project')):
            if ref is not None and self.thing(ref)['type'] != kind:
                raise Refused(f'thing {ref} is not a {kind}')
        tid = self.conn.execute('INSERT INTO thing(type,title,created_at,created_by,area_id,project_id) '
                                'VALUES(?,?,?,?,?,?)', (type_code, title, self.now(), self.ctx['actor'],
                                                        area_id, project_id)).lastrowid
        self.audit(tid, 'create', 'thing.title', None, title)
        return tid

    def add_link(self, from_id, to_id, role, inferred=False):
        self.thing(from_id), self.thing(to_id)
        if self.one('SELECT 1 FROM link WHERE from_id=? AND to_id=? AND role=?', (from_id, to_id, role)):
            return
        self.conn.execute('INSERT INTO link(from_id,to_id,role,inferred,created_at) VALUES(?,?,?,?,?)',
                          (from_id, to_id, role, 1 if inferred else 0, self.now()))
        self.audit(from_id, self.ctx['action'], 'link', None,
                   {'to': to_id, 'role': role, 'inferred': bool(inferred)})

    def add_evidence(self, tid, ev):
        src = ev.get('source')
        if src is None or not str(ev.get('quote') or '').strip():
            raise Refused('evidence needs a source number and the verbatim quote')
        st = self.thing(src)
        if st['grp'] != 'source' or st['type'] == 'file':
            raise Refused(f'thing {src} is not a source (message, event, meeting, record, content or session)')
        eid = self.conn.execute('INSERT INTO evidence(thing_id,source_id,quote,position,quote_date,inferred) '
                                'VALUES(?,?,?,?,?,?)', (tid, src, ev['quote'], ev.get('position'),
                                                        ev.get('quote_date'), 1 if ev.get('inferred') else 0)
                                ).lastrowid
        self.ctx['evidence_id'] = eid
        return eid

    def party(self, pid, what='party'):
        r = self.one('SELECT * FROM party WHERE thing_id=?', (pid,))
        if not r:
            raise Refused(f'{what} {pid} is not a party')
        return r

    def require(self, p, *keys):
        missing = [k for k in keys if p.get(k) in (None, '', [], {})]
        if missing:
            raise Refused('missing: ' + ', '.join(missing))

    # ---------- the one entry point ----------
    def do(self, action, actor, target=None, type=None, params=None, evidence=None, run=None):
        if actor not in ACTORS:
            raise Refused(f'unknown actor "{actor}"')
        p = dict(params or {})
        self.ctx = {'actor': actor, 'action': action, 'run': run, 'evidence_id': None, 'held': None}
        try:
            self.conn.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as e:
            raise Refused(f'the database is busy with another writer ({e}); try again')
        try:
            if run is not None and self.thing(run)['type'] != 'run':
                raise Refused(f'thing {run} is not a run')
            if target is not None:
                t = self.thing(target)
                type_code, grp, current = t['type'], t['grp'], self.status_of(target)
                if type and type != type_code:
                    raise Refused(f'thing {target} is a {type_code}, not a {type}')
            else:
                if not type:
                    raise Refused('give --target for an existing thing, or --type to create one')
                type_code, grp, current = type, self.type_row(type)['grp'], None
            rule = self.permit(type_code, grp, action, actor, current)
            if rule['needs_evidence'] and not evidence:
                if actor == 'user':
                    raise Refused('an action in the name of the user needs his own words, quoted from a session '
                                  'with Claude, as evidence')
                raise Refused(f'{actor} needs evidence (a source and the verbatim quote) for "{action}"')
            if actor == 'user' and evidence:
                src = self.one('SELECT type FROM thing WHERE id=?', (evidence.get('source'),))
                if not src or src['type'] != 'session' or evidence.get('inferred'):
                    raise Refused('an action in the name of the user rests on his own words in a session with '
                                  'Claude, never on another source or an inference')
            inferred = p.pop('_inferred', None)
            if inferred and actor != 'claude':
                raise Refused('only Claude marks values as inferred')
            handler = getattr(self, 'a_' + action, None)
            if handler is None:
                raise Refused(f'action "{action}" has a permission line but no program step')
            self.ctx.update(type=type_code, grp=grp, current=current, rule=rule, evidence=evidence)
            if target is not None and evidence:
                self.add_evidence(target, evidence)
            if target is None and evidence:
                self.ctx['held'] = []
            result = handler(target, p) or {}
            tid = result.get('id', target)
            if target is None and evidence:
                self.add_evidence(tid, evidence)
                self.release_held()
                self.audit(tid, action, 'evidence', None, self.ctx['evidence_id'])
            if rule['to_status'] and not result.get('status_set'):
                self.set_status(tid, rule['to_status'])
            if inferred:
                self.mark_inferred(tid, inferred)
            self.conn.execute('COMMIT')
            result.setdefault('id', tid)
            result['status'] = self.status_of(tid)
            return result
        except sqlite3.IntegrityError as e:
            self.conn.execute('ROLLBACK')
            raise Refused(self.explain(str(e)))
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise

    def explain(self, msg):
        if 'UNIQUE' in msg and ('party_email_once' in msg or 'party_handle' in msg):
            return 'this email address already belongs to another party; merge the two parties instead'
        if 'source.channel_id, source.external_id' in msg:
            return 'this source is already recorded'
        return msg

    # ================= follow-up things =================
    def a_create(self, target, p):
        g, ty = self.ctx['grp'], self.ctx['type']
        if g == 'followup':
            return self.create_followup(ty, p)
        return getattr(self, 'create_' + ty)(p)

    def create_followup(self, ty, p, initial=None):
        fields = json.loads(self.type_row(ty)['fields'])
        d = dict(p.get('details') or {})
        missing = [k for k in fields.get('required', []) if d.get(k) in (None, '', [])]
        if missing:
            raise Refused(f'a {ty} needs in details: ' + ', '.join(missing))
        for role in fields.get('links', []):
            if p.get(role) is None:
                raise Refused(f'a {ty} needs the party "{role}"')
        if fields.get('needs_due') and not p.get('due'):
            raise Refused(f'a {ty} needs a due date')
        if fields.get('needs_next_check') and not p.get('next_check'):
            raise Refused(f'a {ty} needs the date of the check (next_check)')
        if ty == 'draft':
            self.check_draft(d)
        self.require(p, 'holder')
        self.party(p['holder'], 'next step holder')
        tid = self.new_thing(ty, p.get('title'), p.get('area_id'), p.get('project_id'))
        status = initial or self.ctx['rule']['to_status']
        self.conn.execute('INSERT INTO followup(thing_id,status,holder_id,due,next_check,details) '
                          'VALUES(?,?,?,?,?,?)', (tid, status, p['holder'], p.get('due'), p.get('next_check'),
                                                  json.dumps(d, ensure_ascii=False)))
        self.audit(tid, 'create', 'followup.status', None, status)
        self.audit(tid, 'create', 'followup.holder_id', None, p['holder'])
        for role in fields.get('links', []) + fields.get('optional_links', []):
            if p.get(role) is not None:
                self.party(p[role], role)
                self.add_link(tid, p[role], role)
        for x in p.get('parties') or []:
            if x.get('role') not in ('beneficiary', 'participant'):
                raise Refused('a linked party has the role beneficiary or participant')
            self.party(x['party'])
            self.add_link(tid, x['party'], x['role'], x.get('inferred', False))
        return {'id': tid, 'status_set': True}

    def check_draft(self, d):
        if d.get('kind') not in ('reply', 'forward', 'new'):
            raise Refused('a draft kind is reply, forward or new')
        if d['kind'] in ('reply', 'forward') and not d.get('replies_to'):
            raise Refused('a reply or a forward must name what it answers or passes on (replies_to)')
        if self.thing(d['channel_id'])['type'] != 'channel':
            raise Refused(f'thing {d["channel_id"]} is not a channel')

    def a_hand_over(self, tid, p):
        self.require(p, 'holder')
        self.party(p['holder'], 'next step holder')
        self.set('followup', tid, 'holder_id', p['holder'])

    def a_change_due(self, tid, p):
        self.set('followup', tid, 'due', p.get('due'))

    def a_set_next_check(self, tid, p):
        self.set('followup', tid, 'next_check', p.get('next_check'))

    def a_defer(self, tid, p):
        if self.ctx['type'] == 'reminder':
            self.require(p, 'due')
        if p.get('due'):
            self.set('followup', tid, 'due', p['due'])

    def a_complete(self, tid, p):
        reason = p.get('close_reason', 'done')
        if reason not in ('done', 'handed_over', 'not_needed'):
            raise Refused('close reason is done, handed_over or not_needed (merging has its own action)')
        if reason == 'handed_over':
            self.require(p, 'to_party')
            self.party(p['to_party'])
            self.add_link(tid, p['to_party'], 'handed_over_to')
        self.set('followup', tid, 'close_reason', reason)

    def a_reopen(self, tid, p):
        self.set('followup', tid, 'close_reason', None)

    def a_merge(self, tid, p):
        g = self.ctx['grp']
        self.require(p, 'into')
        into = self.thing(p['into'])
        if into['type'] != self.ctx['type']:
            raise Refused('only two things of the same type can be merged')
        if into['id'] == tid:
            raise Refused('a thing cannot be merged into itself')
        if g == 'reference':
            return self.merge_party(tid, p)
        if self.status_of(into['id']) not in ('open', 'deferred'):
            raise Refused('the thing kept must still be open')
        if self.ctx['actor'] == 'claude':
            shared = self.one('SELECT 1 FROM evidence a JOIN evidence b ON a.source_id=b.source_id '
                              'WHERE a.thing_id=? AND b.thing_id=?', (tid, into['id']))
            if not shared:
                raise Refused('Claude merges two things only when they come from the same source')
        self.set('followup', tid, 'close_reason', 'merged')
        self.add_link(tid, into['id'], 'merged_into')

    def a_cancel(self, tid, p):
        if self.ctx['type'] == 'deferred_check' and self.ctx['actor'] == 'claude':
            about = self.conn.execute("SELECT to_id FROM link WHERE from_id=? AND role='about'", (tid,)).fetchall()
            if not about or any(self.status_of(r[0]) in ACTIVE for r in about):
                raise Refused('Claude cancels a deferred check only when the thing it is about has ended')

    def a_mark_late(self, tid, p):
        f = self.one('SELECT due, details FROM followup WHERE thing_id=?', (tid,))
        if not f['due'] or not self.passed(f['due']):
            raise Refused('not late: no due date has passed')
        if json.loads(f['details']).get('late_since'):
            raise Refused('already marked late')
        self.set_details('followup', tid, {'late_since': self.now()})

    def a_assign(self, tid, p):
        for key, kind in (('area_id', 'area'), ('project_id', 'project')):
            if key in p:
                if p[key] is not None and self.thing(p[key])['type'] != kind:
                    raise Refused(f'thing {p[key]} is not a {kind}')
                self.set('thing', tid, key, p[key])

    def a_record_decision(self, tid, p):
        self.require(p, 'decision')
        self.set_details('followup', tid, {'decision': p['decision']})
        self.set('followup', tid, 'close_reason', 'done')

    def a_show(self, tid, p):
        if self.ctx['type'] == 'reminder':
            due = self.one('SELECT due FROM followup WHERE thing_id=?', (tid,))['due']
            if due and not self.passed(due, inclusive=True):
                raise Refused('this reminder is not due yet')
        else:
            self.audit(tid, 'show', note='shown in the report')

    def a_mark_seen(self, tid, p):
        pass

    def a_convert(self, tid, p):
        new_type = p.get('new_type')
        if new_type not in ('commitment', 'reply_needed', 'decision_needed'):
            raise Refused('converted into commitment, reply_needed or decision_needed')
        rule = self.permit(new_type, 'followup', 'create', self.ctx['actor'], None)
        saved = self.ctx['rule']
        self.ctx['rule'] = rule
        new = self.create_followup(new_type, p)['id']
        self.ctx['rule'] = saved
        if self.ctx.get('evidence'):
            self.add_evidence(new, self.ctx['evidence'])
        self.add_link(new, tid, 'converted_from')
        return {'id': tid, 'new_id': new}

    # ---------- drafts ----------
    def a_edit(self, tid, p):
        ty = self.ctx['type']
        if ty == 'draft':
            ch = {k: p[k] for k in ('text', 'recipients', 'cc', 'subject') if k in p}
            if not ch:
                raise Refused('nothing to change')
            self.set_details('followup', tid, ch)
        elif ty == 'party':
            self.edit_party(tid, p)
        elif ty == 'job':
            if 'schedule' in p:
                p['schedule'] = json.dumps(parse_schedule(p['schedule']), ensure_ascii=False)
            for k in ('instructions', 'schedule'):
                if k in p:
                    self.set('job', tid, k, p[k])
            for k in ('channels', 'approved_texts'):
                if k in p:
                    self.set('job', tid, k, json.dumps(p[k], ensure_ascii=False))
            if 'send_permission' in p:
                self.set('job', tid, 'send_permission', p['send_permission'])

    def a_send(self, tid, p):
        if self.ctx['actor'] != 'claude':
            return
        d = json.loads(self.one('SELECT details FROM followup WHERE thing_id=?', (tid,))['details'])
        job = d.get('job_id')
        if job is None:
            raise Refused('Claude sends only a draft made by a recurring job that may send; the default is draft only')
        j = self.one('SELECT * FROM job WHERE thing_id=?', (job,))
        if not j or j['send_permission'] != 'approved_text' or j['status'] != 'enabled':
            raise Refused('the job behind this draft may not send: draft only')
        if d.get('text') not in json.loads(j['approved_texts']):
            raise Refused('the draft text is not one the user approved for this job')
        ch = self.one('SELECT send_policy FROM channel WHERE thing_id=?', (d['channel_id'],))
        if ch is None or ch['send_policy'] == 'draft_only':
            raise Refused('the channel of this draft is draft only')

    def a_mark_sent_as_is(self, tid, p):
        pass

    def a_mark_sent_edited(self, tid, p):
        if 'sent_text' in p:
            self.set_details('followup', tid, {'sent_text': p['sent_text']})

    def a_abandon(self, tid, p):
        if self.ctx['actor'] == 'claude' and self.thing(tid)['created_by'] != 'claude':
            raise Refused('Claude abandons only a draft Claude wrote')
        if self.ctx['actor'] == 'claude':
            self.require(p, 'reason')
            f = self.one('SELECT due, details FROM followup WHERE thing_id=?', (tid,))
            serves = json.loads(f['details']).get('serves')
            passed = f['due'] and self.passed(f['due'])
            ended = serves is not None and self.status_of(serves) not in ACTIVE
            replaced = False
            if p.get('superseded_by') is not None:
                # a newer draft for the same thing replaced it
                new = self.thing(p['superseded_by'])
                if new['type'] != 'draft' or new['id'] <= tid:
                    raise Refused('superseded_by is a newer draft')
                nserves = json.loads(self.one('SELECT details FROM followup WHERE thing_id=?', (new['id'],))
                                     ['details']).get('serves')
                if nserves != serves:
                    raise Refused('the newer draft must serve the same thing')
                self.add_link(tid, new['id'], 'superseded_by')
                replaced = True
            gone = p.get('gone_from_mail') is True
            if gone and not self.ctx.get('evidence'):
                raise Refused('a draft gone from the mail unsent is abandoned with evidence: where it was looked for')
            if not (passed or ended or replaced or gone):
                raise Refused('Claude abandons its draft only when its time has passed: its due date is past, '
                              'or the thing it serves has ended, or a newer draft replaced it, '
                              'or it is gone from the mail unsent (with evidence)')
        if p.get('reason'):
            self.set_details('followup', tid, {'abandon_reason': p['reason']})

    # ---------- deferred checks and jobs ----------
    def a_execute(self, tid, p):
        if self.ctx['type'] == 'job':
            due = [x['period'] for x in self.due_jobs() if x['job_id'] == tid]
            if not due:
                raise Refused('this job has no period due now')
            self.audit(tid, 'execute', note=f'period {due[0]}' + (f': {p["note"]}' if p.get('note') else ''))
            return
        nc = self.one('SELECT next_check FROM followup WHERE thing_id=?', (tid,))['next_check']
        if nc and not self.passed(nc, inclusive=True):
            raise Refused('this check is not due yet')
        if p.get('result') not in (True, False):
            raise Refused('the result of the check is true or false')
        self.set_details('followup', tid, {'result': p['result'], 'result_note': p.get('note')})

    # ================= reference records =================
    def create_party(self, p):
        if p.get('kind') not in ('person', 'org', 'system'):
            raise Refused('a party is a person, an org or a system')
        if self.ctx['actor'] == 'claude' and p.get('relation', 'stranger') != 'stranger':
            raise Refused('only the user sets a party relation; Claude may propose it')
        tid = self.new_thing('party', p.get('title'), p.get('area_id'), p.get('project_id'))
        org = p.get('org_id')
        if org is not None and self.party(org, 'organisation')['kind'] != 'org':
            raise Refused(f'party {org} is not an organisation')
        self.conn.execute('INSERT INTO party(thing_id,kind,relation,org_id,role_in_org,external_link) '
                          'VALUES(?,?,?,?,?,?)', (tid, p['kind'], p.get('relation', 'stranger'), org,
                                                  p.get('role_in_org'), p.get('external_link')))
        self.audit(tid, 'create', 'party.kind', None, p['kind'])
        self.add_handles(tid, p.get('handles') or [])
        return {'id': tid}

    def add_handles(self, pid, handles):
        for h in handles:
            if h.get('kind') not in ('alias', 'email', 'phone', 'whatsapp', 'address', 'domain'):
                raise Refused('a contact detail is alias, email, phone, whatsapp, address or domain')
            v = str(h.get('value') or '').strip()
            if not v:
                raise Refused('a contact detail needs a value')
            if self.one('SELECT 1 FROM party_handle WHERE party_id=? AND kind=? AND lower(value)=lower(?)',
                        (pid, h['kind'], v)):
                continue
            self.conn.execute('INSERT INTO party_handle(party_id,kind,value) VALUES(?,?,?)', (pid, h['kind'], v))
            self.audit(pid, self.ctx['action'], 'party_handle.' + h['kind'], None, v)

    def edit_party(self, tid, p):
        self.add_handles(tid, p.get('handles') or [])
        for k in ('role_in_org', 'external_link'):
            if k in p:
                self.set('party', tid, k, p[k])
        if 'title' in p:
            self.set('thing', tid, 'title', p['title'])

    def a_confirm(self, tid, p):
        pass

    def a_link_org(self, tid, p):
        self.require(p, 'org_id')
        if self.party(p['org_id'], 'organisation')['kind'] != 'org':
            raise Refused(f'party {p["org_id"]} is not an organisation')
        if self.party(tid)['kind'] != 'person':
            raise Refused('only a person is linked to an organisation')
        self.set('party', tid, 'org_id', p['org_id'])
        if 'role_in_org' in p:
            self.set('party', tid, 'role_in_org', p['role_in_org'])

    def a_change_relation(self, tid, p):
        self.require(p, 'relation')
        self.set('party', tid, 'relation', p['relation'])

    def merge_party(self, tid, p):
        keep = p['into']
        if self.party(tid)['is_user']:
            raise Refused('the user party is never merged away')
        if self.ctx['actor'] == 'claude':
            email = str(p.get('email') or '').lower()
            quote = str((self.ctx['evidence'] or {}).get('quote') or '').lower()
            held = self.one("SELECT party_id FROM party_handle WHERE kind='email' AND lower(value)=?", (email,))
            if not email or not held or held[0] not in (tid, keep) or email not in quote:
                raise Refused('Claude merges two parties only on the same email address, shown in the quote; '
                              'never on a similar name')
        for h in self.conn.execute('SELECT id, kind, value FROM party_handle WHERE party_id=?', (tid,)).fetchall():
            self.conn.execute('UPDATE party_handle SET party_id=? WHERE id=?', (keep, h['id']))
            self.audit(keep, 'merge', 'party_handle.' + h['kind'], None, h['value'], note=f'moved from party {tid}')
        for f in self.conn.execute('SELECT thing_id FROM followup WHERE holder_id=?', (tid,)).fetchall():
            self.set('followup', f[0], 'holder_id', keep)
        self.add_link(tid, keep, 'merged_into')

    def a_deactivate(self, tid, p):
        if self.party(tid)['is_user']:
            raise Refused('the user party is never deactivated')

    def create_area(self, p):
        tid = self.new_thing('area', p.get('title'))
        self.conn.execute('INSERT INTO area(thing_id,description) VALUES(?,?)', (tid, p.get('description')))
        return {'id': tid}

    def a_rename(self, tid, p):
        self.require(p, 'title')
        self.set('thing', tid, 'title', p['title'])

    def a_archive(self, tid, p):
        pass

    def create_project(self, p):
        self.require(p, 'area_id')
        if self.thing(p['area_id'])['type'] != 'area':
            raise Refused(f'thing {p["area_id"]} is not an area')
        tid = self.new_thing('project', p.get('title'), p['area_id'])
        self.conn.execute('INSERT INTO project(thing_id,area_id,external_link,started) VALUES(?,?,?,?)',
                          (tid, p['area_id'], p.get('external_link'), p.get('started')))
        for x in p.get('parties') or []:
            self.party(x)
            self.add_link(tid, x, 'party')
        return {'id': tid}

    def a_pause(self, tid, p):
        pass

    def a_end(self, tid, p):
        pass

    def a_resume(self, tid, p):
        pass

    def create_channel(self, p):
        self.require(p, 'title', 'connection')
        sp = p.get('send_policy', 'draft_only')
        tid = self.new_thing('channel', p['title'])
        self.conn.execute('INSERT INTO channel(thing_id,connection,reads,send_policy) VALUES(?,?,?,?)',
                          (tid, p['connection'], p.get('reads'), sp))
        return {'id': tid}

    def a_update_watermark(self, tid, p):
        self.require(p, 'watermark')
        self.set('channel', tid, 'watermark', p['watermark'])
        if 'last_result' in p:
            self.set('channel', tid, 'last_result', p['last_result'])

    def a_mark_unavailable(self, tid, p):
        self.require(p, 'reason')
        self.set('channel', tid, 'last_result', p['reason'])

    def a_mark_available(self, tid, p):
        self.set('channel', tid, 'last_result', p.get('note', 'reachable again'))

    def a_stop(self, tid, p):
        pass

    # ================= sources and evidence =================
    def a_record(self, target, p):
        ty = self.ctx['type']
        if ty == 'file':
            raise Refused('a file is registered by the program (action register), not recorded')
        self.require(p, 'channel_id', 'external_id')
        if self.thing(p['channel_id'])['type'] != 'channel':
            raise Refused(f'thing {p["channel_id"]} is not a channel')
        old = self.one('SELECT thing_id FROM source WHERE channel_id=? AND external_id=?',
                       (p['channel_id'], str(p['external_id'])))
        if old:
            raise Refused(f'this source is already recorded as thing {old[0]}')
        fields = json.loads(self.type_row(ty)['fields'])
        d = dict(p.get('details') or {})
        missing = [k for k in fields.get('required', []) if not d.get(k)]
        if missing:
            raise Refused(f'a {ty} needs in details: ' + ', '.join(missing))
        tid = self.new_thing(ty, p.get('title'), p.get('area_id'), p.get('project_id'))
        self.conn.execute('INSERT INTO source(thing_id,channel_id,external_id,permalink,source_date,run_id,details) '
                          'VALUES(?,?,?,?,?,?,?)', (tid, p['channel_id'], str(p['external_id']), p.get('permalink'),
                                                    p.get('source_date'), self.ctx['run'],
                                                    json.dumps(d, ensure_ascii=False)))
        self.audit(tid, 'record', 'source.external_id', None, str(p['external_id']))
        return {'id': tid, 'status_set': True}

    def a_read(self, tid, p):
        state = p.get('read_state')
        if state not in ('full', 'partial', 'failed'):
            raise Refused('read_state is full, partial or failed')
        if state != 'full':
            self.require(p, 'reason')
        self.set_many('source', tid, {'read_state': state,
                                      'read_fail_reason': None if state == 'full' else p['reason']})
        if self.ctx['run'] is not None:
            self.set('source', tid, 'run_id', self.ctx['run'])

    def a_verdict(self, tid, p):
        v = p.get('verdict')
        if v not in ('linked', 'informed', 'ignored'):
            raise Refused('a verdict is linked, informed or ignored')
        if self.one('SELECT read_state FROM source WHERE thing_id=?', (tid,))[0] != 'full':
            raise Refused('no verdict on a source that was not read in full')
        if v == 'ignored':
            self.require(p, 'reason')
        else:
            tied = self.one("""SELECT 1 FROM evidence e JOIN thing t ON t.id=e.thing_id
                               WHERE e.source_id=? AND t.type NOT IN ('message','calendar_event','meeting',
                               'external_record','published_content','session')
                               UNION SELECT 1 FROM link WHERE from_id=? OR to_id=?""", (tid, tid, tid))
            if not tied:
                raise Refused(f'a verdict "{v}" needs evidence or a link tying this source to a thing first')
            if v == 'informed' and not self.one("""SELECT 1 FROM evidence e JOIN thing t ON t.id=e.thing_id
                                                  WHERE e.source_id=? AND t.type='for_info'""", (tid,)):
                raise Refused('a verdict "informed" needs a for-information thing that quotes this source')
        self.set_many('source', tid, {'verdict': v, 'verdict_reason': p.get('reason')})
        if self.ctx['run'] is not None:
            self.set('source', tid, 'run_id', self.ctx['run'])
        return {'status_set': True}

    def a_correct_verdict(self, tid, p):
        return self.a_verdict(tid, p)

    def a_reset_verdict(self, tid, p):
        """Only when the user acted on a source that was ignored: his outgoing message, or his words in a session."""
        self.require(p, 'reason', 'act_source')
        act = self.thing(p['act_source'])
        if act['id'] == tid:
            raise Refused('the proof that the user acted is another source, not the ignored one')
        if act['type'] == 'message':
            d = json.loads(self.one('SELECT details FROM source WHERE thing_id=?', (act['id'],))[0])
            if d.get('direction') != 'outgoing':
                raise Refused('the proof is a message the user sent (direction outgoing), or his words in a session')
        elif act['type'] != 'session':
            raise Refused('the proof is a message the user sent, or his words in a session')
        self.add_link(act['id'], tid, 'user_acted_on')
        self.set('source', tid, 'verdict_reason', p['reason'])

    def a_update_state(self, tid, p):
        self.require(p, 'last_state')
        self.set_details('source', tid, {'last_state': p['last_state'], 'last_seen': self.now()})

    def a_register(self, target, p):
        self.require(p, 'original_name', 'lives')
        if p['lives'] not in ('store', 'user_disk', 'provider_link'):
            raise Refused('a file lives in the store, on the user disk, or at a provider link')
        if p['lives'] == 'store':
            self.require(p, 'stored_name', 'sha256')
        if p.get('sha256'):
            old = self.one('SELECT thing_id FROM file WHERE sha256=?', (p['sha256'],))
            if old:
                raise Refused(f'this file is already registered as thing {old[0]}')
        if p.get('from_source') is not None and self.thing(p['from_source'])['grp'] != 'source':
            raise Refused(f'thing {p["from_source"]} is not a source')
        tid = self.new_thing('file', p.get('title') or p['original_name'])
        status = 'referenced' if p['lives'] == 'provider_link' else 'kept'
        self.conn.execute('INSERT INTO file(thing_id,original_name,stored_name,sha256,size,mime,lives,status,'
                          'downloaded_at,from_source) VALUES(?,?,?,?,?,?,?,?,?,?)',
                          (tid, p['original_name'], p.get('stored_name'), p.get('sha256'), p.get('size'),
                           p.get('mime'), p['lives'], status, p.get('downloaded_at'), p.get('from_source')))
        self.audit(tid, 'register', 'file.status', None, status)
        return {'id': tid, 'status_set': True}

    def a_mark_missing(self, tid, p):
        pass

    def a_propose_delete(self, tid, p):
        large = self.meta('large_file_bytes')
        if not large:
            raise Refused('the size of a large file is not set (meta large_file_bytes): ask the user first')
        f = self.one('SELECT * FROM file WHERE thing_id=?', (tid,))
        if not f['size'] or f['size'] < int(large):
            raise Refused('only large files are proposed for deletion')
        if not f['downloaded_at']:
            raise Refused('the download date is unknown')
        limit = (datetime.datetime.strptime(self.now()[:10], '%Y-%m-%d')
                 - datetime.timedelta(days=730)).strftime('%Y-%m-%d')
        if f['downloaded_at'][:10] > limit:
            raise Refused('a file is proposed for deletion only 2 years after it was downloaded')
        if self.one("SELECT 1 FROM link l JOIN followup f ON f.thing_id=l.from_id WHERE l.to_id=? "
                    "AND l.role='about' AND f.status IN ('open','deferred')", (tid,)):
            raise Refused('a deletion question about this file is already open')
        user, mar = int(self.meta('user_party_id')), int(self.meta('marionette_party_id'))
        rule = self.permit('decision_needed', 'followup', 'create', 'claude', None)
        saved, self.ctx['rule'] = self.ctx['rule'], rule
        q = self.create_followup('decision_needed', {
            'title': f'delete the large file {f["stored_name"] or f["original_name"]}?', 'holder': user,
            'details': {'question': 'This large file was downloaded more than 2 years ago. Delete it?',
                        'options': ['keep', 'delete'], 'recommendation': 'keep', 'requested_by': mar}})['id']
        self.ctx['rule'] = saved
        self.add_link(q, tid, 'about')
        return {'id': tid, 'question_id': q}

    def a_delete(self, tid, p):
        self.audit(tid, 'delete', note='the user deleted this file himself; the program never deletes files')

    # ================= system memory =================
    def create_decision(self, p):
        self.require(p, 'verbatim', 'said_at')
        ev = self.ctx['evidence'] or {}
        if str(ev.get('quote', '')).strip() != str(p['verbatim']).strip():
            raise Refused('a decision is recorded only from the user words: the quote must be the verbatim text')
        if ev.get('inferred'):
            raise Refused('a decision is never recorded from an inference')
        sess = p.get('session_id', ev.get('source'))
        tid = self.new_thing('decision', p.get('title') or p['verbatim'][:80])
        self.conn.execute('INSERT INTO decision(thing_id,verbatim,said_at,session_id) VALUES(?,?,?,?)',
                          (tid, p['verbatim'], p['said_at'], sess))
        return {'id': tid}

    def a_supersede(self, tid, p):
        self.require(p, 'by')
        if self.thing(p['by'])['type'] != 'decision' or p['by'] == tid:
            raise Refused('a decision is superseded by another recorded decision')
        self.set('decision', tid, 'superseded_by', p['by'])

    def create_rule(self, p):
        self.require(p, 'text', 'decision_id', 'enforced_by')
        d = self.one('SELECT status FROM decision WHERE thing_id=?', (p['decision_id'],))
        if not d:
            raise Refused(f'thing {p["decision_id"]} is not a recorded decision')
        if d['status'] != 'in_force':
            raise Refused('a rule comes only from a decision in force')
        tid = self.new_thing('rule', p.get('title') or p['text'][:80])
        self.conn.execute('INSERT INTO rule(thing_id,text,decision_id,scope,enforced_by) VALUES(?,?,?,?,?)',
                          (tid, p['text'], p['decision_id'], json.dumps(p.get('scope') or {}, ensure_ascii=False),
                           p['enforced_by']))
        return {'id': tid}

    def a_edit_text(self, tid, p):
        self.require(p, 'text')
        self.set('rule', tid, 'text', p['text'])

    def create_job(self, p):
        self.require(p, 'title', 'instructions', 'schedule')
        p['schedule'] = json.dumps(parse_schedule(p['schedule']), ensure_ascii=False)
        tid = self.new_thing('job', p['title'])
        self.conn.execute('INSERT INTO job(thing_id,instructions,schedule,channels,send_permission,approved_texts) '
                          'VALUES(?,?,?,?,?,?)', (tid, p['instructions'], p['schedule'],
                                                  json.dumps(p.get('channels') or []),
                                                  p.get('send_permission', 'draft_only'),
                                                  json.dumps(p.get('approved_texts') or [], ensure_ascii=False)))
        return {'id': tid}

    def a_mark_period_done(self, tid, p):
        self.require(p, 'period')
        if p['period'] not in [x['period'] for x in self.due_jobs() if x['job_id'] == tid]:
            raise Refused(f'period {p["period"]} is not a due period of this job')
        last = self.one('SELECT last_period FROM job WHERE thing_id=?', (tid,))[0]
        if last and p['period'] <= last:
            raise Refused(f'period {p["period"]} is not after the last one done ({last})')
        self.set('job', tid, 'last_period', p['period'])

    def a_start(self, target, p):
        tid = self.new_thing('run', p.get('title') or 'run ' + self.now())
        self.conn.execute('INSERT INTO run(thing_id,started,trigger_kind) VALUES(?,?,?)',
                          (tid, self.now(), p.get('trigger_kind', 'schedule')))
        return {'id': tid}

    SKIP_CODES = ('tool_absent', 'page_failed', 'permission_refused', 'not_due', 'partly_read')

    def a_note_skip(self, tid, p):
        """A channel this run did not read, with a reason from the closed list and one plain sentence."""
        self.require(p, 'channel', 'code', 'text')
        if p['code'] not in self.SKIP_CODES:
            raise Refused('the reason for not reading a channel is one of: ' + ', '.join(self.SKIP_CODES))
        cur = json.loads(self.one('SELECT summary FROM run WHERE thing_id=?', (tid,))[0])
        skips = [s for s in cur.get('skips', []) if s['channel'] != p['channel']]
        skips.append({'channel': p['channel'], 'code': p['code'], 'text': p['text'], 'at': self.now()})
        cur['skips'] = skips
        self.set('run', tid, 'summary', json.dumps(cur, ensure_ascii=False))

    def a_close(self, tid, p):
        if p.get('failed'):
            status = 'failed'
        else:
            gaps = self.one('SELECT count(*) FROM source WHERE run_id=? AND verdict IS NULL', (tid,))[0]
            status = 'complete_with_gaps' if gaps else 'complete'
        counts = {r[0] or NO_VERDICT: r[1] for r in self.conn.execute(
            'SELECT verdict, count(*) FROM source WHERE run_id=? GROUP BY verdict', (tid,))}
        cur = json.loads(self.one('SELECT summary FROM run WHERE thing_id=?', (tid,))[0])
        self.set('run', tid, 'summary', json.dumps({**cur, 'verdicts': counts, **(p.get('summary') or {})},
                                                    ensure_ascii=False))
        self.set('run', tid, 'ended', self.now())
        self.set('run', tid, 'status', status)
        return {'status_set': True}

    # ================= any thing =================
    def a_link(self, tid, p):
        self.require(p, 'to_id', 'role')
        if p['to_id'] == tid:
            raise Refused('a thing is not linked to itself')
        self.add_link(tid, p['to_id'], p['role'], p.get('inferred', False))

    def a_confirm_values(self, tid, p):
        names = p.get('names')
        if not isinstance(names, list) or not names:
            raise Refused('name the values to confirm')
        table = self.details_table(tid)
        cur = json.loads(self.one(f'SELECT details FROM {table} WHERE thing_id=?', (tid,))[0])
        marked = set(cur.get('_inferred', []))
        if not set(names) <= marked:
            raise Refused('not marked as inferred: ' + ', '.join(sorted(set(names) - marked)))
        self.set_details(table, tid, {'_inferred': sorted(marked - set(names))})

    def a_add_evidence(self, tid, p):
        if not self.ctx.get('evidence_id'):
            raise Refused('give the evidence: a source number and the verbatim quote')

    # ================= reading (no writing) =================
    def show(self, tid):
        t = dict(self.thing(tid))
        table = self.table_of(t['type'], t['grp'])
        row = self.one(f'SELECT * FROM {table} WHERE thing_id=?', (tid,))
        t['record'] = dict(row) if row else None
        t['links'] = [dict(r) for r in self.conn.execute(
            'SELECT from_id,to_id,role,inferred FROM link WHERE from_id=? OR to_id=?', (tid, tid))]
        t['evidence'] = [dict(r) for r in self.conn.execute('SELECT * FROM evidence WHERE thing_id=?', (tid,))]
        if t['type'] == 'party':
            t['handles'] = [dict(r) for r in self.conn.execute(
                'SELECT kind,value FROM party_handle WHERE party_id=?', (tid,))]
        return t

    def history(self, tid):
        return [dict(r) for r in self.conn.execute('SELECT * FROM audit WHERE thing_id=? ORDER BY id', (tid,))]

    def allowed(self, type_code=None):
        seed = load_seed()
        q = 'SELECT scope,action,actor,from_status,to_status,needs_evidence FROM action_rule'
        rows = [dict(r) for r in self.conn.execute(q + ' ORDER BY id')]
        if type_code:
            grp = self.type_row(type_code)['grp']
            rows = [r for r in rows if r['scope'] in (type_code, grp, '*')]
        for r in rows:
            r['action_ar'] = seed.ACTION_AR.get(r['action'], r['action'])
        return rows

    def due_jobs(self):
        """Every period of every enabled job that has come and is not done, oldest first.
        No period is skipped: a missed one stays listed, marked late, until it is done."""
        now_dt = datetime.datetime.strptime(self.now()[:16], '%Y-%m-%d %H:%M')
        out = []
        for j in self.conn.execute("SELECT j.*, t.title, t.created_at FROM job j JOIN thing t ON t.id=j.thing_id "
                                   "WHERE j.status='enabled' ORDER BY t.id"):
            sched = parse_schedule(j['schedule'])
            first = datetime.datetime.strptime(j['created_at'][:10], '%Y-%m-%d').date()
            occ = [o for o in occurrences(sched, first, now_dt, self.meta('week_start', 'mon')) if not j['last_period'] or o[0] > j['last_period']]
            for i, (period, when) in enumerate(occ):
                out.append({'job_id': j['thing_id'], 'title': j['title'], 'period': period, 'due_at': when,
                            'late': i < len(occ) - 1})
        return out

    # ---------- the late rule ----------
    # A follow-up thing still alive is late when its due date has passed, OR when its next step is with the
    # user (holder = the user), it has no due date, and one full working day has passed since it first
    # appeared. Working days come from meta "workdays" (set when the database is created). A bare due date counts as the whole day.
    def workdays(self):
        try:
            return set(json.loads(self.meta('workdays', '["mon","tue","wed","thu","fri"]')))
        except sqlite3.Error:
            return {'mon', 'tue', 'wed', 'thu', 'fri'}

    @staticmethod
    def as_time(v):
        v = (v or '').strip()
        for fmt, n in (('%Y-%m-%d %H:%M:%S', 19), ('%Y-%m-%d %H:%M', 16)):
            try:
                return datetime.datetime.strptime(v[:n], fmt)
            except ValueError:
                pass
        try:
            return datetime.datetime.strptime(v[:10], '%Y-%m-%d') + datetime.timedelta(days=1)
        except ValueError:
            return None

    def first_seen(self, tid):
        """When the thing first appeared: the earliest time quoted in its evidence lines or recorded on them,
        never later than when it was written into the database."""
        times = [self.as_time(self.thing(tid)['created_at'])]
        for e in self.conn.execute('SELECT quote, quote_date FROM evidence WHERE thing_id=?', (tid,)):
            m = re.match(r'^- (\d{4}-\d\d-\d\d \d\d:\d\d)', e['quote'] or '')
            if m:
                times.append(datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M'))
            if e['quote_date'] and len(e['quote_date']) >= 16:
                times.append(self.as_time(e['quote_date']))
        return min(t for t in times if t)

    def working_hours_since(self, t0, now):
        wd, h, t = self.workdays(), 0.0, t0
        while t < now:
            nxt = min(datetime.datetime.combine(t.date() + datetime.timedelta(days=1), datetime.time()), now)
            if WEEKDAYS[t.weekday()] in wd:
                h += (nxt - t).total_seconds() / 3600
            t = nxt
        return h

    def late_reason(self, r):
        """r has id, status, due, holder_id. Returns why it is late, or None."""
        if r['status'] not in ('open', 'deferred', 'new'):
            return None
        now = self.as_time(self.now())
        if r['due']:
            d = self.as_time(r['due'])
            if d and d <= now:
                return (LATE_TEXT.get(self.meta('language', 'en'), LATE_TEXT['en'])[0]).format(d=r['due'])
            return None
        if r['status'] in ('open', 'new') and str(r['holder_id']) == self.meta('user_party_id'):
            t0 = self.first_seen(r['id'])
            if self.working_hours_since(t0, now) >= 24:
                return (LATE_TEXT.get(self.meta('language', 'en'), LATE_TEXT['en'])[1]).format(d=t0.strftime('%Y-%m-%d'))
        return None

    def late(self):
        """Every follow-up thing that is late now, with the reason, oldest first."""
        out = []
        for r in self.conn.execute("SELECT t.id,t.type,t.title,f.status,f.due,f.holder_id FROM followup f "
                                   "JOIN thing t ON t.id=f.thing_id WHERE f.status IN ('open','deferred','new') "
                                   "AND t.type NOT IN ('draft','reminder','deferred_check') ORDER BY t.id"):
            why = self.late_reason(dict(r))
            if why:
                out.append({**dict(r), 'why': why})
        return out

    def due(self):
        """Follow-up things that need attention now: late, reminders due, checks due."""
        out = []
        for r in self.conn.execute('SELECT t.id,t.type,t.title,f.status,f.due,f.next_check FROM followup f '
                                   'JOIN thing t ON t.id=f.thing_id ORDER BY t.id'):
            r = dict(r)
            why = None
            if r['status'] in ('open', 'deferred') and r['due'] and self.passed(r['due']):
                why = 'late'
            elif r['status'] in ('open', 'deferred') and r['next_check'] and self.passed(r['next_check'], True):
                why = 'check due'
            elif r['status'] == 'scheduled' and r['type'] == 'reminder' and self.passed(r['due'], True):
                why = 'reminder due'
            elif r['status'] == 'scheduled' and r['type'] == 'deferred_check' and self.passed(r['next_check'], True):
                why = 'check due'
            if why:
                r['why'] = why
                out.append(r)
        return out


def init(path, user_name, user_email=None, now=None, timezone=DEFAULT_TZ, workdays=None, week_start='mon',
         language='en'):
    zoneinfo.ZoneInfo(timezone)  # refuses an unknown zone before anything is written
    workdays = workdays or ['mon', 'tue', 'wed', 'thu', 'fri']
    if not set(workdays) <= set(WEEKDAYS) or week_start not in WEEKDAYS:
        raise Refused('days are written mon, tue, wed, thu, fri, sat, sun')
    if os.path.exists(path) and os.path.getsize(path) > 0:
        raise Refused(f'{path} already exists; a database is created once and never overwritten')
    conn = connect(path)
    conn.executescript(open(SCHEMA_FILE, encoding='utf-8').read())
    conn.execute('BEGIN')
    load_seed().seed(conn)
    conn.execute("INSERT INTO meta(key,value) VALUES('schema_version','0.1')")
    conn.execute('COMMIT')
    conn.close()
    door = Door(path, now=now or (lambda: local_now(timezone)))
    door.ctx = {'actor': 'program', 'action': 'create', 'run': None, 'evidence_id': None, 'held': None}
    door.conn.execute('BEGIN IMMEDIATE')
    me = door.new_thing('party', user_name)
    door.conn.execute("INSERT INTO party(thing_id,kind,relation,is_user,status) VALUES(?,?,?,1,'confirmed')",
                      (me, 'person', 'self'))
    if user_email:
        door.add_handles(me, [{'kind': 'email', 'value': user_email}])
    mar = door.new_thing('party', 'Marionette')
    door.conn.execute("INSERT INTO party(thing_id,kind,relation,status) VALUES(?,?,?,'confirmed')",
                      (mar, 'system', 'self'))
    # every user talks to Claude, so the channel of those sessions exists from the start:
    # an action in the user's name rests on his words recorded from it
    ch = door.new_thing('channel', SESSIONS_CHANNEL)
    door.conn.execute('INSERT INTO channel(thing_id,connection) VALUES(?,?)', (ch, 'claude'))
    door.conn.executemany('INSERT INTO meta(key,value) VALUES(?,?)',
                          [('user_party_id', str(me)), ('marionette_party_id', str(mar)),
                           ('sessions_channel_id', str(ch)), ('timezone', timezone),
                           ('workdays', json.dumps(workdays)), ('week_start', week_start),
                           ('language', language)])
    door.conn.execute('COMMIT')
    return door, me, mar


def main(argv=None):
    ap = argparse.ArgumentParser(description='Marionette database door')
    ap.add_argument('--db', required=True)
    sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('init')
    i.add_argument('--user-name', required=True)
    i.add_argument('--user-email')
    i.add_argument('--timezone', default=DEFAULT_TZ)
    i.add_argument('--workdays', default='mon,tue,wed,thu,fri')
    i.add_argument('--week-start', default='mon')
    i.add_argument('--language', default='en', choices=('en', 'ar'))
    d = sub.add_parser('do')
    d.add_argument('action')
    d.add_argument('--actor', required=True, choices=ACTORS)
    d.add_argument('--target', type=int)
    d.add_argument('--type')
    d.add_argument('--params', default='{}')
    d.add_argument('--evidence')
    d.add_argument('--run', type=int)
    for name in ('show', 'history'):
        s = sub.add_parser(name)
        s.add_argument('id', type=int)
    a = sub.add_parser('allowed')
    a.add_argument('--type')
    sub.add_parser('due')
    sub.add_parser('due-jobs')
    sub.add_parser('late')
    args = ap.parse_args(argv)
    try:
        if args.cmd == 'init':
            _, me, mar = init(args.db, args.user_name, args.user_email, timezone=args.timezone,
                              workdays=[x.strip() for x in args.workdays.split(',') if x.strip()],
                              week_start=args.week_start, language=args.language)
            out = {'created': args.db, 'user_party_id': me, 'marionette_party_id': mar}
        else:
            if not os.path.exists(args.db):
                raise Refused(f'{args.db} does not exist; run init first')
            door = Door(args.db)
            if args.cmd == 'do':
                out = door.do(args.action, args.actor, args.target, args.type, json.loads(args.params),
                              json.loads(args.evidence) if args.evidence else None, args.run)
            elif args.cmd == 'show':
                out = door.show(args.id)
            elif args.cmd == 'history':
                out = door.history(args.id)
            elif args.cmd == 'allowed':
                out = door.allowed(args.type)
            elif args.cmd == 'due-jobs':
                out = door.due_jobs()
            elif args.cmd == 'late':
                out = door.late()
            else:
                out = door.due()
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    except Refused as e:
        print(json.dumps({'refused': str(e)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
