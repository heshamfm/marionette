#!/usr/bin/env python3
"""Marionette by Hesham Elmahdy (github.com/heshamfm): move an installation from files to the database.

Version 1.5. Reads the Marionette files (the format Setup creates: index.tsv, items/, drafts.tsv, data/drafts/,
questions.md, reminders/, data/disposition.tsv, channels.md, jobs.md, state.json) and writes everything into one
SQLite database through the door program mdb.py only. Nothing is ever deleted.

Two steps, always in this order:

  1. Check (changes nothing in the installation):
     python3 migrate.py --followup DIR --approval "<the owner's own words>" --session-file sessions/<file>.md
     Builds a trial database in DIR/db/trial_<time>/, prints a report and writes report.json beside it.
     Exit code 0: everything fits and --apply may run. Exit code 1: the report lists what does not fit.

  2. Apply (only after the owner read the check's report and approved):
     the same command with --apply. It checks again, then builds DIR/db/marionette.db, copies the programs into
     DIR/tools/, writes DIR/tools/db_usage.md, moves the old memory files into DIR/archive/before_db_<date>/ and
     leaves a read-only placeholder at each old path, and records the move in state.json and runs.log.
     It refuses while a run holds the lock, when anything does not fit, or when DIR/db/marionette.db exists.

A new installation runs the same two steps right after Setup writes its empty starter files.

Undo: python3 migrate.py --followup DIR --undo puts the files back as they were before the move. Nothing is deleted:
the database, the placeholders and the installed programs are moved aside into DIR/archive/undone_<time>/. What was
recorded in the database after the move is not written back into the files; the result says how many changes that was.

--approval holds the owner's own words, quoted verbatim from the session in which they approved the move. The
database accepts actions in the owner's name (creating channels and jobs, postponing an item, marking a
"for information" item seen, dropping a draft the owner dropped) only on such words.
--map FILE (optional): JSON {"types": {"<your word>": "<template word>"}, "statuses": {...}} for an installation
whose index uses its own words for types or statuses.
"""
import argparse
import collections
import datetime
import json
import os
import re
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mdb  # noqa: E402

VERSION = '1.5'
PROGRAMS = ('mdb.py', 'mrun.py', 'schema_v0.1.sql', 'seed_v0.1.py', 'migrate.py')
DOORS = ('brief.py', 'run_gate.py', 'build_status.py')
OLD_MEMORY = ('index.tsv', 'items', 'drafts.tsv', 'data/drafts', 'questions.md', 'reminders', 'data/disposition.tsv')
OLD_CHANNEL = 'Marionette files before the database'

# the template's words, plus the Arabic words some installations use
TYPES = {'reply_needed': 'reply_needed', 'my_commitment': 'my_commitment', 'their_commitment': 'their_commitment',
         'decision_needed': 'decision_needed', 'fyi': 'fyi',
         'رد مطلوب مني': 'reply_needed', 'التزام قطعته أنا': 'my_commitment', 'التزام قطعه غيري': 'their_commitment',
         'التزام من الآخرين لي': 'their_commitment', 'قرار مطلوب مني': 'decision_needed', 'للعلم فقط': 'fyi'}
STATUSES = {'open': 'open', 'waiting_on_others': 'waiting_on_others', 'postponed': 'postponed', 'done': 'done',
            'closed_no_action': 'closed_no_action',
            'مفتوح': 'open', 'بانتظار رد الآخرين': 'waiting_on_others', 'مؤجل': 'postponed', 'منجز': 'done',
            'أُغلق دون إجراء': 'closed_no_action'}
NEEDED = ('## needed', '## المطلوب')
STORY = ('## story', '## القصة')
Q_OPEN = ('## open', '## مفتوحة')
Q_ANSWERED = ('## answered', '## مُجابة')
DAYNAMES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
DATE_RE = re.compile(r'^\d{4}-\d\d-\d\d( \d\d:\d\d)?$')
DISPOSITION_TYPE = {'calendar': 'calendar_event', 'meetings': 'meeting', 'meeting': 'meeting'}


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def read_tsv(path):
    if not os.path.exists(path):
        return []
    lines = read(path).split('\n')
    head = lines[0].split('\t')
    rows = []
    for n, line in enumerate(lines[1:], 2):
        if line.strip() and line.split('\t')[0] != head[0]:
            cells = line.split('\t')
            rows.append((n, line, dict(zip(head, cells + [''] * (len(head) - len(cells))))))
    return rows


def parse_item(path):
    head, needed, story, part = {}, [], [], 'head'
    for line in read(path).split('\n'):
        low = line.strip().lower()
        if low.startswith(NEEDED):
            part = 'needed'
            continue
        if low.startswith(STORY):
            part = 'story'
            continue
        if part == 'head':
            m = re.match(r'^([a-z_]+): ?(.*)$', line)
            if m:
                head[m.group(1)] = (m.group(2).strip(), line)
            elif line.startswith('# ') and 'title' not in head:
                head['title'] = (line[2:].strip(), line)
        elif part == 'needed':
            needed.append(line)
        elif line.startswith('- '):
            story.append(line)
    return head, '\n'.join(needed).strip(), story


def language_code(text):
    t = (text or '').strip().lower()
    return 'ar' if t.startswith('ar') or 'arab' in t or 'عرب' in t else 'en'


def week_start(days):
    for d in DAYNAMES:
        if d in days and DAYNAMES[(DAYNAMES.index(d) - 1) % 7] not in days:
            return d
    return 'mon'


FULLDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
DAY_WORD = r'(mon|tue|wed|thu|fri|sat|sun)[a-z]*'
TIME = r'(\d{1,2}):(\d\d)'
END = r'(?:$|[ ,;(])'


