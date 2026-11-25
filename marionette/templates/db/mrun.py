#!/usr/bin/env python3
"""Marionette by Hesham Elmahdy (github.com/heshamfm): the run-time layer, version 1.8.1.

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
 issues: problems in how Marionette itself works (1.7)
  mrun.py issue-new --run ID --title T --reported-by WHO --context WHERE --what-happened X --found X
                    [--owner-words X] --asked X --source ID --quote Q      written in one fixed template
  mrun.py issue-append --run ID --issue I --text T --source ID --quote Q  add to an issue, word for word
  mrun.py issue-act --run ID --issue I --action start_work|resolve|reopen [--params JSON] [--source ID --quote Q]
  mrun.py issues [--all]                                    the register
  mrun.py issue I                                           one issue exactly as stored (what the owner is shown)
  mrun.py version                                           the release of this database and of these programs
 1.8
  mrun.py unreadable --run ID --source S --reason R          close a source that still cannot be read on a second try
  mrun.py panel-data --out FILE [--message F] [--gate-file F] [--jobs F]   what the panel page shows
  mrun.py apply-panel --run ID --file BATCHES --out RESULTS  apply what the owner submitted on the panel
  mrun.py act --run ID --item I --action retract_evidence --params '{"evidence_id": N, "reason": "..."}'
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
  'reply_needed_by': 'reply needed from {n}', 'decision_needed_by': 'decision needed from {n}',
  'step_with': 'next step with {n}',
  'check_left': 'Item {i}: its next check {d} came and this run did not handle it: {t}',
  'undated_item': 'Item {i} is open with no due date and no next check: {t}',
  'issue_head': 'Written by: {w}, {at}, {c}.', 'issue_what': 'What happened', 'issue_found': 'What was found, quoting the sources',
  'issue_words': "The owner's words, verbatim", 'issue_asked': 'What is asked, step by step',
  'issue_similar': 'Look for the similar cases of this problem in the rules, the programs and the data, and fix them all, not this one only.',
  'issue_no_words': 'The owner said nothing about it: it was found by {w}',
  'issue_line': 'Issue {i} ({s}): {t}', 'issue_add': 'Added {at} ({b}):', 'issue_res': 'How it was resolved: ',
  'info_open': 'A for-information item is still open after it was told: mark it seen, or convert it when it asks something of you: {i} {t}',
  'backlog': 'A source from an earlier run has no verdict since {d}: {i} {t}',
  'no_file': 'Rule decision {d} does not name the file that carries it: add a correction line to decisions.md naming {d} and "File: <file>"',
  'parked': '{n} sources were read in part more than 48 hours ago and are not finished; try the oldest again in this run and record what remains: {x}',
  'unreadable_told': 'Could not be read after a second attempt (told once): {t}: {r}',
  'panel_said': 'On the panel: {a}',
  'tag_delegate_full': '[delegated: decide and do] ', 'tag_delegate_ask': '[delegated: prepare and ask] ',
  'tag_custom': '[your instructions] ',
  'a_done': 'done', 'a_strike': 'struck out, will not do it', 'a_seen': 'seen', 'a_sent_as_is': 'sent as is',
  'a_discarded': 'discarded', 'a_postpone': 'postponed', 'a_answer': 'agreed with the recommendation',
  'a_take_back': 'taken back',
  'unmarked': 'Spam the rules cover that could not be marked ({n}): try marking it again now, and name it first in the message with why it failed:',
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
  'reply_needed_by': 'رد مطلوب من {n}', 'decision_needed_by': 'قرار مطلوب من {n}',
  'step_with': 'الخطوة عند {n}',
  'check_left': 'البند {i} حلّ موعد فحصه {d} ولم يعالجه هذا التشغيل: {t}',
  'undated_item': 'البند {i} مفتوح بلا موعد ولا موعد فحص: {t}',
  'issue_head': 'كتبه: {w}، {at}، {c}.', 'issue_what': 'ما حدث', 'issue_found': 'ما وُجد، مع اقتباس المصادر',
  'issue_words': 'كلام صاحب النظام بنصه', 'issue_asked': 'المطلوب، خطوة خطوة',
  'issue_similar': 'ابحث عن الحالات المشابهة لهذه المشكلة في القواعد والبرامج والبيانات، وأصلحها كلها، لا هذه وحدها.',
  'issue_no_words': 'لا كلام له فيها: وجدها {w}',
  'issue_line': 'المشكلة {i} ({s}): {t}', 'issue_add': 'إضافة {at} ({b}):', 'issue_res': 'طريقة الحل: ',
  'info_open': 'بند للعلم ما زال مفتوحًا بعد إبلاغه: أغلقه (اطُّلع عليه)، أو حوّله إلى قرار أو رد إن كان فيه خطوة على صاحب النظام: {i} {t}',
  'backlog': 'مصدر من تشغيل سابق بلا حكم منذ {d}: {i} {t}',
  'no_file': 'قرار القاعدة {d} لا يذكر الملف الذي يحملها: أضف سطر تصحيح إلى decisions.md يذكر {d} و«الملف: <الملف>»',
  'parked': '{n} مصدرًا قُرئت جزئيًا قبل أكثر من 48 ساعة ولم تُكمل؛ أعد محاولة أقدمها في هذا التشغيل وسجّل ما بقي: {x}',
  'unreadable_told': 'تعذرت قراءته بعد محاولة ثانية (يُذكر مرة): {t}: {r}',
  'panel_said': 'من اللوحة: {a}',
  'tag_delegate_full': '[فوّضتَه كاملًا] ', 'tag_delegate_ask': '[فوّضتَه مع الرجوع إليك] ', 'tag_custom': '[تعليماتك] ',
  'a_done': 'أُنجز', 'a_strike': 'اشطبه: لن أعمل عليه', 'a_seen': 'اطّلعتُ عليه', 'a_sent_as_is': 'أرسلتُها كما هي',
  'a_discarded': 'تخلّصتُ منها', 'a_postpone': 'أجِّل', 'a_answer': 'موافق على المقترح', 'a_take_back': 'أسترجعه لنفسي',
  'unmarked': 'مزعج لم أستطع تعليمه ({n}): أعد محاولة التعليم الآن، واذكره أول الرسالة مع سبب التعذر:',
 },
}


UNREADABLE = 'UNREADABLE after a second attempt: '
RETRACTED_SQL = "AND id NOT IN (SELECT CAST(new_value AS INTEGER) FROM audit WHERE action='retract_evidence')"


def followup_of(db_path):
    """The followup folder of a database at F/db/marionette.db."""
    return os.path.dirname(os.path.dirname(os.path.abspath(db_path)))


def read_state(db_path):
    try:
        return json.load(open(os.path.join(followup_of(db_path), 'state.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


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
        # 1.7: "reply/decision needed" names whoever holds the next step when it is not the user
        if ty in ('reply_needed', 'decision_needed'):
            h = self.one('SELECT holder_id FROM followup WHERE thing_id=?', (tid,))
            if h and h[0] is not None and h[0] != self.me:
                return self.t(ty + '_by', n=self.name(h[0]).strip())
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
        e = self.one("SELECT quote FROM evidence WHERE thing_id=? AND id NOT IN (SELECT CAST(new_value AS INTEGER) FROM audit WHERE action='retract_evidence') ORDER BY id DESC LIMIT 1", (tid,))
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
            if x['type'] == 'for_info':  # 1.8: nothing to do on it, so never late
                continue
            d = json.loads(self.one('SELECT details FROM followup WHERE thing_id=?', (x['id'],))[0])
            if not (x['type'] == 'decision_needed' and (d.get('old_question') or d.get('kind') == 'question')):
                out[x['id']] = x['why']
        return out

    def checks_due(self):
        """Alive items that are not questions and whose next check is today or earlier (1.7)."""
        today = self.now()[:10]
        return [r for r in self.items() if r['next_check'] and r['next_check'][:10] <= today
                and not self.is_question(r)]

    def touched_in_run(self, tid, run):
        return bool(self.one('SELECT 1 FROM audit WHERE thing_id=? AND run_id=? LIMIT 1', (tid, run)))

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
        mine = [r for r in rows if r['holder_id'] == self.me and r['type'] != 'for_info']  # 1.8
        L.append('')
        L.append(f'## ON THE USER ({len(mine)}): the next step is the user\'s. The ONLY list a message may present as '
                 '"waiting for you" or "you need to do today"; an item held by anyone else is never there, whatever its '
                 'type or date')
        for r in mine:
            L.append(f"- {r['id']} | due {r['due'] or '-'}" + (' LATE' if r['id'] in late else '') + f" | {r['title']}")
        cc = self.chat_check(rows)
        L.append('')
        L.append(f'## CHAT CHECK ({len(cc)}): the next step is the user\'s and it lives in a chat, where the user may '
                 'already have acted. Open each chat that shows no unread messages (read receipts) and look for the '
                 'user\'s message after the last event; record it and close or hand over the item')
        for x in cc:
            L.append(f"- {x['id']} | last event {x['last']}" + (' | chat draft waiting' if x['draft'] else '') +
                     (' | LATE' if x['id'] in late else '') + f" | {x['title']}")
        mp = self.marionette_party()
        dg = [r for r in rows if r['holder_id'] == mp]
        L.append('')
        L.append(f'## DELEGATED TO MARIONETTE ({len(dg)}): the user handed these over on the panel; the instructions '
                 'are the latest story line. "decide and do": do it within the hard limits of the manual (a reply is a '
                 'draft for the user to send) and report; "prepare and ask": prepare it, then ask before any step that '
                 'acts; "your instructions": do what they say, for this item only')
        for r in dg:
            L.append(f"- {r['id']} | due {r['due'] or '-'} | {r['title']} | last {self.last_event(r['id'])[:200]}")
        cd = self.checks_due()
        L.append('')
        L.append(f'## CHECKS DUE ({len(cd)}): the next check came. Handle EVERY one in this run: look it up live, then '
                 'story or act with what was found, or set_next_check to a later date quoting what was checked; the '
                 'end-of-run check lists any left')
        for r in cd:
            L.append(f"- {r['id']} | next_check {r['next_check'][:10]} | holder "
                     f"{self.name(r['holder_id']).strip() or '-'} | {r['title']}")
        iss = self.issues()
        L.append('')
        L.append(f'## Marionette issues open ({len(iss)}): problems in how Marionette works (mrun.py issues)')
        for x in iss:
            L.append(f"- {x['id']} | {x['status']} | reported {x['created']} by {x['reported_by']} | {x['title']}")
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
            "SELECT * FROM evidence WHERE thing_id=? AND id NOT IN (SELECT CAST(new_value AS INTEGER) FROM audit WHERE action='retract_evidence') ORDER BY id", (tid,))]
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
                         f"{self.t('step_with', n=self.name(r['holder_id']).strip())})")
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
                if code == 'spam_unmarked':
                    continue  # 1.8.1: listed in its own section below, from any run, until a run marks it
                ign.setdefault(code, []).append(x['title'])
            else:
                inf.append(x['title'])
        undated = [x for x in self.items() if not x['due'] and not x['next_check'] and x['status'] in ALIVE
                   and not self.is_question(x)]
        # 1.7: every check that came is handled in the run that meets it (anything it recorded on the item: a story
        # line with what was found, an act, or the next check moved with what was checked), and every open item keeps
        # a date
        for x in self.checks_due():
            if not self.touched_in_run(x['id'], run):
                bad.append(self.t('check_left', i=x['id'], d=x['next_check'][:10], t=x['title'][:90]))
        for x in undated:
            bad.append(self.t('undated_item', i=x['id'], t=x['title'][:90]))
        start = r['started'][:16]
        # 1.8: a for-information item is closed once told; a source left unclassified by an earlier run; a rule
        # decision that does not name its file; sources read in part and parked. Like every 1.8 guard they judge only
        # what was recorded since the guard started (meta unclassified_guard_since), never what came before it
        since = self.door.meta('unclassified_guard_since') or start
        for x in self.q("SELECT t.id, t.title FROM thing t JOIN followup f ON f.thing_id=t.id WHERE t.type='for_info' "
                        "AND f.status IN ('open','new') AND t.created_at>=? AND t.created_at<? ORDER BY t.id",
                        (since, start)):
            bad.append(self.t('info_open', i=x['id'], t=x['title'][:80]))
        for x in self.q("SELECT t.id, t.title, t.created_at FROM source s JOIN thing t ON t.id=s.thing_id "
                        "WHERE s.verdict IS NULL AND s.read_fail_reason IS NULL AND t.created_at>=? AND t.created_at<? "
                        "ORDER BY t.id LIMIT 30", (since, start)):
            bad.append(self.t('backlog', d=x['created_at'][:16], i=x['id'], t=x['title'][:70]))
        for d in self.decisions_without_file():
            bad.append(self.t('no_file', d=d))
        lim = (mdb.Door.as_time(self.now()) - datetime.timedelta(hours=48)).strftime('%Y-%m-%d %H:%M')
        parked = self.q("SELECT t.id, t.title FROM source s JOIN thing t ON t.id=s.thing_id WHERE s.verdict IS NULL "
                        "AND s.read_fail_reason IS NOT NULL AND s.read_fail_reason NOT LIKE 'UNREADABLE%' "
                        "AND t.created_at<? ORDER BY t.id", (lim,))
        if parked:
            notes.append(self.t('parked', n=len(parked), x=self.t('sep').join(
                f"{x['id']} {x['title'][:50]}" for x in parked[:10])))
        for x in self.q("SELECT t.title, s.read_fail_reason FROM source s JOIN thing t ON t.id=s.thing_id WHERE "
                        "s.run_id=? AND s.read_fail_reason LIKE 'UNREADABLE%'", (run,)):
            notes.append(self.t('unreadable_told', t=x['title'][:80], r=x['read_fail_reason'][len(UNREADABLE):160]))
        print(self.t('gate_head', s=start, r=read, n=len(enabled)))
        unmarked = self.q("SELECT t.id, t.title, s.verdict_reason FROM source s JOIN thing t ON t.id=s.thing_id "
                          "WHERE s.verdict='ignored' AND s.verdict_reason LIKE 'spam_unmarked:%' ORDER BY t.id")
        if unmarked:
            print(self.t('unmarked', n=len(unmarked)))
            for x in unmarked:
                print(f"- [{x['id']}] {x['title']}: {x['verdict_reason'].split(':', 1)[1].strip()}")
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
        if not (bad or notes or un):
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

    # ------------------------------------------------------------ the panel (1.8)
    # page action -> door action. The text the owner typed is the quote; for the self-explaining buttons it may be
    # empty, and the quote is then "On the panel: <action>".
    PANEL_ACTIONS = {
        'done': 'complete', 'not_needed': 'complete', 'strike': 'cancel', 'postpone': 'defer',
        'hand_over': 'hand_over', 'answer': 'record_decision', 'seen': 'mark_seen', 'sent_as_is': 'send',
        'discarded': 'abandon', 'note': 'add_evidence', 'delegate_full': 'hand_over', 'delegate_ask': 'hand_over',
        'custom': 'hand_over', 'take_back': 'hand_over',
    }
    OPTIONAL_REASON = ('done', 'strike', 'seen', 'sent_as_is', 'discarded', 'postpone', 'answer', 'take_back')
    TAGS = ('delegate_full', 'delegate_ask', 'custom')

    CHAT_WORDS = ('whatsapp', 'telegram', 'signal', 'slack', 'teams', 'chat', 'واتساب')

    def chat_check(self, rows):
        """1.8.1: items whose next step is the user's and that rest on a chat channel (a chat source, a waiting chat
        draft, or a chat named in the title or details). The user may have answered in the chat, which no run sees
        unless it opens the chat."""
        chat_ch = {r['id'] for r in self.q('SELECT t.id, t.title FROM channel c JOIN thing t ON t.id=c.thing_id')
                   if any(w in r['title'].lower() for w in self.CHAT_WORDS)}
        drafts = {json.loads(r[0]).get('serves') for r in self.q(
            "SELECT f.details FROM followup f JOIN thing t ON t.id=f.thing_id WHERE t.type='draft' AND f.status='ready'")
            if json.loads(r[0]).get('channel_id') in chat_ch}
        out = []
        for r in rows:
            if r['holder_id'] != self.me or self.is_question(r):
                continue
            src = {x[0] for x in self.q('SELECT DISTINCT s.channel_id FROM evidence e JOIN source s ON '
                                        's.thing_id=e.source_id WHERE e.thing_id=?', (r['id'],))}
            text = (r['title'] + ' ' + r['details']).lower()
            if src & chat_ch or r['id'] in drafts or any(w in text for w in ('whatsapp', 'واتساب')):
                out.append({'id': r['id'], 'title': r['title'], 'last': self.last_event(r['id'])[:16],
                            'draft': r['id'] in drafts})
        return out

    def marionette_party(self):
        v = self.door.meta('marionette_party_id')
        return int(v) if v else -1

    def strip_tag(self, title):
        for lang in TEXT.values():
            for k in ('tag_delegate_full', 'tag_delegate_ask', 'tag_custom'):
                if title.startswith(lang[k]):
                    return title[len(lang[k]):]
        return title

    def item_link(self, tid):
        r = self.one("SELECT s.external_id, s.permalink, c.title FROM evidence e JOIN source s ON s.thing_id=e.source_id "
                     "JOIN thing c ON c.id=s.channel_id WHERE e.thing_id=? ORDER BY e.id DESC LIMIT 1", (tid,))
        if not r:
            return None
        if r['permalink'] and str(r['permalink']).startswith('https://'):
            return r['permalink']
        if r['title'] == 'gmail' and re.fullmatch(r'[0-9a-f]{12,20}', r['external_id'] or ''):
            return 'https://mail.google.com/mail/u/0/#all/' + r['external_id']
        return None

    def panel_item(self, r, late):
        d = json.loads(r['details'])
        try:
            t0 = self.door.first_seen(r['id'])
        except Exception:
            t0 = None
        age = (mdb.Door.as_time(self.now()) - (t0 or mdb.Door.as_time(r['created_at'][:16]))).days
        return {'id': r['id'], 'type': r['type'], 'type_label': self.ar_type(r['id'], r['type']), 'title': r['title'],
                'status': r['status'], 'due': r['due'], 'next_check': r['next_check'], 'age_days': age,
                'holder': self.name(r['holder_id']).strip() or '-', 'late': late.get(r['id']),
                'last': self.last_event(r['id'])[:300], 'link': self.item_link(r['id']),
                'question': d.get('question'), 'options': d.get('options'), 'recommendation': d.get('recommendation')}

    def panel_data(self, run_message=None, gate_file=None, jobs=None):
        """What the panel page shows: the sections of the run message, from the database (1.8)."""
        late = self.late_map()
        rows = list(self.items())
        qs = [r for r in rows if self.is_question(r)]
        its = [r for r in rows if not self.is_question(r)]
        mp = self.marionette_party()
        mine = [r for r in its if r['holder_id'] == self.me and r['type'] != 'for_info']
        out = {'built_at': self.now()[:16], 'language': self.door.meta('language', 'en'), 'run_message': run_message,
               'timezone': self.door.meta('timezone', 'UTC'), 'workdays': json.loads(self.door.meta('workdays', '[]') or '[]'),
               'late': [self.panel_item(r, late) for r in mine if r['id'] in late],
               'on_you': [self.panel_item(r, late) for r in mine if r['id'] not in late],
               'questions': [self.panel_item(r, late) for r in qs],
               'delegated': [self.panel_item(r, late) for r in its if r['holder_id'] == mp],
               'for_info': [self.panel_item(r, late) for r in its if r['type'] == 'for_info' and r['holder_id'] == self.me],
               'waiting': [self.panel_item(r, late) for r in its if r['holder_id'] not in (self.me, mp)],
               'drafts': [], 'gate': [], 'jobs': jobs or []}
        for d in self.q("SELECT t.id, t.title, t.created_at, f.details FROM followup f JOIN thing t ON t.id=f.thing_id "
                        "WHERE t.type='draft' AND f.status='ready' ORDER BY t.id"):
            dd = json.loads(d['details'])
            out['drafts'].append({'id': d['id'], 'title': d['title'], 'created': d['created_at'][:16],
                                  'to': dd.get('recipients'), 'subject': dd.get('subject'),
                                  'text': (dd.get('text') or '')[:4000], 'serves': dd.get('serves')})
        if gate_file and os.path.exists(gate_file):
            out['gate'] = [x for x in open(gate_file, encoding='utf-8').read().splitlines() if x.strip()][:80]
        return out

    def apply_panel(self, run, batches_file):
        """Apply what the owner submitted on the panel (1.8). Each batch becomes a session source; each line one door
        action in the owner's name, quoting what was typed. A line already applied from the same batch is reported
        and not written again. Every line reports ok, or the door's refusal."""
        data = json.load(open(batches_file, encoding='utf-8'))
        result = {}
        for b in data.get('batches', []):
            bid = str(b.get('id') or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{6,80}', bid):
                result[bid or '?'] = {'status': 'refused', 'error': 'batch id missing or malformed'}
                continue
            lines = b.get('lines') or []
            src = self.record(run, mdb.SESSIONS_CHANNEL, 'session', 'panel/' + bid,
                              title=f"Panel {(b.get('submitted_at') or '')[:16]} ({len(lines)})",
                              date=(b.get('submitted_at') or self.now())[:16],
                              details={'kind': 'panel_batch', 'lines': lines}, read='full')
            sid = src['id']
            res = [self.apply_panel_line(run, sid, ln) for ln in lines]
            ok = [x['ok'] for x in res]
            try:
                if any(ok):
                    self.verdict(run, sid, 'linked')
                elif res:
                    self.verdict(run, sid, 'ignored', 'panel: every line of this batch was refused by the door')
            except mdb.Refused:
                pass
            result[bid] = {'status': 'applied' if all(ok) else ('partly_refused' if any(ok) else 'refused'),
                           'source': sid, 'lines': res, 'applied_at': self.now()[:16]}
        return result

    def apply_panel_line(self, run, sid, ln):
        item, act, reason = ln.get('item'), ln.get('action'), str(ln.get('reason') or '').strip()
        base = {'item': item, 'action': act}
        try:
            if act not in self.PANEL_ACTIONS:
                raise mdb.Refused(f'unknown action "{act}"')
            tid = int(item)
            if len(reason) < 3:
                if act in self.OPTIONAL_REASON and not (act == 'answer' and not ln.get('accepted')):
                    reason = self.t('panel_said', a=self.t('a_' + act)) + (
                        f" ({ln.get('date')})" if act == 'postpone' and ln.get('date') else '') + (
                        f" ({ln.get('answer')})" if act == 'answer' else '')
                else:
                    raise mdb.Refused('this action needs the owner\'s words: a reason or instructions')
            ty = self.one('SELECT t.type, t.title, f.due, f.status, f.details FROM thing t JOIN followup f '
                          'ON f.thing_id=t.id WHERE t.id=?', (tid,))
            if not ty:
                raise mdb.Refused(f'no item {tid}')
            if act == 'custom' and ty['type'] == 'draft':   # instructions on a draft go to the item it serves
                tid = int(json.loads(ty['details'] or '{}').get('serves') or tid)
                ty = self.one('SELECT t.type, t.title, f.due, f.status, f.details FROM thing t JOIN followup f '
                              'ON f.thing_id=t.id WHERE t.id=?', (tid,))
            if self.one("SELECT 1 FROM evidence WHERE thing_id=? AND source_id=? AND quote=?", (tid, sid, reason)):
                return {**base, 'ok': True, 'already': True}
            door_act, p = self.PANEL_ACTIONS[act], {}
            if act in ('done', 'not_needed', 'strike') and ty['type'] == 'for_info':
                door_act = 'mark_seen'        # a for-information item is closed by marking it seen
            elif act == 'done':
                p = {'close_reason': 'done'}
            elif act == 'not_needed':
                p = {'close_reason': 'not_needed'}
            elif act == 'postpone':
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?', str(ln.get('date') or '')):
                    raise mdb.Refused('postpone needs a date, and may give a time')
                p = {'due': ln['date']}
                if ty['status'] == 'deferred':
                    door_act = 'change_due'   # already postponed: move its date
            elif act == 'hand_over':
                p = {'holder': self.who(ln.get('holder')), 'title': str(ln.get('title') or '').strip(),
                     'due': ln.get('date') or None,
                     'next_check': ln.get('next_check') or (datetime.date.fromisoformat(self.now()[:10])
                                                          + datetime.timedelta(days=3)).isoformat()}
                if not p['title']:
                    raise mdb.Refused('a hand-over needs what the new holder does next')
            elif act in self.TAGS:
                p = {'holder': self.marionette_party(), 'title': self.t('tag_' + act) + self.strip_tag(ty['title']),
                     'due': ty['due'], 'next_check': self.now()[:10]}
            elif act == 'take_back':
                p = {'holder': self.me, 'title': self.strip_tag(ty['title']), 'due': ty['due'],
                     'next_check': self.now()[:10]}
            elif act == 'answer':
                p = {'decision': str(ln.get('answer') or reason)}
            elif act == 'discarded':
                p = {'reason': reason}
            self.do(door_act, 'user', tid, params=p, evidence={'source': sid, 'quote': reason}, run=run)
            return {**base, 'ok': True}
        except mdb.Refused as e:
            return {**base, 'ok': False, 'error': str(e)}
        except (ValueError, TypeError, KeyError) as e:
            return {**base, 'ok': False, 'error': f'bad line: {e}'}

    @staticmethod
    def write_json(path, obj):
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        return {'written': path, 'bytes': os.path.getsize(path)}

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
        out = {'run': res['id'], 'started': self.now()[:16]}
        if kind == 'schedule':
            miss = self.missed_slots()
            if miss:
                out['missed_slots'] = miss
                out['missed_rule'] = ('scheduled runs of the last 48 hours that did not happen or started late: say '
                                      'so first in the message and record an issue unless one is open (1.8)')
        return out

    def missed_slots(self, hours=48):
        """1.8: slots of the periodic schedule (state.json "periodic_schedule": {"times": ["10:57", ...],
        "since": "YYYY-MM-DD HH:MM"}) in the last 48 hours with no scheduled run started within 30 minutes."""
        st = read_state(self.door.path)
        sched = st.get('periodic_schedule') or {}
        times, since = sched.get('times') or [], sched.get('since') or '2000-01-01 00:00'
        now = mdb.Door.as_time(self.now())
        starts = [mdb.Door.as_time(r[0]) for r in self.q(
            "SELECT started FROM run WHERE trigger_kind='schedule' AND started>=?",
            ((now - datetime.timedelta(hours=hours + 4)).strftime('%Y-%m-%d %H:%M'),))]
        out = []
        for d in range(hours // 24 + 1, -1, -1):
            day = (now - datetime.timedelta(days=d)).date()
            for t in times:
                slot = datetime.datetime.combine(day, datetime.time(*map(int, t.split(':'))))
                if slot > now - datetime.timedelta(minutes=45) or slot < now - datetime.timedelta(hours=hours):
                    continue
                if slot.strftime('%Y-%m-%d %H:%M') < since:
                    continue
                near = [x for x in starts if datetime.timedelta(minutes=-5) <= x - slot <= datetime.timedelta(hours=3)]
                if not near:
                    out.append(f"{slot.strftime('%Y-%m-%d %H:%M')}: no run")
                elif min(near) - slot > datetime.timedelta(minutes=30):
                    out.append(f"{slot.strftime('%Y-%m-%d %H:%M')}: started late at {min(near).strftime('%H:%M')}")
        return out

    def stale_unclassified(self, hours=48):
        """1.8: sources recorded since the guard started (meta unclassified_guard_since), older than 48 hours, with no
        verdict and no recorded reason."""
        since = self.door.meta('unclassified_guard_since')
        if not since:
            return []
        lim = (mdb.Door.as_time(self.now()) - datetime.timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M')
        return self.q("SELECT t.id, t.title FROM source s JOIN thing t ON t.id=s.thing_id WHERE s.verdict IS NULL "
                      "AND s.read_fail_reason IS NULL AND t.created_at>=? AND t.created_at<? ORDER BY t.id", (since, lim))

    def decisions_without_file(self, first=None):
        """1.8: rule decisions whose line in decisions.md does not end by naming the file that carries them, and that
        no later line corrects (a later line naming the decision and the file). A rule line is one whose type column
        reads rule or قاعدة; the file is named as "File:", "Files:", "الملف:" or "الملفات:"."""
        path = os.path.join(followup_of(self.door.path), 'decisions.md')
        if not os.path.exists(path):
            return []
        lines = open(path, encoding='utf-8').read().splitlines()
        first = first if first is not None else int(self.door.meta('decision_file_rule_from', '0') or 0)
        named = re.compile(r'(\bfiles?:|الملفا?ت?:)', re.I)
        out = []
        for i, ln in enumerate(lines):
            m = re.match(r'^- D(\d+) \| [^|]+\| *(rule|قاعدة) *\|', ln, re.I)
            if not m or int(m.group(1)) < first or named.search(ln[-400:]):
                continue
            tag = 'D' + m.group(1)
            if any(re.search(r'\b' + tag + r'\b', x) and named.search(x) for x in lines[i + 1:]):
                continue
            out.append(tag)
        return out

    def unreadable(self, run, source, reason):
        """1.8: a source that still cannot be read in full on a second attempt in a later run (a voice note that will
        not play, a deleted message, access refused) is closed as unreadable with what was tried, and told once."""
        src = int(source)
        r = self.one('SELECT s.verdict, s.read_state, t.created_at FROM source s JOIN thing t ON t.id=s.thing_id '
                     'WHERE s.thing_id=?', (src,))
        if not r:
            raise mdb.Refused(f'{src} is not a source')
        if r['verdict'] is not None or r['read_state'] == 'full':
            raise mdb.Refused('this source was read in full or has a verdict: give it a verdict instead')
        started = self.one('SELECT started FROM run WHERE thing_id=?', (run,))[0]
        if r['created_at'] >= started:
            raise mdb.Refused('try again in a later run first: unreadable is only for a second attempt')
        if len((reason or '').strip()) < 15:
            raise mdb.Refused('say what was tried and why it cannot be read')
        return self.do('read', 'claude', src, params={'read_state': 'failed', 'reason': UNREADABLE + reason.strip()},
                       run=run)

    def run_end(self, run, failed=False, summary=None):
        kind = self.one('SELECT trigger_kind FROM run WHERE thing_id=?', (run,))
        if not failed and kind and kind[0] == 'schedule':
            old = self.stale_unclassified()
            if old:
                raise mdb.Refused('sources read more than 48 hours ago still have no verdict and no recorded reason; '
                                  'read each in full and give its verdict, or record why it cannot be read: '
                                  + '; '.join(f"{x['id']} {x['title'][:60]}" for x in old[:15]))
        p = {'failed': bool(failed)}
        if summary:
            p['summary'] = summary
        return self.do('close', 'program', run, params=p)

    def skip(self, run, channel, code, text):
        self.channel_id(channel)
        # Time, length or consumption is never a reason to leave a channel unread (added in 1.6).
        if re.search(r'(ضيق الوقت|الوقت|وقت|توفير|استهلاك|اختصار|\btime\b|\bsave\b|consumption|usage|tokens?|too long|shorten)',
                     text or '', re.I):
            raise mdb.Refused('a skip never rests on time, length or consumption; read the channel, or name the tool '
                              'failure, page failure, refused permission or what remains unread and why')
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
            # 1.7: a source recorded before can be read further later: --read moves its read state forward
            # (unread or failed -> partial -> full) while it has no verdict; never backward
            cur = self.source(channel, external_id)
            rank = {'unread': 0, 'failed': 0, 'partial': 1, 'full': 2}
            if read and cur.get('verdict') is None and rank.get(read, -1) > rank.get(cur.get('read_state'), 0):
                p = {'read_state': read}
                if reason:
                    p['reason'] = reason
                self.do('read', 'claude', old[0], params=p, run=run)
                return {'id': old[0], 'already': True, 'read_updated': True, **self.source(channel, external_id)}
            return {'id': old[0], 'already': True, **cur}
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
        # 1.8: a question or request to the user is never "for information"
        if type == 'for_info' and p['holder'] == self.me and re.search(
                r'[?؟]', title + json.dumps(details or {}, ensure_ascii=False)):
            raise mdb.Refused('this item asks the user something (it holds a question mark): make it decision_needed '
                              'or reply_needed; for_info is only for what asks nothing of the user')
        res = self.do('create', 'claude', type=type, params=p, evidence=self.ev(source, quote), run=run)
        # 1.8: the open items with the same counterparty, so the same promise is never opened twice
        parties = {x for x in (p['holder'], p.get('promised_by'), p.get('requested_by')) if x and x != self.me}
        if parties:
            ph = ','.join('?' * len(parties))
            sim = self.q(f"SELECT DISTINCT t.id, t.title FROM thing t JOIN followup f ON f.thing_id=t.id "
                         f"LEFT JOIN link l ON l.from_id=t.id AND l.role IN ('promised_by','requested_by') "
                         f"WHERE f.status IN ('open','new','deferred') AND t.id<>? AND t.type IN "
                         f"('commitment','reply_needed','decision_needed','for_info') AND "
                         f"(f.holder_id IN ({ph}) OR l.to_id IN ({ph}))", (res['id'], *parties, *parties))
            if sim:
                res['similar_open'] = [f"{x['id']}: {x['title'][:100]}" for x in sim]
                res['similar_rule'] = ('same counterparty: if one of these carries the same promise, merge into it '
                                       '(old version kept in the story); if unsure, keep both and ask the user')
        return res

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
        tid = self.resolve_item(item)
        dup = self.one("SELECT id FROM evidence WHERE thing_id=? AND source_id=? AND quote=? " + RETRACTED_SQL,
                       (tid, int(source), quote))
        if dup:  # 1.8: the same line twice is never written again
            return {'id': tid, 'already': True, 'evidence': dup[0]}
        return self.do('add_evidence', 'claude', tid, evidence=self.ev(source, quote, position), run=run)

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

    # ------------------------------------------------------------ issues register (1.7)
    ISSUE_PARTS = (('what_happened', 'issue_what'), ('found', 'issue_found'), ('owner_words', 'issue_words'),
                   ('asked', 'issue_asked'))

    def issue_new(self, run, title, reported_by, context, source, quote, what_happened=None, found=None,
                  owner_words=None, asked=None, holder=None, actor='claude', description=None):
        """A problem in how Marionette works, always written in one template the program builds, so no part can be
        left out: who wrote it, when and where; what happened; what was found, quoting the sources; the owner's
        words verbatim (required when the owner reported it); what is asked, step by step; and always the step to
        find and fix the similar cases."""
        if description and not what_happened:
            raise mdb.Refused('an issue is written in the template: --what-happened, --found, --owner-words, --asked '
                              '(db_usage.md, Issues register)')
        parts = {'what_happened': what_happened, 'found': found, 'owner_words': owner_words, 'asked': asked}
        # the owner's words may be left out only when the issue was clearly found by Marionette itself
        owner = self.one('SELECT title FROM thing WHERE id=?', (self.me,))[0] or ''
        names = [w for w in re.split(r'\s+', owner) if len(w) > 1]
        by_owner = actor == 'user' or re.search(r'\b(owner|user)\b', reported_by or '', re.I) or any(
            re.search(r'(?<!\w)' + re.escape(w) + r'(?!\w)', reported_by or '', re.I) for w in names)
        by_marionette = re.match(r'\s*(run\b|the auditor\b|auditor\b|program\b)', reported_by or '', re.I)
        if not (owner_words or '').strip() and by_marionette and not by_owner:
            parts['owner_words'] = self.t('issue_no_words', w=reported_by)
        short = [k for k, v in parts.items() if len((v or '').strip()) < 20]
        if short:
            raise mdb.Refused('the issue template is incomplete (each part at least a full sentence): ' + ', '.join(short))
        L = [self.t('issue_head', w=reported_by, at=self.now()[:16], c=context), '']
        for key, head in self.ISSUE_PARTS:
            L += [self.t(head) + ':', parts[key].strip(), '']
        L.append('- ' + self.t('issue_similar'))
        h = self.me if holder in (None, 'me') else (int(self.door.meta('marionette_party_id')) if holder == 'marionette'
                                                    else int(holder))
        d = {'description': '\n'.join(L), 'reported_by': reported_by, 'context': context, **parts}
        r = self.do('create', actor, type='issue', run=run, evidence=self.ev(source, quote),
                    params={'title': title, 'holder': h, 'details': d, 'next_check': self.now()[:10]})
        r['saved_text'] = self.issue_text(r['id'])
        return r

    def issue_text(self, issue):
        """The issue exactly as stored: what a session shows the owner, never a text written beside it."""
        r = self.one("SELECT t.id, t.title, f.status, f.details FROM followup f JOIN thing t ON t.id=f.thing_id "
                     "WHERE t.id=? AND t.type='issue'", (int(issue),))
        if not r:
            raise mdb.Refused(f'no issue {issue}')
        d = json.loads(r['details'])
        L = [self.t('issue_line', i=r['id'], s=r['status'], t=r['title']), '', d.get('description') or '']
        for a in d.get('additions') or []:
            L += ['', self.t('issue_add', at=a['at'], b=a['by']), a['text']]
        if d.get('resolution'):
            L += ['', self.t('issue_res') + d['resolution']]
        return '\n'.join(L)

    def issue_append(self, run, issue, text, source, quote, by=None, actor='claude'):
        r = self.do('append', actor, int(issue), params={'text': text, 'by': by or actor},
                    evidence=self.ev(source, quote), run=run)
        r['saved_text'] = self.issue_text(issue)
        return r

    def issue_act(self, run, issue, action, params=None, source=None, quote=None, actor='claude'):
        if action not in ('start_work', 'resolve', 'reopen', 'hand_over', 'set_next_check'):
            raise mdb.Refused('an issue action is start_work, resolve, reopen, hand_over or set_next_check '
                              '(to add text: issue-append)')
        return self.do(action, actor, int(issue), params=params or {}, evidence=self.ev(source, quote), run=run)

    def issues(self, all_=False):
        sql = ("SELECT t.id, t.title, t.created_at, f.status, f.details FROM followup f JOIN thing t ON "
               "t.id=f.thing_id WHERE t.type='issue'" +
               ('' if all_ else " AND f.status IN ('reported','in_progress')") + " ORDER BY t.id")
        out = []
        for r in self.q(sql):
            d = json.loads(r['details'])
            ch = self.q("SELECT at, actor, new_value FROM audit WHERE thing_id=? AND field='followup.status' "
                        "ORDER BY id", (r['id'],))
            out.append({'id': r['id'], 'title': r['title'], 'status': r['status'], 'created': r['created_at'][:16],
                        'reported_by': d.get('reported_by'), 'context': d.get('context'),
                        'description': d.get('description'), 'additions': d.get('additions') or [],
                        'resolution': d.get('resolution'),
                        'history': [f"{x['at'][:16]} {x['actor']} -> {x['new_value']}" for x in ch]})
        return out

    def version(self):
        return {'installed': self.door.meta('marionette_version', 'unknown (before 1.7)'), 'programs': mdb.VERSION}

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
    s = sub.add_parser('issue-new')
    for k in ('--run', '--title', '--reported-by', '--context', '--source', '--quote'):
        s.add_argument(k, required=True)
    for k in ('--what-happened', '--found', '--owner-words', '--asked', '--description', '--holder'):
        s.add_argument(k)
    s.add_argument('--actor', default='claude', choices=('claude', 'user'))
    s = sub.add_parser('issue-append')
    for k in ('--run', '--issue', '--text', '--source', '--quote'):
        s.add_argument(k, required=True)
    s.add_argument('--by'); s.add_argument('--actor', default='claude', choices=('claude', 'user'))
    s = sub.add_parser('issue-act')
    for k in ('--run', '--issue', '--action'):
        s.add_argument(k, required=True)
    for k in ('--params', '--source', '--quote'):
        s.add_argument(k)
    s.add_argument('--actor', default='claude', choices=('claude', 'user'))
    s = sub.add_parser('issues'); s.add_argument('--all', action='store_true')
    s = sub.add_parser('issue'); s.add_argument('id')
    sub.add_parser('version')
    s = sub.add_parser('unreadable')
    for k in ('--run', '--source', '--reason'):
        s.add_argument(k, required=True)
    s = sub.add_parser('panel-data'); s.add_argument('--out', required=True)
    for k in ('--message', '--gate-file', '--jobs'):
        s.add_argument(k)
    s = sub.add_parser('apply-panel')
    for k in ('--run', '--file', '--out'):
        s.add_argument(k, required=True)
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
        if c == 'issue':
            print(R.issue_text(a.id)); return 0
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
            'issue-new': lambda: R.issue_new(run, a.title, a.reported_by, a.context, a.source, a.quote,
                                             a.what_happened, a.found, a.owner_words, a.asked, a.holder, a.actor,
                                             a.description),
            'issue-append': lambda: R.issue_append(run, a.issue, a.text, a.source, a.quote, a.by, a.actor),
            'issue-act': lambda: R.issue_act(run, a.issue, a.action, J(a.params), a.source, a.quote, a.actor),
            'issues': lambda: R.issues(a.all),
            'version': lambda: R.version(),
            'unreadable': lambda: R.unreadable(run, a.source, a.reason),
            'panel-data': lambda: R.write_json(a.out, R.panel_data(
                open(a.message, encoding='utf-8').read() if a.message else None, a.gate_file,
                json.load(open(a.jobs, encoding='utf-8')) if a.jobs else None)),
            'apply-panel': lambda: R.write_json(a.out, R.apply_panel(run, a.file)),
        }[c]()
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 0
    except mdb.Refused as e:
        print(json.dumps({'refused': str(e)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
