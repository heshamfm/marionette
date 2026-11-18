#!/usr/bin/env python3
"""Marionette by Hesham Elmahdy (github.com/heshamfm): the run-time layer, version 1.5.

What the scheduled runs and the sessions use in an installation that keeps its memory in the database,
instead of editing the files (index.tsv, items/, drafts.tsv, questions.md, reminders/, data/disposition.tsv,
state.json watermarks and lock).
Reading commands only SELECT. Every write goes through the door program mdb.py (Door.do), which checks
who may do what, refuses with a reason, and writes the audit trail. Nothing is ever deleted.

Output: the brief, the status page and the end-of-run check print text for the reader, in the language the
database was created with (meta "language": en or ar); every other command prints JSON. A refusal prints {"refused": "..."} and exits with code 2.

Usage (DB defaults to $MARIONETTE_DB, else ../db/marionette.db beside this program's folder):
 reading
  mrun.py brief [--full-questions]              what a run needs to know, compact (replaces tools/brief.py)
  mrun.py late                                  every late thing with its reason
  mrun.py item ID_OR_OLD_KEY                    one thing, its parties, its evidence (story) and its history
  mrun.py find TEXT                             things and parties whose title, details or handles hold TEXT
  mrun.py source CHANNEL EXTERNAL_ID            is this message, event, meeting or record already recorded?
  mrun.py sources --since "YYYY-MM-DD HH:MM" [--verdict none|linked|informed|ignored]   for the auditor
  mrun.py status --out FILE --live-check TEXT [--notes FILE]   the status page (replaces tools/build_status.py)
  mrun.py gate --run RUN_ID --channels-file FILE                the end-of-run check (replaces tools/run_gate.py)
  mrun.py export --out view/Marionette_Register.xlsx            the register spreadsheet, one way (needs openpyxl)
 writing (actor claude unless --actor user, which needs --session and --quote: his words in a session)
  mrun.py run-start [--kind schedule|session|jobs] [--title T]  takes the lock: one live run at a time
  mrun.py run-end --run ID [--failed] [--summary JSON]          releases it
  mrun.py skip --run ID --channel NAME --code CODE --text TEXT  an enabled channel this run did not read
  mrun.py watermark --run ID --channel NAME --at "YYYY-MM-DD HH:MM"
  mrun.py record --run ID --channel NAME --type message|calendar_event|meeting|external_record|published_content
                 --external-id X --title T [--date D] [--permalink URL] [--details JSON]
                 [--read full|partial|failed] [--reason TEXT]
  mrun.py verdict --run ID --source ID --verdict linked|informed|ignored [--reason TEXT]
  mrun.py party --run ID --name NAME [--email ADDRESS] [--kind person|org] --source ID --quote Q
  mrun.py new-item --run ID --type commitment|reply_needed|decision_needed|for_info --title T --holder WHO
                 [--promised-by WHO] [--requested-by WHO] [--due D] [--next-check D] [--details JSON]
                 --source ID --quote Q [--inferred a,b]
  mrun.py ask --run ID --question TEXT [--about ID] --source ID --quote Q [--options JSON] [--recommend TEXT]
  mrun.py story --run ID --item ID --source ID --quote Q [--position P]
  mrun.py act --run ID --item ID --action ACTION [--params JSON] [--source ID --quote Q] [--actor claude|user|program]
  mrun.py draft --run ID --item ID --channel NAME --kind reply|forward|new [--replies-to X] --recipients JSON
                [--cc JSON] [--subject S] --text-file FILE [--mail-draft-id X]
  mrun.py remind --run ID --text T --due D --session ID --quote Q    a reminder the user asked for
 WHO is "me", a party number, or an email address of a recorded party.
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mdb  # noqa: E402

ALIVE = ('open', 'deferred', 'new')
ITEM_TYPES = ('commitment', 'reply_needed', 'decision_needed', 'for_info')
LOCK_MINUTES = 30   # a run that wrote nothing for 30 minutes is taken as stopped

# Words the reader sees. Keys are English; each language gives its text.
TEXT = {
 'en': {
  'you': 'you', 'open': 'open', 'waiting': 'waiting on others', 'not_needed': 'closed, no action needed',
  'done': 'done', 'deferred': 'postponed', 'new': 'new', 'seen': 'seen', 'cancelled': 'cancelled',
  'ready': 'waiting for you to send', 'scheduled': 'scheduled', 'shown': 'shown',
  'my_commitment': 'my commitment', 'their_commitment': 'their commitment to me', 'reply_needed': 'reply needed from me',
  'decision_needed': 'decision needed from me', 'for_info': 'for information only', 'reminder': 'reminder',
  'draft': 'draft', 'deferred_check': 'deferred check', 'sep': '; ',
  'status_title': '# Marionette status, {now} ({tz})', 'live_check': 'Live check before building: {x}',
  'h_you': '## Waiting for you', 'draft_since': '- Draft waiting for you to send since {d}: {t}',
  'question_since': '- Question since {d}: {t}', 'reminder_due': '- Reminder you asked for{w}: {t}',
  'due_on': ', due {d}', 'reminder_when': ' due {d}', 'reminder_nodate': ' with no date',
  'h_late': '## Late', 'h_waiting': '## Waiting on others ({n})', 'h_jobs': '## Produced by jobs today',
  'next_job': '- Next job due: {x}', 'nothing_now': 'nothing now',
  'sheet': 'Items', 'cols': ['Number', 'Old key', 'Status', 'Type', 'Due', 'Next check', 'Late', 'Counterparty',
                            'Title', 'Last event'],
  'tool_absent': 'the tool is absent', 'page_failed': 'the page did not open', 'permission_refused': 'permission was refused',
  'not_due': 'not due yet', 'partly_read': 'read in part; what remains is named',
  'no_channel': 'Channel {c} is enabled in channels.md and has no record in the database.',
  'skipped': 'Channel {c} was not read: {why}. {t}', 'left': 'Channel {c} was left without an accepted reason. Last read: {w}.',
  'never': 'never read', 'gate_head': 'End-of-run check ({s}): {r} of {n} enabled channels read.',
  'violation': 'VIOLATION: ', 'note': 'Note: ', 'unclassified': 'Read and not classified ({n}):', 'rest': '- and {n} more.',
  'ignored': 'Ignored in this run ({n}):', 'more': ', and {n} more', 'informed': 'For information, from parties we deal with ({n}):',
  'undated': 'Open items with no due date and no next check ({n}). Oldest:',
  'clean': 'Every channel was read, everything read is classified, nothing is missing.',
  'q_title': 'Question: ', 'd_title': 'Draft: ',   'you_tag': '- [you] ', 'jobs_tag': '- [jobs] ',
 },
 'ar': {
  'you': 'أنت', 'open': 'مفتوح', 'waiting': 'بانتظار رد الآخرين', 'not_needed': 'أُغلق دون إجراء',
  'done': 'منجز', 'deferred': 'مؤجل', 'new': 'جديد', 'seen': 'اطُّلع عليه', 'cancelled': 'أُلغي',
  'ready': 'تنتظر إرسالك', 'scheduled': 'مجدول', 'shown': 'عُرض',
  'my_commitment': 'التزام قطعته أنا', 'their_commitment': 'التزام قطعه غيري', 'reply_needed': 'رد مطلوب مني',
  'decision_needed': 'قرار مطلوب مني', 'for_info': 'للعلم فقط', 'reminder': 'تذكير',
  'draft': 'مسودة', 'deferred_check': 'فحص مؤجل', 'sep': '؛ ',
  'status_title': '# حالة ماريونيت، {now} ({tz})', 'live_check': 'الفحص الحي قبل البناء: {x}',
  'h_you': '## ينتظرك أنت', 'draft_since': '- مسودة تنتظر إرسالك منذ {d}: {t}',
  'question_since': '- سؤال منذ {d}: {t}', 'reminder_due': '- تذكير طلبته{w}: {t}',
  'due_on': '، الموعد {d}', 'reminder_when': ' موعده {d}', 'reminder_nodate': ' بلا موعد',
  'h_late': '## متأخر عن موعده', 'h_waiting': '## بانتظار الآخرين ({n})', 'h_jobs': '## ما أنتجته الأعمال اليوم',
  'next_job': '- العمل الدوري المستحق التالي: {x}', 'nothing_now': 'لا شيء الآن',
  'sheet': 'البنود', 'cols': ['الرقم', 'المفتاح القديم', 'الحالة', 'النوع', 'الموعد', 'الفحص التالي', 'متأخر',
                             'الطرف المقابل', 'العنوان', 'آخر حدث'],
  'tool_absent': 'الأداة غائبة', 'page_failed': 'الصفحة لم تفتح', 'permission_refused': 'الصلاحية رُفضت',
  'not_due': 'لم يحن موعد قراءتها', 'partly_read': 'قُرئت جزئيًا وبقي منها ما يُذكر',
  'no_channel': 'القناة {c} مفعّلة في ملف القنوات ولا سجل لها في القاعدة.',
  'skipped': 'لم تُقرأ قناة {c}: {why}. {t}', 'left': 'تُركت قناة {c} دون سبب مقبول. آخر قراءة لها: {w}.',
  'never': 'لم تُقرأ قط', 'gate_head': 'فحص نهاية التشغيل ({s}): قُرئت {r} قناة من {n} مفعّلة.',
  'violation': 'مخالفة: ', 'note': 'ملاحظة: ', 'unclassified': 'قرأتُه ولم أصنّفه ({n}):', 'rest': '- والباقي {n}.',
  'ignored': 'تجاهلتُ في هذا التشغيل ({n}):', 'more': '، و{n} غيرها', 'informed': 'للعلم من جهات نتعامل معها ({n}):',
  'undated': 'بنود مفتوحة بلا موعد ولا تاريخ فحص قادم ({n}). الأقدم:',
  'clean': 'كل القنوات قُرئت، وكل ما قُرئ مصنّف، ولا شيء ناقص.',
  'q_title': 'سؤال: ', 'd_title': 'مسودة: ',   'you_tag': '- [ينتظرك] ', 'jobs_tag': '- [الأعمال] ',
 },
}


def default_db():
    return os.environ.get('MARIONETTE_DB') or os.path.join(os.path.dirname(HERE), 'db', 'marionette.db')


class Run:
    def __init__(self, db):
        if not os.path.exists(db):
            raise mdb.Refused(f'{db} does not exist')
        self.door = mdb.Door(db)
        self.c = self.door.conn
        self.me = int(self.door.meta('user_party_id'))
        self.T = TEXT.get(self.door.meta('language', 'en'), TEXT['en'])

    def t(self, key, **kw):
        return self.T[key].format(**kw) if kw else self.T[key]

    # ------------------------------------------------------------ helpers
    def q(self, sql, a=()):
        return self.c.execute(sql, a).fetchall()

    def one(self, sql, a=()):
        return self.c.execute(sql, a).fetchone()

    def now(self):
        return self.door.now()

    def channel_id(self, name):
        r = self.one("SELECT t.id FROM channel ch JOIN thing t ON t.id=ch.thing_id WHERE t.title=?", (name,))
        if not r:
            raise mdb.Refused(f'no channel named "{name}"')
        return r[0]

    def resolve_item(self, x):
        x = str(x)
        if x.isdigit():
            return int(x)
        r = self.one("SELECT thing_id FROM followup WHERE json_extract(details,'$.old_key')=?", (x,))
        if not r:
            raise mdb.Refused(f'no follow-up thing with old key "{x}"')
        return r[0]

    def who(self, w):
        if w in (None, ''):
            return None
        w = str(w)
        if w == 'me':
            return self.me
        if w.isdigit():
            self.door.party(int(w))
            return int(w)
        r = self.one("SELECT party_id FROM party_handle WHERE kind='email' AND lower(value)=lower(?)", (w,))
        if not r:
            raise mdb.Refused(f'no party with the email "{w}"; record it first with: mrun.py party')
        return r[0]

    def name(self, pid):
        if pid is None:
            return ''
        if pid == self.me:
            return self.t('you')
        t = self.one('SELECT title FROM thing WHERE id=?', (pid,))
        e = self.one("SELECT value FROM party_handle WHERE party_id=? AND kind='email' ORDER BY id LIMIT 1", (pid,))
        title = t[0] if t else str(pid)
        return title + (f' {e[0]}' if e and e[0].lower() not in title.lower() else '')

    def ar_status(self, r):
        s = r['status']
        if s == 'open':
            return self.t('open') if r['holder_id'] == self.me else self.t('waiting')
        if s == 'done':
            return self.t('not_needed') if r['close_reason'] == 'not_needed' else self.t('done')
        return self.T.get(s, s) if s in ('deferred', 'new', 'seen', 'cancelled', 'ready', 'scheduled', 'shown') else s

    def ar_type(self, tid, ty):
        if ty == 'commitment':
            r = self.one("SELECT to_id FROM link WHERE from_id=? AND role='promised_by'", (tid,))
            return self.t('my_commitment') if r and r[0] == self.me else self.t('their_commitment')
        return self.T.get(ty, ty) if ty in ('reply_needed', 'decision_needed', 'for_info', 'reminder', 'draft',
                                            'deferred_check') else ty

    def parties(self, tid):
        return [(r['role'], r['to_id']) for r in self.q(
            "SELECT l.role, l.to_id FROM link l JOIN thing t ON t.id=l.to_id WHERE l.from_id=? AND t.type='party'",
            (tid,))]

    def counterparty(self, tid, holder):
        ps = [p for _, p in self.parties(tid) if p != self.me]
        if holder != self.me and holder not in ps:
            ps.insert(0, holder)
        return self.t('sep').join(dict.fromkeys(n for n in (self.name(p).strip() for p in ps) if n)) or '-'

    def last_event(self, tid):
        a = self.one("SELECT at, action, field, new_value, note FROM audit WHERE thing_id=? AND action NOT IN "
                     "('show') ORDER BY id DESC LIMIT 1", (tid,))
        e = self.one('SELECT quote FROM evidence WHERE thing_id=? ORDER BY id DESC LIMIT 1', (tid,))
        q = (e[0] if e else '').replace('\n', ' ').replace('\t', ' | ')
        q = re.sub(r'^- ', '', q)
        return f"{a['at'][:16]} {q[:160]}" if a else q[:160]

    def old_key(self, details):
        return json.loads(details).get('old_key')

    def items(self, alive=True):
        sql = ("SELECT t.id,t.type,t.title,t.created_at,f.status,f.holder_id,f.due,f.next_check,f.close_reason,"
               "f.details FROM followup f JOIN thing t ON t.id=f.thing_id WHERE t.type IN (?,?,?,?)")
        if alive:
            sql += " AND f.status IN ('open','deferred','new')"
        return self.q(sql + ' ORDER BY t.id', ITEM_TYPES)

    def late_map(self):
        """Late items with their reason. Questions to the user are not items: they are shown as questions."""
        out = {}
        for x in self.door.late():
            d = json.loads(self.one('SELECT details FROM followup WHERE thing_id=?', (x['id'],))[0])
            if not (x['type'] == 'decision_needed' and (d.get('old_question') or d.get('kind') == 'question')):
                out[x['id']] = x['why']
        return out

    def is_question(self, r):
        d = json.loads(r['details'])
        return r['type'] == 'decision_needed' and (d.get('old_question') or d.get('kind') == 'question')

    # ------------------------------------------------------------ reading
    def brief(self, full_q=False):
        L = []
        now = self.now()[:16]
        runs = self.q("SELECT t.id, t.title, r.started FROM run r JOIN thing t ON t.id=r.thing_id "
                      "WHERE r.status='running' ORDER BY t.id")
        lock = '; '.join(f"run {r['id']} since {r['started'][:16]} ({r['title']})" for r in runs) or 'free'
        L.append(f'# Marionette brief {now} | lock: {lock}')
        wm = self.q("SELECT t.title, ch.watermark, ch.status FROM channel ch JOIN thing t ON t.id=ch.thing_id "
                    "ORDER BY t.id")
        L.append('watermarks: ' + '; '.join(f"{r['title']}={r['watermark']}" + ('' if r['status'] == 'connected'
                                            else f" ({r['status']})") for r in wm))
        jobs = self.q("SELECT t.title, j.last_period, j.status FROM job j JOIN thing t ON t.id=j.thing_id ORDER BY t.id")
        L.append('jobs last_period: ' + '; '.join(f"{r['title']}={r['last_period']}" for r in jobs
                                                  if r['status'] == 'enabled'))
        due = self.door.due_jobs()
        L.append('jobs DUE, this run does them now: ' + ('; '.join(
            f"{x['title']} period {x['period']} (due {x['due_at']})" + (' LATE' if x['late'] else '')
            for x in due) or 'none'))
        late = self.late_map()
        rows = [r for r in self.items() if not self.is_question(r)]
        today = now[:10]

        def sk(r):
            return (0 if r['id'] in late else 1, r['due'] or '9999', r['id'])
        rows.sort(key=sk)
        allr = self.q("SELECT f.status, f.close_reason, f.holder_id FROM followup f JOIN thing t ON t.id=f.thing_id "
                      "WHERE t.type IN (?,?,?,?)", ITEM_TYPES)
        cnt = {}
        for r in allr:
            k = self.ar_status(r)
            cnt[k] = cnt.get(k, 0) + 1
        L.append('')
        L.append(f'## Open items ({len(rows)}) | all items {len(allr)} | by status: ' +
                 ', '.join(f'{k}={v}' for k, v in cnt.items()))
        for r in rows:
            lt = ' LATE' + ('' if r['due'] else ' (no deadline, unaddressed)') if r['id'] in late else ''
            nc = r['next_check'] or ''
            ncs = (f' | next_check {nc}' + (' CHECK DUE' if nc[:10] <= today else '')) if nc else \
                ('' if r['due'] else ' | NO DATE')
            ok = self.old_key(r['details'])
            L.append(f"- {r['id']}{' (' + ok + ')' if ok else ''} | {self.ar_status(r)} | "
                     f"{self.ar_type(r['id'], r['type'])} | due {r['due'] or '-'}{lt}{ncs} | "
                     f"{self.counterparty(r['id'], r['holder_id'])} | {r['title']} | last {self.last_event(r['id'])}")
        L.append(f'count check: open {len(rows)} listed')
        drafts = self.q("SELECT t.id, t.title, t.created_at, f.details FROM followup f JOIN thing t ON t.id=f.thing_id "
                        "WHERE t.type='draft' AND f.status='ready' ORDER BY t.id")
        L.append('')
        L.append(f'## Drafts waiting ({len(drafts)})')
        for d in drafts:
            dd = json.loads(d['details'])
            L.append(f"- {d['id']} | mail draft {dd.get('mail_draft_id') or dd.get('old_draft_id') or '-'} | "
                     f"serves {dd.get('serves') or '-'} | created {(dd.get('created_before_move') or d['created_at'])[:16]}"
                     f" | {d['title']}")
        qs = [r for r in self.items() if self.is_question(r)]
        L.append('')
        L.append(f'## Open questions ({len(qs)})')
        for r in qs:
            d = json.loads(r['details'])
            L.append(f"- {r['id']} | asked {d.get('asked_at') or r['created_at'][:16]} | {r['title']}" +
                     (f" | {d.get('question')}" if full_q else ''))
        rem = self.q("SELECT t.id, t.title, f.due, f.status FROM followup f JOIN thing t ON t.id=f.thing_id "
                     "WHERE t.type='reminder' AND f.status='scheduled' ORDER BY f.due")
        L.append('')
        L.append(f'## Reminders not yet delivered ({len(rem)})')
        for r in rem:
            L.append(f"- {r['id']} | due {r['due']} | {r['title']}" +
                     (' | DUE NOW' if r['due'] and r['due'][:16] <= now else ''))
        un = self.q("SELECT t.id, t.title, s.read_state, s.read_fail_reason FROM source s JOIN thing t ON "
                    "t.id=s.thing_id WHERE s.verdict IS NULL AND s.read_state<>'failed' ORDER BY t.id")
        L.append('')
        L.append(f'## Read and not classified ({len(un)})')
        for r in un[:60]:
            L.append(f"- {r['id']} | {r['read_state']} | {r['title']}")
        if len(un) > 60:
            L.append(f'- and {len(un) - 60} more')
        return '\n'.join(L)

    def late(self):
        late = self.late_map()
        return [x for x in self.door.late() if x['id'] in late]

    def item(self, x):
        tid = self.resolve_item(x)
        out = self.door.show(tid)
        out['story'] = [{'quote': r['quote'], 'source': r['source_id'], 'position': r['position'],
                         'inferred': bool(r['inferred'])} for r in self.q(
            'SELECT * FROM evidence WHERE thing_id=? ORDER BY id', (tid,))]
        out['history'] = [f"{r['at'][:16]} {r['actor']} {r['action']} {r['field'] or ''} "
                          f"{(r['new_value'] or '')[:120]} {r['note'] or ''}".strip()
                          for r in self.q('SELECT * FROM audit WHERE thing_id=? ORDER BY id', (tid,))]
        out['late'] = self.late_map().get(tid)
        return out

    def find(self, text):
        like = f'%{text.lower()}%'
        things = [dict(r) for r in self.q(
            "SELECT t.id, t.type, t.title FROM thing t LEFT JOIN followup f ON f.thing_id=t.id "
            "LEFT JOIN source s ON s.thing_id=t.id WHERE lower(t.title) LIKE ? OR lower(f.details) LIKE ? "
            "OR lower(s.details) LIKE ? OR lower(s.external_id) LIKE ? ORDER BY t.id DESC LIMIT 80",
            (like, like, like, like))]
        parties = [dict(r) for r in self.q(
            "SELECT DISTINCT p.party_id AS id, h.kind, h.value FROM party_handle p0 JOIN party_handle h "
            "ON h.party_id=p0.party_id JOIN party_handle p ON p.id=h.id WHERE lower(p0.value) LIKE ? LIMIT 40",
            (like,))]
        return {'things': things, 'party_handles': parties}

    def sources(self, since, verdict=None):
        """Sources recorded or decided since a time, for the auditor: title, channel, read state, verdict, reason."""
        sql = ("SELECT t.id, t.title, c.title AS channel, s.external_id, s.read_state, s.verdict, s.verdict_reason, "
               "(SELECT max(at) FROM audit a WHERE a.thing_id=t.id) AS last FROM source s JOIN thing t ON "
               "t.id=s.thing_id JOIN thing c ON c.id=s.channel_id WHERE (SELECT max(at) FROM audit a WHERE "
               "a.thing_id=t.id) >= ?")
        a = [since]
        if verdict == 'none':
            sql += ' AND s.verdict IS NULL'
        elif verdict:
            sql += ' AND s.verdict=?'
            a.append(verdict)
        return [dict(r) for r in self.q(sql + ' ORDER BY t.id', a)]

    def source(self, channel, ext):
        r = self.one('SELECT s.thing_id, s.read_state, s.verdict, s.verdict_reason FROM source s WHERE '
                     's.channel_id=? AND s.external_id=?', (self.channel_id(channel), str(ext)))
        return dict(r) if r else {'recorded': False}

    # ------------------------------------------------------------ status page
    def status(self, out, live_check, notes=None):
        now = self.now()[:16]
        late = self.late_map()
        rows = [r for r in self.items() if not self.is_question(r)]
        L = [self.t('status_title', now=now, tz=self.door.meta('timezone', 'UTC')), '',
             self.t('live_check', x=live_check), '']
        L.append(self.t('h_you'))
        drafts = self.q("SELECT t.id, t.title, t.created_at, f.details FROM followup f JOIN thing t ON t.id=f.thing_id "
                        "WHERE t.type='draft' AND f.status='ready' ORDER BY t.created_at")
        for d in drafts:
            since = json.loads(d['details']).get('created_before_move') or d['created_at']
            L.append(self.t('draft_since', d=since[:10], t=d['title']))
        for r in [r for r in self.items() if self.is_question(r)]:
            d = json.loads(r['details'])
            L.append(self.t('question_since', d=(d.get('asked_at') or r['created_at'])[:10], t=d.get('question') or r['title']))
        for r in self.q("SELECT t.id, t.title, f.due FROM followup f JOIN thing t ON t.id=f.thing_id "
                        "WHERE t.type='reminder' AND f.status='scheduled' AND (f.due IS NULL OR f.due<=?) "
                        "ORDER BY f.due", (now,)):
            w = self.t('reminder_when', d=r['due']) if r['due'] else self.t('reminder_nodate')
            L.append(self.t('reminder_due', w=w, t=r['title']))
        if notes and os.path.exists(notes):
            for line in open(notes, encoding='utf-8').read().splitlines():
                for tag in (TEXT['en']['you_tag'], TEXT['ar']['you_tag']):
                    if line.startswith(tag):
                        L.append('- ' + line[len(tag):])
        mine = [r for r in rows if r['status'] in ('open', 'new') and r['holder_id'] == self.me and r['id'] not in late]
        for r in mine:
            L.append(f"- {r['title']} ({self.ar_type(r['id'], r['type'])}"
                     f"{self.t('due_on', d=r['due']) if r['due'] else ''})")
        L.append('')
        L.append(self.t('h_late'))
        for r in rows:
            if r['id'] in late:
                L.append(f"- {r['title']}: {late[r['id']]} ({self.ar_type(r['id'], r['type'])}{self.t('sep')}"
                         f"{self.counterparty(r['id'], r['holder_id'])})")
        L.append('')
        waiting = [r for r in rows if r['holder_id'] != self.me and r['id'] not in late]
        L.append(self.t('h_waiting', n=len(waiting)))
        for r in waiting:
            L.append(f"- {r['title']} ({self.counterparty(r['id'], r['holder_id'])}"
                     f"{self.t('due_on', d=r['due']) if r['due'] else ''})")
        L.append('')
        L.append(self.t('h_jobs'))
        for r in self.q("SELECT t.title, a.at, a.note FROM audit a JOIN thing t ON t.id=a.thing_id WHERE "
                        "t.type='job' AND a.action='execute' AND a.at>=? ORDER BY a.id", (now[:10],)):
            L.append(f"- {r['title']} {r['at'][11:16]}: {r['note'] or ''}")
        if notes and os.path.exists(notes):
            for line in open(notes, encoding='utf-8').read().splitlines():
                if line.startswith(TEXT['en']['jobs_tag']) or line.startswith(TEXT['ar']['jobs_tag']):
                    L.append(line)
        due = self.door.due_jobs()
        L.append(self.t('next_job', x=self.t('sep').join(f"{x['title']} {x['period']}" for x in due) or self.t('nothing_now')))
        tmp = out + '.tmp'
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(L) + '\n')
        os.replace(tmp, out)
        return {'written': out, 'waiting_for_you': len(drafts) + len(mine), 'late': len(late), 'waiting_others': len(waiting)}

    # ------------------------------------------------------------ the register spreadsheet
    def export(self, out):
        """One-way copy of every follow-up item into an Excel file, for viewing only."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = self.t('sheet')
        ws.sheet_view.rightToLeft = self.door.meta('language', 'en') == 'ar'
        ws.append(self.T['cols'])
        late = self.late_map()
        for r in self.items(alive=False):
            ws.append([r['id'], self.old_key(r['details']) or '', self.ar_status(r), self.ar_type(r['id'], r['type']),
                       r['due'] or '', r['next_check'] or '', late.get(r['id'], ''),
                       self.counterparty(r['id'], r['holder_id']), r['title'], self.last_event(r['id'])])
        tmp = out + '.tmp.xlsx'
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        wb.save(tmp)
        os.replace(tmp, out)
        return {'written': out, 'rows': ws.max_row - 1}

    # ------------------------------------------------------------ end-of-run check
    VALID = ('tool_absent', 'page_failed', 'permission_refused', 'not_due', 'partly_read')

    def gate(self, run, channels_file):
        r = self.one('SELECT r.started, r.summary, r.status FROM run r WHERE r.thing_id=?', (run,))
        if not r:
            raise mdb.Refused(f'no run {run}')
        txt = open(channels_file, encoding='utf-8').read()
        enabled = [m.group(1) for m in re.finditer(r'(?m)^## (\S+)\s*\nstatus: *(\S+)', txt)
                   if m.group(2).lower().startswith('enabled')]
        skips = {s['channel']: s for s in json.loads(r['summary']).get('skips', [])}
        bad, notes, read = [], [], 0
        for ch in enabled:
            try:
                cid = self.channel_id(ch)
            except mdb.Refused:
                bad.append(self.t('no_channel', c=ch))
                continue
            moved = self.one("SELECT 1 FROM audit WHERE thing_id=? AND run_id=? AND field='channel.watermark'",
                             (cid, run))
            if moved:
                read += 1
                continue
            s = skips.get(ch)
            if s:
                notes.append(self.t('skipped', c=ch, why=self.T.get(s['code'], s['code']), t=s['text']))
            else:
                w = self.one('SELECT watermark FROM channel WHERE thing_id=?', (cid,))[0]
                bad.append(self.t('left', c=ch, w=w or self.t('never')))
        un = self.q("SELECT t.title, s.read_state FROM source s JOIN thing t ON t.id=s.thing_id "
                    "WHERE s.verdict IS NULL AND s.read_fail_reason IS NULL ORDER BY t.id")
        ign, inf = {}, []
        for x in self.q("SELECT t.title, s.verdict, s.verdict_reason FROM source s JOIN thing t ON t.id=s.thing_id "
                        "WHERE s.run_id=? AND s.verdict IN ('ignored','informed') ORDER BY t.id", (run,)):
            if x['verdict'] == 'ignored':
                code = (x['verdict_reason'] or '').split(':', 1)[0].strip()
                ign.setdefault(code, []).append(x['title'])
            else:
                inf.append(x['title'])
        undated = [x for x in self.items() if not x['due'] and not x['next_check'] and x['status'] in ALIVE
                   and not self.is_question(x)]
        start = r['started'][:16]
        print(self.t('gate_head', s=start, r=read, n=len(enabled)))
        for line in bad:
            print(self.t('violation') + line)
        for line in notes:
            print(self.t('note') + line)
        if un:
            print(self.t('unclassified', n=len(un)))
            for x in un[:40]:
                print(f"- {x['title']}")
            if len(un) > 40:
                print(self.t('rest', n=len(un) - 40))
        if ign:
            print(self.t('ignored', n=sum(len(v) for v in ign.values())))
            for code, v in ign.items():
                more = self.t('more', n=len(v) - 15) if len(v) > 15 else ''
                print(f'- {code} ({len(v)}): ' + self.t('sep').join(v[:15]) + more)
        if inf:
            print(self.t('informed', n=len(inf)))
            for x in inf:
                print('- ' + x)
        if undated:
            print(self.t('undated', n=len(undated)))
            for x in undated[:10]:
                print(f"- {x['title']}")
        if not (bad or notes or un or undated):
            print(self.t('clean'))
        return 1 if (bad or un) else 0

    # ------------------------------------------------------------ writing
    def do(self, action, actor='claude', target=None, type=None, params=None, evidence=None, run=None):
        return self.door.do(action, actor, target, type, params, evidence, run)

    def ev(self, source, quote, position=None):
        if source is None or not quote:
            return None
        e = {'source': int(source), 'quote': quote}
        if position:
            e['position'] = position
        return e

    def run_start(self, kind='schedule', title=None):
        for r in self.q("SELECT t.id, r.started FROM run r JOIN thing t ON t.id=r.thing_id WHERE r.status='running'"):
            last = self.one('SELECT max(at) FROM audit WHERE run_id=? OR thing_id=?', (r['id'], r['id']))[0] or r['started']
            age = (mdb.Door.as_time(self.now()) - mdb.Door.as_time(last)).total_seconds() / 60
            if age < LOCK_MINUTES:
                raise mdb.Refused(f'locked: run {r["id"]} started {r["started"][:16]} wrote {int(age)} minutes ago; '
                                  'wait 2 minutes and try again, up to 3 times, then stop')
            self.do('close', 'program', r['id'], params={'failed': True,
                                                         'summary': {'closed_as_stale_by': 'run-start'}})
        res = self.do('start', 'program', type='run', params={'title': title or f'{kind} {self.now()[:16]}',
                                                               'trigger_kind': kind})
        return {'run': res['id'], 'started': self.now()[:16]}

    def run_end(self, run, failed=False, summary=None):
        p = {'failed': bool(failed)}
        if summary:
            p['summary'] = summary
        return self.do('close', 'program', run, params=p)

    def skip(self, run, channel, code, text):
        self.channel_id(channel)
        return self.do('note_skip', 'claude', run, params={'channel': channel, 'code': code, 'text': text})

    def watermark(self, run, channel, at):
        if not re.match(r'^\d{4}-\d\d-\d\d \d\d:\d\d', at or ''):
            raise mdb.Refused('a watermark is "YYYY-MM-DD HH:MM" in the user zone')
        return self.do('update_watermark', 'claude', self.channel_id(channel), params={'watermark': at[:16]}, run=run)

    def record(self, run, channel, type, external_id, title, date=None, permalink=None, details=None,
               read=None, reason=None):
        cid = self.channel_id(channel)
        old = self.one('SELECT thing_id FROM source WHERE channel_id=? AND external_id=?', (cid, str(external_id)))
        if old:
            return {'id': old[0], 'already': True, **self.source(channel, external_id)}
        res = self.do('record', 'claude', type=type, run=run, params={
            'channel_id': cid, 'external_id': str(external_id), 'title': title, 'source_date': date,
            'permalink': permalink, 'details': details or {}})
        if read:
            p = {'read_state': read}
            if reason:
                p['reason'] = reason
            self.do('read', 'claude', res['id'], params=p, run=run)
        return {'id': res['id'], 'already': False}

    def verdict(self, run, source, verdict, reason=None):
        p = {'verdict': verdict}
        if reason:
            p['reason'] = reason
        cur = self.door.status_of(int(source))
        action = 'verdict' if cur == mdb.NO_VERDICT else 'correct_verdict'
        return self.do(action, 'claude', int(source), params=p, run=run,
                       evidence=None if action == 'verdict' else {'source': int(source), 'quote': reason or verdict})

    def party(self, run, name, email, kind, source, quote):
        if email:
            r = self.one("SELECT party_id FROM party_handle WHERE kind='email' AND lower(value)=lower(?)", (email,))
            if r:
                return {'id': r[0], 'already': True}
        p = {'title': name, 'kind': kind or 'person'}
        if email:
            p['handles'] = [{'kind': 'email', 'value': email}]
        return self.do('create', 'claude', type='party', params=p, evidence=self.ev(source, quote), run=run)

    def new_item(self, run, type, title, holder, details, source, quote, due=None, next_check=None,
                 promised_by=None, requested_by=None, inferred=None):
        if type not in ITEM_TYPES:
            raise mdb.Refused('an item is commitment, reply_needed, decision_needed or for_info')
        if not due and not next_check:
            raise mdb.Refused('every open item has a due date or a next-check date')
        p = {'title': title, 'holder': self.who(holder), 'details': details or {}, 'due': due,
             'next_check': next_check}
        if promised_by:
            p['promised_by'] = self.who(promised_by)
        if requested_by:
            p['requested_by'] = self.who(requested_by)
        if inferred:
            p['_inferred'] = inferred
        return self.do('create', 'claude', type=type, params=p, evidence=self.ev(source, quote), run=run)

    def ask(self, run, question, source, quote, about=None, options=None, recommend=None, due=None):
        d = {'question': question, 'kind': 'question', 'asked_at': self.now()[:16]}
        if options:
            d['options'] = options
        if recommend:
            d['recommendation'] = recommend
        res = self.do('create', 'claude', type='decision_needed', run=run, evidence=self.ev(source, quote),
                      params={'title': self.t('q_title') + question[:90], 'holder': self.me, 'details': d,
                              'due': due, 'next_check': due or self.now()[:10]})
        if about:
            self.do('link', 'claude', res['id'], params={'to_id': self.resolve_item(about), 'role': 'about'},
                    evidence=self.ev(source, quote), run=run)
        return res

    def story(self, run, item, source, quote, position=None):
        return self.do('add_evidence', 'claude', self.resolve_item(item), evidence=self.ev(source, quote, position),
                       run=run)

    def act(self, run, item, action, params=None, source=None, quote=None, actor='claude'):
        return self.do(action, actor, self.resolve_item(item), params=params or {},
                       evidence=self.ev(source, quote), run=run)

    def draft(self, run, item, channel, kind, recipients, text, replies_to=None, cc=None, subject=None,
              mail_draft_id=None):
        tid = self.resolve_item(item)
        exists = self.one("SELECT t.id FROM followup f JOIN thing t ON t.id=f.thing_id WHERE t.type='draft' "
                          "AND f.status='ready' AND json_extract(f.details,'$.serves')=?", (tid,))
        if exists:
            raise mdb.Refused(f'thing {tid} already has a waiting draft ({exists[0]}); never two drafts for one item')
        title = self.one('SELECT title FROM thing WHERE id=?', (tid,))[0]
        d = {'text': text, 'channel_id': self.channel_id(channel), 'recipients': recipients, 'kind': kind,
             'serves': tid}
        for k, v in (('replies_to', replies_to), ('cc', cc), ('subject', subject), ('mail_draft_id', mail_draft_id)):
            if v:
                d[k] = v
        return self.do('create', 'claude', type='draft', run=run,
                       params={'title': self.t('d_title') + title[:100], 'holder': self.me, 'details': d})

    def remind(self, run, text, due, session, quote):
        return self.do('create', 'user', type='reminder', run=run, evidence=self.ev(session, quote),
                       params={'title': text[:120], 'holder': self.me, 'due': due, 'details': {'text': text}})