def parse_schedule(text):
    """A job schedule from jobs.md, read strictly from the start of the cell; anything else is not guessed.
    Accepted: JSON as mdb.py takes it; "HH:MM" or "every day HH:MM" or "daily HH:MM"; "working days HH:MM";
    "Sun-Thu HH:MM" (a range of days); "Monday HH:MM"; "day N HH:MM" or "day N, HH:MM" (monthly).
    Text after the time (", covering ...") is allowed and ignored."""
    t = (text or '').strip()
    if t.startswith('{'):
        try:
            return json.loads(t)
        except ValueError:
            return None
    low = t.lower()

    def at(m, g):
        return f'{int(m.group(g)):02d}:{m.group(g + 1)}'
    m = re.match(r'^(?:every day|daily)\s+' + TIME + END, low) or re.match(r'^' + TIME + END, low)
    if m:
        return {'every': 'day', 'at': at(m, 1)}
    m = re.match(r'^(?:working days|weekdays|workdays)\s+' + TIME + END, low)
    if m:
        return {'every': 'day', 'at': at(m, 1), 'days': 'WORKDAYS'}
    m = re.match(r'^' + DAY_WORD + r'\s*-\s*' + DAY_WORD + r'\s+' + TIME + END, low)
    if m:
        a, b = DAYNAMES.index(m.group(1)), DAYNAMES.index(m.group(2))
        days = [DAYNAMES[(a + k) % 7] for k in range((b - a) % 7 + 1)]
        return {'every': 'day', 'at': at(m, 3), 'days': days}
    m = re.match(r'^(?:every\s+)?' + DAY_WORD + r'\s+' + TIME + END, low)
    if m and (m.group(0).split()[-2] if m.group(0).startswith('every') else m.group(0).split()[0]).rstrip(',') \
            in FULLDAYS + DAYNAMES:
        return {'every': 'week', 'day': m.group(1), 'at': at(m, 2)}
    m = re.match(r'^(?:monthly on day|monthly|day)\s+(\d{1,2}),?\s+' + TIME + END, low)
    if m and 1 <= int(m.group(1)) <= 28:
        return {'every': 'month', 'day': int(m.group(1)), 'at': at(m, 2)}
    return None


class Migration:
    def __init__(self, a, db_path):
        self.a, self.F, self.db = a, a.followup, db_path
        self.problems = []    # what does not fit: --apply refuses while there is any
        self.choices = []     # what the program decided where the files leave room for more than one reading
        self.counts = collections.Counter()
        self.ids, self.ch, self.party_by_email, self.party_by_text = {}, {}, {}, {}
        self.src_of = {}
        extra = json.loads(read(a.map)) if a.map else {}
        self.types = {**TYPES, **extra.get('types', {})}
        self.statuses = {**STATUSES, **extra.get('statuses', {})}

    def path(self, *p):
        return os.path.join(self.F, *p)

    def problem(self, kind, what, why):
        self.problems.append({'kind': kind, 'what': what, 'why': why})

    def do(self, what, action, actor, target=None, type=None, params=None, evidence=None):
        try:
            return self.door.do(action, actor, target, type, params, evidence, self.run)
        except mdb.Refused as e:
            self.problem('refused', f'{what}: {action}', str(e))
            return None

    def file_source(self, rel, title):
        r = self.do(rel, 'record', 'claude', type='external_record',
                    params={'channel_id': self.ch[OLD_CHANNEL], 'external_id': rel, 'title': title[:200],
                            'permalink': rel, 'details': {'record_kind': 'marionette_file'}})
        if r:
            self.do(rel, 'read', 'claude', r['id'], params={'read_state': 'full'})
            return r['id']

    def settle(self, sid):
        """Every file source ends with a verdict: linked when something rests on it."""
        if sid is None:
            return
        tied = self.door.conn.execute('SELECT 1 FROM evidence WHERE source_id=? UNION SELECT 1 FROM link WHERE '
                                      'from_id=? OR to_id=?', (sid, sid, sid)).fetchone()
        if tied:
            self.do(sid, 'verdict', 'claude', sid, params={'verdict': 'linked'})
        else:
            self.do(sid, 'verdict', 'claude', sid, params={'verdict': 'ignored',
                                                            'reason': 'empty: nothing in this file to carry over'})

    # ------------------------------------------------------------------------------------------------
    def build(self):
        a = self.a
        st = json.loads(read(self.path('state.json')))
        owner = st.get('owner', {})
        self.state = st
        nums = owner.get('working_days') or [0, 1, 2, 3, 4]
        days = [DAYNAMES[int(n)] for n in nums]
        name = owner.get('name') or a.user_name
        if not name:
            raise SystemExit('state.json has no owner name; give --user-name')
        self.user_email = (owner.get('email') or a.user_email or '').lower()
        self.door, self.me, _ = mdb.init(self.db, name, self.user_email or None,
                                         timezone=owner.get('timezone') or a.timezone or 'UTC', workdays=days,
                                         week_start=week_start(days), language=language_code(owner.get('language')))
        self.workdays = days
        self.run = None
        r = self.door.do('start', 'program', type='run', params={'title': 'move from files to the database',
                                                                  'trigger_kind': 'migration'})
        self.run = r['id']
        sess = int(self.door.meta('sessions_channel_id'))
        s = self.do('session', 'record', 'claude', type='session',
                    params={'channel_id': sess, 'external_id': a.session_file, 'title': 'session approving the move',
                            'details': {'quotes': [a.approval]}})
        self.session = s['id']
        self.do('session', 'read', 'claude', self.session, params={'read_state': 'full'})
        self.owner_ev = {'source': self.session, 'quote': a.approval}
        self.channels()
        self.items()
        self.questions()
        self.reminders()
        self.dispositions()
        self.drafts()
        self.jobs()
        self.settle(self.session)
        for sid in self.src_of.values():
            self.settle(sid)
        self.do('run', 'close', 'program', self.run)
        return self.report()

    def channels(self):
        r = self.do('channel', 'create', 'user', type='channel', evidence=self.owner_ev,
                    params={'title': OLD_CHANNEL, 'connection': 'files',
                            'reads': 'the Marionette files as they were before the database, read-only'})
        self.ch[OLD_CHANNEL] = r['id']
        txt = read(self.path('channels.md')) if os.path.exists(self.path('channels.md')) else ''
        marks = self.state.get('watermarks') or {}
        for m in re.finditer(r'(?m)^## (\S+)\s*\n((?:(?!^## ).*\n?)*)', txt):
            n, body = m.group(1), m.group(2)
            how = re.search(r'(?m)^how: *(.*)$', body)
            r = self.do('channel ' + n, 'create', 'user', type='channel', evidence=self.owner_ev,
                        params={'title': n, 'connection': 'see channels.md, section ' + n,
                                'reads': how.group(1)[:500] if how else None})
            if not r:
                continue
            self.ch[n] = r['id']
            self.counts['channels'] += 1
            w = marks.get(n)
            if w and re.match(r'^\d{4}-\d\d-\d\d \d\d:\d\d', str(w)):
                self.do('watermark ' + n, 'update_watermark', 'claude', r['id'], params={'watermark': str(w)[:16]})
            if not re.search(r'(?m)^status: *enabled', body):
                self.choices.append(f'channel {n} is not enabled in channels.md; it was created like the others, '
                                    'and the end-of-run check reads channels.md, so it is not checked')

    def party(self, text, sid, quote):
        """The parties of a counterparty text: one per email address (the first holds the next step), the owner
        when the text names the owner's address, or one unconfirmed party named exactly as written.
        Never a match on a similar name."""
        t = (text or '').strip()
        emails = []
        for e in EMAIL_RE.findall(t):
            if e.lower() not in emails:
                emails.append(e.lower())
        if self.user_email and self.user_email in emails:
            emails.remove(self.user_email)
            if not emails:
                return self.me, [], False
        if not emails:
            if not t or t == '-':
                return None, [], False
            if t not in self.party_by_text:
                r = self.do('party ' + t, 'create', 'claude', type='party', params={'kind': 'person', 'title': t[:200]},
                            evidence={'source': sid, 'quote': quote})
                if not r:
                    return None, [], False
                self.party_by_text[t] = r['id']
                self.counts['parties'] += 1
            return self.party_by_text[t], [], False
        ids, rest = [], t
        for e in emails:
            if e not in self.party_by_email:
                pos = rest.lower().find(e)
                title = rest[:pos].strip(' ,;:()<>-') if pos > 0 else ''
                r = self.do('party ' + e, 'create', 'claude', type='party',
                            params={'kind': 'person', 'title': (title or e)[:200],
                                    'handles': [{'kind': 'email', 'value': e}]},
                            evidence={'source': sid, 'quote': quote})
                if not r:
                    return None, [], False
                self.party_by_email[e] = r['id']
                self.counts['parties'] += 1
            pos = rest.lower().find(e)
            rest = rest[pos + len(e):] if pos >= 0 else rest
            ids.append(self.party_by_email[e])
        return ids[0], [x for x in ids[1:] if x != ids[0]], len(ids) > 1

    def unknown_party(self, sid, quote):
        if 'unknown' not in self.party_by_text:
            r = self.do('unknown party', 'create', 'claude', type='party',
                        params={'kind': 'person', 'title': 'Counterparty not named in the old files'},
                        evidence={'source': sid, 'quote': quote, 'inferred': True})
            self.party_by_text['unknown'] = r['id'] if r else None
        return self.party_by_text['unknown']

    def items(self):
        rows = [(r, 'index.tsv', line) for _, line, r in read_tsv(self.path('index.tsv'))]
        arch = self.path('archive')
        if os.path.isdir(arch):
            for f in sorted(os.listdir(arch)):
                if f.endswith('.tsv') and f.startswith('index'):
                    rows += [(r, 'archive/' + f, line) for _, line, r in read_tsv(os.path.join(arch, f))]
        seen = set()
        for r, where, line in rows:
            key = (r.get('key') or '').strip()
            if not key or key in seen:
                if key:
                    self.choices.append(f'item {key} appears twice in the index files; the first row was used')
                continue
            seen.add(key)
            self.counts['items_in_files'] += 1
            rel = f'items/{key}.md'
            if os.path.exists(self.path(rel)):
                head, needed, story = parse_item(self.path(rel))
            else:
                rel, head, needed, story = where, {}, '', []
                self.choices.append(f'item {key} has no file in items/; it rests on its row in {where}')
            sid = self.src_of.get(rel) or self.file_source(rel, r.get('title') or key)
            self.src_of[rel] = sid
            if sid is None:
                continue
            self.item(key, r, head, needed, story or [line], sid)

    def item(self, key, r, head, needed, story, sid):
        oldt, olds = (r.get('type') or '').strip(), (r.get('status') or '').strip()
        ty, status = self.types.get(oldt), self.statuses.get(olds)
        title = (r.get('title') or '').strip() or key
        if not ty:
            return self.problem('item', f'{key} ({title})', f'type "{oldt}" is not one the program knows; '
                                'give its meaning with --map')
        if not status:
            return self.problem('item', f'{key} ({title})', f'status "{olds}" is not one the program knows; '
                                'give its meaning with --map')
        cp_quote = head.get('counterparty', ('', 'counterparty: ' + (r.get('counterparty') or '')))[1]
        cp, others, guessed = self.party(r.get('counterparty'), sid, cp_quote)
        d = {'old_key': key, 'old_type': oldt, 'old_status': olds, 'counterparty_text': r.get('counterparty', ''),
             'record_text': r.get('record', ''), 'last_event_text': r.get('last_event', '')}
        text = needed or title
        links, inferred = {}, []
        holder = self.me
        needs_other = ty in ('their_commitment', 'reply_needed') or status == 'waiting_on_others'
        if needs_other and cp in (None, self.me):
            cp = self.unknown_party(sid, cp_quote)
            inferred.append('holder' if status == 'waiting_on_others' else 'counterparty')
            self.choices.append(f'item {key} ({title}) names no other party; it is tied to "Counterparty not named '
                                'in the old files", marked as an inference')
        if status == 'waiting_on_others':
            holder = cp
        if ty == 'my_commitment':
            kind, d['text'], links['promised_by'] = 'commitment', text, self.me
            if cp not in (None, self.me):
                links['promised_to'] = cp
        elif ty == 'their_commitment':
            kind, d['text'], links['promised_by'] = 'commitment', text, cp
            links['promised_to'] = self.me
        elif ty == 'reply_needed':
            kind, d['request'], links['requested_by'] = 'reply_needed', text, cp
        elif ty == 'decision_needed':
            kind, d['question'] = 'decision_needed', text
        else:
            kind, d['what_happened'] = 'for_info', text
            d['why_it_matters'] = 'not written in the old files'
            inferred.append('why_it_matters')
        dl = (r.get('deadline') or '').strip()
        due = dl if DATE_RE.match(dl) else None
        if dl and not due:
            d['deadline_text'] = dl
            self.choices.append(f'item {key} ({title}): the deadline "{dl}" is not a date; it is kept as text and '
                                'the item counts as having no deadline')
        nc = head.get('next_check', ('', ''))[0]
        if guessed:
            inferred.append('holder' if holder == cp else 'counterparty')
            d['inferred_note'] = 'the first address in the counterparty text was taken as the main party'
        p = {'title': title, 'holder': holder, 'details': d, 'due': due,
             'next_check': nc if DATE_RE.match(nc or '') else None, **links,
             'parties': [{'party': x, 'role': 'participant'} for x in others]}
        if inferred:
            p['_inferred'] = sorted(set(inferred))
        res = self.do(key, 'create', 'claude', type=kind, params=p,
                      evidence={'source': sid, 'quote': story[0], 'position': 'first line of the story'})
        if not res:
            return
        tid = self.ids[key] = res['id']
        self.counts['items'] += 1
        for line in story[1:]:
            self.do(key, 'add_evidence', 'claude', tid, evidence={'source': sid, 'quote': line, 'position': 'story'})
        last = {'source': sid, 'quote': story[-1], 'position': 'last line of the story'}
        if kind == 'for_info':
            if status in ('done', 'closed_no_action'):
                self.do(key, 'mark_seen', 'user', tid, evidence=self.owner_ev)
        elif status == 'postponed':
            self.do(key, 'defer', 'user', tid, evidence=self.owner_ev)
        elif status == 'done':
            self.do(key, 'complete', 'claude', tid, params={'close_reason': 'done'}, evidence=last)
        elif status == 'closed_no_action':
            self.do(key, 'complete', 'claude', tid, params={'close_reason': 'not_needed'}, evidence=last)

    def questions(self):
        rel = 'questions.md'
        if not os.path.exists(self.path(rel)):
            return
        sid = self.src_of[rel] = self.file_source(rel, 'questions to the owner')
        part = None
        for line in read(self.path(rel)).split('\n'):
            low = line.strip().lower()
            if low.startswith(Q_OPEN):
                part = 'open'
                continue
            if low.startswith(Q_ANSWERED):
                part = 'answered'
                continue
            if not part or not line.startswith('- '):
                continue
            self.counts['questions_in_files'] += 1
            cells = [c.strip() for c in line[2:].split(' | ')]
            if len(cells) < 4:
                self.problem('question', line[:100], 'the line does not follow "- time | Qn | about | question"')
                continue
            asked, qid, about, rest = cells[0], cells[1], cells[2], cells[3:]
            d = {'question': ' | '.join(rest), 'kind': 'question', 'asked_at': asked, 'old_question': qid}
            if len(rest) > 1:
                d['recommendation'] = rest[-1]
            res = self.do(qid, 'create', 'claude', type='decision_needed', evidence={'source': sid, 'quote': line},
                          params={'title': f'{qid}: {rest[0][:90]}', 'holder': self.me, 'details': d,
                                  'next_check': asked[:10] if DATE_RE.match(asked[:10]) else None})
            if not res:
                continue
            self.counts['questions'] += 1
            if about in self.ids:
                self.do(qid, 'link', 'claude', res['id'], params={'to_id': self.ids[about], 'role': 'about'},
                        evidence={'source': sid, 'quote': line})
            if part == 'answered':
                self.do(qid, 'record_decision', 'claude', res['id'],
                        params={'decision': ' | '.join(rest), '_inferred': ['decision']},
                        evidence={'source': sid, 'quote': line})
        self.choices.append('an answered question keeps its whole line as the recorded answer, marked as an '
                            'inference, because the old line does not separate the question from the answer')

    def reminders(self):
        folder = self.path('reminders')
        if not os.path.isdir(folder):
            return
        for f in sorted(x for x in os.listdir(folder) if x.endswith('.md')):
            rel = 'reminders/' + f
            lines = read(self.path(rel)).split('\n')
            self.counts['reminders_in_files'] += 1

            def get(k):
                return next((ln for ln in lines if ln.lower().startswith(k + ':')), None)
            due_l, done_l = get('due'), get('delivered')
            due = due_l.split(':', 1)[1].strip() if due_l else ''
            body = '\n'.join(ln for ln in lines if ln.strip() and not re.match(r'^(due|delivered|source):', ln,
                                                                                 re.I)).strip() or f[:-3]
            sid = self.src_of[rel] = self.file_source(rel, f[:-3])
            p = {'title': body.split('\n')[0][:120], 'holder': self.me, 'details': {'text': body, 'old_file': rel}}
            if DATE_RE.match(due):
                p['due'] = due
            else:
                p['due'] = self.door.now()[:16]
                p['_inferred'] = ['due']
                p['details']['no_date_in_old_file'] = True
                self.choices.append(f'reminder {f} has no date; it is due at the moment of the move, so it is shown '
                                    'in the next report, as the old files showed it')
            res = self.do(rel, 'create', 'claude', type='reminder', params=p,
                          evidence={'source': sid, 'quote': due_l or lines[0], 'position': 'due line'})
            if not res:
                continue
            self.counts['reminders'] += 1
            if done_l and done_l.split(':', 1)[1].strip():
                self.do(rel, 'show', 'program', res['id'])

    def drafts(self):
        rows = read_tsv(self.path('drafts.tsv'))
        if not rows:
            return
        rsid = self.src_of['drafts.tsv'] = self.file_source('drafts.tsv', 'drafts register')
        mail = next((c for c in ('mail', 'gmail', 'email') if c in self.ch), None)
        made, pending = {}, []
        for n, line, r in rows:
            did = (r.get('draft_id') or '').strip()
            self.counts['drafts_in_files'] += 1
            st = (r.get('status') or '').strip()
            rel = f'data/drafts/{did}.txt'
            txt = read(self.path(rel)) if os.path.exists(self.path(rel)) else ''
            if not txt:
                txt = '(the full text was not saved in the old files)'
                self.choices.append(f'draft {did} has no saved text; it is carried over with a note saying so')
            head = txt.split('\n')
            to = next((x.split(':', 1)[1].strip() for x in head if x.lower().startswith('to:')), '')
            cc = next((x.split(':', 1)[1].strip() for x in head if x.lower().startswith('cc:')), '')
            subj = next((x.split(':', 1)[1].strip() for x in head if x.lower().startswith('subject:')), '')
            chn = (r.get('channel') or '').strip()
            cid = self.ch.get(chn) or (self.ch.get(mail) if mail else None)
            if cid is None:
                self.problem('draft', did, f'its channel "{chn}" is not in channels.md and there is no mail channel')
                continue
            key = (r.get('item_key') or '').strip()
            det = {'text': txt, 'channel_id': cid, 'recipients': to or '(not written in the old file)', 'cc': cc,
                   'subject': subj, 'old_draft_id': did, 'old_status': st,
                   'kind': 'reply' if key.startswith(('mail-', 'gmail-')) else 'new', 'mail_draft_id': did}
            if DATE_RE.match((r.get('created') or '').strip()):
                det['created_before_move'] = r['created'].strip()
            if key in self.ids:
                det['serves'] = self.ids[key]
            m = re.match(r'^(?:mail|gmail)-(.+)-\d+$', key)
            if det['kind'] == 'reply':
                rt = self.thread_source(cid, m.group(1)) if m else None
                if rt:
                    det['replies_to'] = rt
                else:
                    det['kind'] = 'new'
            res = self.do(did, 'create', 'claude', type='draft', params={'title': subj or did, 'holder': self.me,
                                                                         'details': det})
            if not res:
                continue
            t = res['id']
            self.counts['drafts'] += 1
            made[n] = (key, t)
            if key in self.ids:
                self.do(did, 'link', 'claude', t, params={'to_id': self.ids[key], 'role': 'serves'},
                        evidence={'source': rsid, 'quote': line, 'position': f'line {n}'})
            if st in ('waiting', 'scheduled', ''):
                continue
            if st == 'sent_as_is':
                self.do(did, 'mark_sent_as_is', 'claude', t)
            elif st in ('sent_edited', 'sent_unverified_text'):
                self.do(did, 'mark_sent_edited', 'claude', t)
                if st == 'sent_unverified_text':
                    self.choices.append(f'draft {did} was sent but its sent text was never compared; it is recorded '
                                        'as sent with changes, the weaker claim')
            elif st in ('deleted_no_reply', 'superseded', 'discarded_by_claude'):
                pending.append((n, line, did, key, st, t))
            elif st.startswith('discarded_by'):
                self.do(did, 'abandon', 'user', t, params={'reason': st}, evidence=self.owner_ev)
            else:
                self.problem('draft', did, f'status "{st}" is not one the program knows')
        # drafts Claude dropped are settled after every row exists, so a newer draft can be named
        for n, line, did, key, st, t in pending:
            newer = [tid for m, (k, tid) in sorted(made.items()) if m > n and k == key and key]
            p = {'reason': st}
            if st == 'superseded' and newer:
                p['superseded_by'] = newer[0]
                self.do(did, 'abandon', 'claude', t, params=p)
            else:
                p['gone_from_mail'] = True
                self.do(did, 'abandon', 'claude', t, params=p,
                        evidence={'source': rsid, 'quote': line, 'position': f'line {n}'})

    def thread_source(self, cid, thread):
        """The mail thread a draft answers: the source already recorded for it, or a new one marked as not read,
        because the move knows only its id, from the drafts register."""
        row = self.door.conn.execute('SELECT thing_id FROM source WHERE channel_id=? AND external_id=?',
                                     (cid, thread)).fetchone()
        if row:
            return row[0]
        r = self.do('thread ' + thread, 'record', 'claude', type='message',
                    params={'channel_id': cid, 'external_id': thread, 'title': 'mail thread ' + thread,
                            'details': {'direction': 'incoming'}})
        if r:
            self.do(r['id'], 'read', 'claude', r['id'], params={
                'read_state': 'failed', 'reason': 'not read during the move: only its id is known, from the drafts '
                                                  'register, as the thread a draft answers'})
            return r['id']

    def dispositions(self):
        rows = read_tsv(self.path('data/disposition.tsv'))
        if not rows:
            return
        sid = self.src_of['data/disposition.tsv'] = self.file_source('data/disposition.tsv', 'reading register')
        repeats = 0
        for n, line, r in rows:
            self.counts['dispositions_in_files'] += 1
            chn = (r.get('source') or '').strip()
            if chn not in self.ch:
                r2 = self.do('channel ' + chn, 'create', 'user', type='channel', evidence=self.owner_ev,
                             params={'title': chn or 'unnamed', 'connection': 'named only in the old reading register'})
                if not r2:
                    continue
                self.ch[chn] = r2['id']
                self.choices.append(f'the reading register names a source "{chn}" that channels.md does not have; '
                                    'a channel of that name was created so its lines keep their place')
            ext = (r.get('source_id') or f'line {n}').strip()
            old = self.door.conn.execute('SELECT thing_id FROM source WHERE channel_id=? AND external_id=?',
                                         (self.ch[chn], ext)).fetchone()
            if old:
                # the same source listed again in a later run: recorded once, classified by its first valid line
                repeats += 1
                t = old[0]
                if self.door.status_of(t) == mdb.NO_VERDICT and self.valid(r):
                    self.classify(t, n, line, r, sid)
                continue
            src = self.do(f'reading register line {n}', 'record', 'claude', type=DISPOSITION_TYPE.get(chn, 'message'),
                          params={'channel_id': self.ch[chn], 'external_id': ext,
                                  'title': (r.get('subject') or r.get('source_id') or 'no subject')[:200],
                                  'source_date': r.get('date') or None,
                                  'details': {'sender': r.get('sender', ''), 'old_line': n, 'direction': 'incoming'}})
            if not src:
                continue
            if self.valid(r):
                self.classify(src['id'], n, line, r, sid)
            else:
                disp, why = (r.get('disposition') or '').strip(), (r.get('key_or_reason') or '').strip()
                reason = ('not classified before the move' if not disp else
                          f'the old register says "{disp} {why}", and that is not a valid disposition here')
                self.do(src['id'], 'read', 'claude', src['id'], params={'read_state': 'partial', 'reason': reason})
        still = self.door.conn.execute(
            'SELECT count(*) FROM source WHERE verdict IS NULL AND channel_id<>? AND read_state=?',
            (self.ch[OLD_CHANNEL], 'partial')).fetchone()[0]
        self.counts['dispositions_still_open'] = still
        if repeats:
            self.counts['dispositions_repeated'] = repeats
            self.choices.append(f'{repeats} lines of the reading register repeat a source already listed (the same '
                                'thread in a later run); each source is recorded once and takes the first line that '
                                'classifies it')
        if still:
            self.choices.append(f'{still} sources in the reading register had no valid disposition; they stay listed '
                                'as read and not classified, as before, until a run classifies them')

    def valid(self, r):
        disp, why = (r.get('disposition') or '').strip(), (r.get('key_or_reason') or '').strip()
        return (disp == 'ignored' and why) or (disp == 'linked' and why in self.ids)

    def classify(self, t, n, line, r, sid):
        disp, why = (r.get('disposition') or '').strip(), (r.get('key_or_reason') or '').strip()
        self.do(t, 'read', 'claude', t, params={'read_state': 'full'})
        if disp == 'ignored':
            self.do(t, 'verdict', 'claude', t, params={'verdict': 'ignored', 'reason': why})
        else:
            self.do(t, 'link', 'claude', self.ids[why], params={'to_id': t, 'role': 'source'},
                    evidence={'source': sid, 'quote': line, 'position': f'line {n}'})
            self.do(t, 'verdict', 'claude', t, params={'verdict': 'linked'})
        self.counts['dispositions'] += 1

    def jobs(self):
        rows = []
        if os.path.exists(self.path('jobs.md')):
            for line in read(self.path('jobs.md')).split('\n'):
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                if line.startswith('|') and len(cells) >= 3 and cells[0] not in ('id', '') \
                        and not set(cells[0]) <= set('-: '):
                    rows.append((line, cells))
        done = (self.state.get('jobs') or {})
        for line, cells in rows:
            jid, what, sched_text = cells[0], cells[1], cells[2]
            self.counts['jobs_in_files'] += 1
            sched = parse_schedule(sched_text)
            if sched and sched.get('days') == 'WORKDAYS':
                sched['days'] = self.workdays
            if not sched:
                self.problem('job', jid, f'the schedule "{sched_text}" cannot be read; write it in jobs.md as JSON, '
                             'for example {"every": "day", "at": "07:30"}')
                continue
            f = self.path('jobs', jid + '.md')
            instr = read(f) if os.path.exists(f) else what
            res = self.do(jid, 'create', 'user', type='job', evidence=self.owner_ev,
                          params={'title': jid, 'instructions': instr, 'schedule': sched})
            if not res:
                continue
            self.counts['jobs'] += 1
            self.choices.append(f'job {jid}: the schedule "{sched_text}" was read as {json.dumps(sched)}')
            last = (done.get(jid) or {}).get('last_period')
            if last and last in [x['period'] for x in self.door.due_jobs() if x['job_id'] == res['id']]:
                self.do(jid, 'mark_period_done', 'program', res['id'], params={'period': last})

    # ------------------------------------------------------------------------------------------------
    def report(self):
        c = self.door.conn
        after = {
            'items': c.execute("SELECT count(*) FROM followup f JOIN thing t ON t.id=f.thing_id WHERE t.type IN "
                               "('commitment','reply_needed','decision_needed','for_info') AND "
                               "json_extract(f.details,'$.kind') IS NOT 'question'").fetchone()[0],
            'by_status': [list(r) for r in c.execute(
                'SELECT t.type, f.status, count(*) FROM followup f JOIN thing t ON t.id=f.thing_id '
                'GROUP BY 1,2 ORDER BY 1,2')],
            'run': [list(r) for r in c.execute('SELECT status FROM run')],
            'audit_lines': c.execute('SELECT count(*) FROM audit').fetchone()[0],
        }
        rep = {'version': VERSION, 'database': self.db, 'counts': dict(self.counts), 'after': after,
               'problems': self.problems, 'choices': self.choices,
               'ready_to_apply': not self.problems}
        return rep