def main(argv=None):
    ap = argparse.ArgumentParser(description='Marionette run-time layer')
    ap.add_argument('--db', default=default_db())
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('brief'); b.add_argument('--full-questions', action='store_true')
    sub.add_parser('late')
    s = sub.add_parser('item'); s.add_argument('id')
    s = sub.add_parser('find'); s.add_argument('text')
    s = sub.add_parser('source'); s.add_argument('channel'); s.add_argument('external_id')
    s = sub.add_parser('sources'); s.add_argument('--since', required=True); s.add_argument('--verdict')
    s = sub.add_parser('status'); s.add_argument('--out', required=True); s.add_argument('--live-check', required=True)
    s.add_argument('--notes')
    s = sub.add_parser('export'); s.add_argument('--out', required=True)
    s = sub.add_parser('gate'); s.add_argument('--run', type=int, required=True)
    s.add_argument('--channels-file', default=os.path.join(os.path.dirname(HERE), 'channels.md'))
    s = sub.add_parser('run-start'); s.add_argument('--kind', default='schedule'); s.add_argument('--title')
    s = sub.add_parser('run-end'); s.add_argument('--run', type=int, required=True)
    s.add_argument('--failed', action='store_true'); s.add_argument('--summary')
    s = sub.add_parser('skip')
    for k in ('--run', '--channel', '--code', '--text'):
        s.add_argument(k, required=True)
    s = sub.add_parser('watermark')
    for k in ('--run', '--channel', '--at'):
        s.add_argument(k, required=True)
    s = sub.add_parser('record')
    for k in ('--run', '--channel', '--type', '--external-id', '--title'):
        s.add_argument(k, required=True)
    for k in ('--date', '--permalink', '--details', '--read', '--reason'):
        s.add_argument(k)
    s = sub.add_parser('verdict')
    for k in ('--run', '--source', '--verdict'):
        s.add_argument(k, required=True)
    s.add_argument('--reason')
    s = sub.add_parser('party')
    for k in ('--run', '--name', '--source', '--quote'):
        s.add_argument(k, required=True)
    s.add_argument('--email'); s.add_argument('--kind')
    s = sub.add_parser('new-item')
    for k in ('--run', '--type', '--title', '--holder', '--source', '--quote'):
        s.add_argument(k, required=True)
    for k in ('--promised-by', '--requested-by', '--due', '--next-check', '--details', '--inferred'):
        s.add_argument(k)
    s = sub.add_parser('ask')
    for k in ('--run', '--question', '--source', '--quote'):
        s.add_argument(k, required=True)
    for k in ('--about', '--options', '--recommend', '--due'):
        s.add_argument(k)
    s = sub.add_parser('story')
    for k in ('--run', '--item', '--source', '--quote'):
        s.add_argument(k, required=True)
    s.add_argument('--position')
    s = sub.add_parser('act')
    for k in ('--run', '--item', '--action'):
        s.add_argument(k, required=True)
    for k in ('--params', '--source', '--quote'):
        s.add_argument(k)
    s.add_argument('--actor', default='claude', choices=('claude', 'user', 'program'))
    s = sub.add_parser('draft')
    for k in ('--run', '--item', '--channel', '--kind', '--recipients', '--text-file'):
        s.add_argument(k, required=True)
    for k in ('--replies-to', '--cc', '--subject', '--mail-draft-id'):
        s.add_argument(k)
    s = sub.add_parser('remind')
    for k in ('--run', '--text', '--due', '--session', '--quote'):
        s.add_argument(k, required=True)
    a = ap.parse_args(argv)
    J = lambda v: json.loads(v) if v else None  # noqa: E731
    try:
        R = Run(a.db)
        c = a.cmd
        if c == 'brief':
            print(R.brief(a.full_questions)); return 0
        if c == 'gate':
            return R.gate(a.run, a.channels_file)
        run = int(a.run) if getattr(a, 'run', None) not in (None, '') else None
        out = {
            'late': lambda: R.late(),
            'item': lambda: R.item(a.id),
            'find': lambda: R.find(a.text),
            'source': lambda: R.source(a.channel, a.external_id),
            'sources': lambda: R.sources(a.since, a.verdict),
            'status': lambda: R.status(a.out, a.live_check, a.notes),
            'export': lambda: R.export(a.out),
            'run-start': lambda: R.run_start(a.kind, a.title),
            'run-end': lambda: R.run_end(run, a.failed, J(a.summary)),
            'skip': lambda: R.skip(run, a.channel, a.code, a.text),
            'watermark': lambda: R.watermark(run, a.channel, a.at),
            'record': lambda: R.record(run, a.channel, a.type, a.external_id, a.title, a.date, a.permalink,
                                       J(a.details), a.read, a.reason),
            'verdict': lambda: R.verdict(run, a.source, a.verdict, a.reason),
            'party': lambda: R.party(run, a.name, a.email, a.kind, a.source, a.quote),
            'new-item': lambda: R.new_item(run, a.type, a.title, a.holder, J(a.details), a.source, a.quote,
                                           a.due, a.next_check, a.promised_by, a.requested_by,
                                           a.inferred.split(',') if a.inferred else None),
            'ask': lambda: R.ask(run, a.question, a.source, a.quote, a.about, J(a.options), a.recommend, a.due),
            'story': lambda: R.story(run, a.item, a.source, a.quote, a.position),
            'act': lambda: R.act(run, a.item, a.action, J(a.params), a.source, a.quote, a.actor),
            'draft': lambda: R.draft(run, a.item, a.channel, a.kind, J(a.recipients),
                                     open(a.text_file, encoding='utf-8').read(), a.replies_to, J(a.cc), a.subject,
                                     a.mail_draft_id),
            'remind': lambda: R.remind(run, a.text, a.due, a.session, a.quote),
        }[c]()
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 0
    except mdb.Refused as e:
        print(json.dumps({'refused': str(e)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