# ----------------------------------------------------------------------------------------------------
def stamp(tz):
    import zoneinfo
    return datetime.datetime.now(zoneinfo.ZoneInfo(tz)).strftime('%Y%m%d_%H%M')


def lock_held(st, tz):
    """The lock of the files version: held when a holder took it under 10 minutes ago (MANUAL section 4)."""
    import zoneinfo
    lk = st.get('lock') or {}
    if not lk.get('holder') or not lk.get('since'):
        return None
    try:
        since = datetime.datetime.strptime(str(lk['since'])[:16], '%Y-%m-%d %H:%M')
    except ValueError:
        return lk
    now = datetime.datetime.now(zoneinfo.ZoneInfo(tz)).replace(tzinfo=None)
    return lk if (now - since).total_seconds() < 600 else None


def check(a):
    st = json.loads(read(os.path.join(a.followup, 'state.json')))
    tz = (st.get('owner') or {}).get('timezone') or a.timezone or 'UTC'
    base = os.path.join(a.followup, 'db', 'trial_' + stamp(tz))
    out, n = base, 1
    while os.path.exists(out):
        n += 1
        out = f'{base}_{n}'
    os.makedirs(out)
    rep = Migration(a, os.path.join(out, 'marionette.db')).build()
    with open(os.path.join(out, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    return rep, tz


def placeholder_text(rel, where):
    return (f'This {"folder" if not rel.endswith((".tsv", ".md")) else "file"} is no longer used.\n'
            'Marionette keeps its memory in the database (db/marionette.db). Read tools/db_usage.md for how to read '
            'and write it.\n'
            f'What was here before the move is kept, unchanged, in {where}/{rel}.\n'
            'Never write here and never recreate this file.\n')


def make_read_only(path):
    if os.path.isdir(path):
        os.chmod(path, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    else:
        os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def apply(a, rep, tz):
    F = a.followup
    st_path = os.path.join(F, 'state.json')
    st = json.loads(read(st_path))
    lk = lock_held(st, tz)
    if lk:
        raise SystemExit(f'a run holds the lock ({lk.get("holder")} since {lk.get("since")}); wait until it ends')
    final = os.path.join(F, 'db', 'marionette.db')
    if os.path.exists(final):
        raise SystemExit(f'{final} exists already; the move was done before')
    day = stamp(tz)
    where = f'archive/before_db_{day}'
    # 1. the lock, so no run writes the old files while they move
    import zoneinfo
    st['lock'] = {'holder': 'migration',
                  'since': datetime.datetime.now(zoneinfo.ZoneInfo(tz)).strftime('%Y-%m-%d %H:%M')}
    with open(st_path, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    try:
        # 2. the real database, built the same way as the check
        rep2 = Migration(a, final).build()
        if rep2['problems']:
            raise SystemExit('the real build found problems the check did not: ' + json.dumps(rep2['problems'][:5]))
        # 3. the programs, and the old copies of the run tools kept
        tools = os.path.join(F, 'tools')
        os.makedirs(os.path.join(F, where, 'tools'), exist_ok=True)
        for name in DOORS:
            if os.path.exists(os.path.join(tools, name)):
                shutil.move(os.path.join(tools, name), os.path.join(F, where, 'tools', name))
        for name in PROGRAMS + DOORS + ('db_usage.md',):
            src = os.path.join(HERE, 'doors', name) if name in DOORS else os.path.join(HERE, name)
            shutil.copyfile(src, os.path.join(tools, name))
            os.chmod(os.path.join(tools, name), 0o644)
        # 4. the old memory moves into the archive; a read-only placeholder stays at each old path
        moved = []
        for rel in OLD_MEMORY:
            p = os.path.join(F, rel)
            if not os.path.exists(p):
                continue
            dest = os.path.join(F, where, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(p, dest)
            moved.append(rel)
            if rel.endswith(('.tsv', '.md')):
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(placeholder_text(rel, where))
                make_read_only(p)
            else:
                os.makedirs(p)
                with open(os.path.join(p, 'README.md'), 'w', encoding='utf-8') as f:
                    f.write(placeholder_text(rel, where))
                make_read_only(os.path.join(p, 'README.md'))
                make_read_only(p)
        # 5. state.json: watermarks and lock now live in the database
        st = json.loads(read(st_path))
        st['before_db'] = {'watermarks': st.pop('watermarks', None), 'jobs': st.pop('jobs', None), 'moved_to': where}
        st['memory'] = {'kind': 'database', 'file': 'db/marionette.db', 'since': day, 'version': VERSION}
        st.pop('lock', None)
        with open(st_path, 'w', encoding='utf-8') as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        with open(os.path.join(F, 'runs.log'), 'a', encoding='utf-8') as f:
            f.write(f'\n## {day} move to the database (Marionette {VERSION})\n'
                    f'Database: db/marionette.db. Counts: {json.dumps(rep2["counts"])}.\n'
                    f'Old memory files moved, unchanged, to {where}/: {", ".join(moved)}. '
                    'A read-only placeholder stays at each old path.\n')
        return {'applied': True, 'database': final, 'old_files': where, 'moved': moved, 'counts': rep2['counts'],
                'choices': rep2['choices']}
    except BaseException:
        st = json.loads(read(st_path))
        if (st.get('lock') or {}).get('holder') == 'migration':
            st['lock'] = {'holder': None, 'since': None}
            with open(st_path, 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
        raise


def undo(a):
    """Puts the files back as they were before the move. Nothing is deleted: the database, the placeholders and the
    installed programs are moved aside into archive/undone_<time>/. What was recorded in the database after the
    move is not copied back into the files; the report says how much that was."""
    F = a.followup
    st_path = os.path.join(F, 'state.json')
    st = json.loads(read(st_path))
    b = st.get('before_db')
    if not b or not b.get('moved_to'):
        return {'refused': 'state.json does not record a move to the database; nothing to undo'}
    tz = (st.get('owner') or {}).get('timezone') or a.timezone or 'UTC'
    where = b['moved_to']
    aside = os.path.join(F, 'archive', 'undone_' + stamp(tz))
    os.makedirs(aside)
    db = os.path.join(F, 'db', 'marionette.db')
    after = 0
    if os.path.exists(db):
        import sqlite3
        c = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
        moved_at = c.execute("SELECT min(at) FROM audit WHERE run_id IN (SELECT thing_id FROM run WHERE "
                             "trigger_kind='migration')").fetchone()[0] or ''
        after = c.execute("SELECT count(*) FROM audit WHERE (run_id IS NULL OR run_id NOT IN (SELECT thing_id FROM "
                          "run WHERE trigger_kind='migration')) AND at>?", (moved_at,)).fetchone()[0]
        c.close()
        os.makedirs(os.path.join(aside, 'db'))
        shutil.move(db, os.path.join(aside, 'db', 'marionette.db'))
    for rel in OLD_MEMORY:
        src = os.path.join(F, where, rel)
        if not os.path.exists(src):
            continue
        cur = os.path.join(F, rel)
        if os.path.exists(cur):
            for dp, dn, fn in os.walk(cur):
                os.chmod(dp, 0o755)
                for n in fn:
                    os.chmod(os.path.join(dp, n), 0o644)
            os.chmod(cur, 0o755 if os.path.isdir(cur) else 0o644)
            os.makedirs(os.path.dirname(os.path.join(aside, 'placeholders', rel)), exist_ok=True)
            shutil.move(cur, os.path.join(aside, 'placeholders', rel))
        shutil.move(src, cur)
    tools = os.path.join(F, 'tools')
    os.makedirs(os.path.join(aside, 'tools'))
    for name in PROGRAMS + DOORS + ('db_usage.md',):
        if os.path.exists(os.path.join(tools, name)):
            shutil.move(os.path.join(tools, name), os.path.join(aside, 'tools', name))
    for name in DOORS:
        old = os.path.join(F, where, 'tools', name)
        if os.path.exists(old):
            shutil.move(old, os.path.join(tools, name))
    if b.get('watermarks') is not None:
        st['watermarks'] = b['watermarks']
    if b.get('jobs') is not None:
        st['jobs'] = b['jobs']
    st['lock'] = {'holder': None, 'since': None}
    st.pop('memory', None)
    st['undone_db'] = {'at': stamp(tz), 'kept_in': os.path.relpath(aside, F), 'database_changes_after_move': after}
    st.pop('before_db', None)
    with open(st_path, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    with open(os.path.join(F, 'runs.log'), 'a', encoding='utf-8') as f:
        f.write(f'\n## {stamp(tz)} move to the database undone\nThe files are back. The database and the programs were '
                f'moved aside into {os.path.relpath(aside, F)}/. Changes recorded in the database after the move and '
                f'not in the files: {after}.\n')
    return {'undone': True, 'kept_in': os.path.relpath(aside, F), 'database_changes_after_move': after}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Move a Marionette installation from files to the database')
    ap.add_argument('--followup', required=True, help='the followup folder')
    ap.add_argument('--approval', help="the owner's own words approving the move, verbatim")
    ap.add_argument('--session-file', help='the session file those words were said in')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--undo', action='store_true', help='put the files back as they were before the move')
    ap.add_argument('--map')
    ap.add_argument('--user-name')
    ap.add_argument('--user-email')
    ap.add_argument('--timezone')
    a = ap.parse_args(argv)
    a.followup = os.path.abspath(a.followup)
    if a.undo:
        out = undo(a)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 2 if 'refused' in out else 0
    if not a.approval or not a.session_file:
        ap.error('--approval and --session-file are needed to check or apply the move')
    if os.path.exists(os.path.join(a.followup, 'tools', 'db_usage.md')) and \
            os.path.exists(os.path.join(a.followup, 'db', 'marionette.db')):
        print(json.dumps({'refused': 'this installation already keeps its memory in the database'}))
        return 2
    rep, tz = check(a)
    summary = {'check': rep['database'], 'counts': rep['counts'], 'problems': rep['problems'],
               'choices': rep['choices'], 'ready_to_apply': rep['ready_to_apply']}
    if not a.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0 if rep['ready_to_apply'] else 1
    if not rep['ready_to_apply']:
        summary['refused'] = 'not applied: the check found problems; fix them and run the check again'
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 1
    print(json.dumps(apply(a, rep, tz), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
