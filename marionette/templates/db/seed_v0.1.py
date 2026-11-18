"""Marionette by Hesham Elmahdy (github.com/heshamfm): starting data of the database, schema 0.1.

Holds the 4 groups, the 22 types with their statuses, and who may do each
action (the action_rule table). A job schedule is JSON, see mdb.py (parse_schedule). Everything here is generic: no channel, client
or person of any user is written in this file. The user's own name is given
when the database is created (mdb.py init).

"""
import json

GROUPS = [
    ('followup', 'أشياء المتابعة', 'Follow-up things'),
    ('reference', 'السجلات المرجعية', 'Reference records'),
    ('source', 'المصادر والأدلة', 'Sources and evidence'),
    ('memory', 'ذاكرة النظام', 'System memory'),
]

S4 = ['open', 'deferred', 'done', 'cancelled']
VERDICTS = ['linked', 'informed', 'ignored']

# code, group, Arabic name, English name, statuses, fields
# fields: "required" = keys that must be in details when the thing is created;
#         "links" = parties that must be linked at creation, by role.
TYPES = [
    ('commitment', 'followup', 'التزام', 'Commitment', S4,
     {'required': ['text'], 'links': ['promised_by'], 'optional_links': ['promised_to']}),
    ('reply_needed', 'followup', 'رد مطلوب', 'Reply needed', S4,
     {'required': ['request'], 'links': ['requested_by'], 'optional': ['channel_id', 'draft_id']}),
    ('decision_needed', 'followup', 'قرار مطلوب', 'Decision needed', S4,
     {'required': ['question'], 'optional': ['options', 'recommendation', 'decision']}),
    ('for_info', 'followup', 'للعلم', 'For information', ['new', 'seen'],
     {'required': ['what_happened', 'why_it_matters']}),
    ('reminder', 'followup', 'تذكير', 'Reminder', ['scheduled', 'shown', 'seen', 'cancelled'],
     {'required': ['text'], 'needs_due': True}),
    ('draft', 'followup', 'مسودة', 'Draft', ['ready', 'sent_as_is', 'sent_edited', 'abandoned'],
     {'required': ['text', 'channel_id', 'recipients', 'kind'], 'optional': ['replies_to', 'job_id']}),
    ('deferred_check', 'followup', 'فحص مؤجل', 'Deferred check', ['scheduled', 'executed', 'cancelled'],
     {'required': ['condition', 'if_true', 'if_false'], 'needs_next_check': True}),
    ('party', 'reference', 'طرف', 'Party', ['unconfirmed', 'confirmed', 'inactive'], {}),
    ('area', 'reference', 'مجال', 'Area', ['active', 'archived'], {}),
    ('project', 'reference', 'مشروع', 'Project', ['active', 'paused', 'ended'], {}),
    ('channel', 'reference', 'قناة', 'Channel', ['connected', 'unavailable', 'stopped'], {}),
    ('message', 'source', 'رسالة', 'Message', VERDICTS, {}),
    ('calendar_event', 'source', 'موعد تقويم', 'Calendar event', VERDICTS, {}),
    ('meeting', 'source', 'اجتماع أو مكالمة', 'Meeting or call', VERDICTS, {}),
    ('external_record', 'source', 'سجل في نظام خارجي', 'External record', VERDICTS,
     {'required': ['record_kind']}),
    ('file', 'source', 'ملف', 'File', ['kept', 'referenced', 'deleted_by_user', 'missing'], {}),
    ('published_content', 'source', 'محتوى منشور', 'Published content', VERDICTS, {}),
    ('session', 'source', 'جلسة مع Claude', 'Session with Claude', VERDICTS, {}),
    ('decision', 'memory', 'قرار مسجل', 'Recorded decision', ['in_force', 'superseded'], {}),
    ('rule', 'memory', 'قاعدة', 'Rule', ['in_force', 'paused', 'cancelled'], {}),
    ('job', 'memory', 'وظيفة دورية', 'Recurring job', ['enabled', 'paused', 'cancelled'], {}),
    ('run', 'memory', 'تشغيلة', 'Run', ['running', 'complete', 'complete_with_gaps', 'failed'], {}),
]

# Arabic names of the actions, for listing them to a human.
ACTION_AR = {
    'create': 'إنشاء', 'hand_over': 'نقل الخطوة التالية إلى طرف آخر', 'change_due': 'تغيير الموعد',
    'set_next_check': 'تغيير موعد الفحص التالي', 'defer': 'تأجيل', 'complete': 'إنجاز',
    'reopen': 'إعادة فتح', 'merge': 'دمج مع مكرر', 'cancel': 'إلغاء', 'mark_late': 'تعليم بأنه تجاوز موعده',
    'record_decision': 'تسجيل القرار', 'show': 'عرض في التقرير', 'mark_seen': 'تعليم بالاطلاع',
    'convert': 'تحويل إلى التزام أو رد أو قرار', 'edit': 'تعديل', 'send': 'إرسال',
    'mark_sent_as_is': 'رصد أنها أُرسلت كما هي', 'mark_sent_edited': 'رصد أنها أُرسلت بتعديل',
    'abandon': 'إهمال', 'execute': 'تنفيذ في موعده', 'confirm': 'تأكيد', 'link_org': 'ربط شخص بجهة',
    'change_relation': 'تغيير العلاقة بنا', 'deactivate': 'تعطيل', 'rename': 'إعادة تسمية',
    'archive': 'أرشفة', 'pause': 'إيقاف', 'end': 'إنهاء', 'assign': 'ربط بمجال أو مشروع',
    'update_watermark': 'قراءة وتحديث العلامة', 'mark_unavailable': 'تعليم غير متاحة',
    'mark_available': 'تعليم متاحة من جديد', 'stop': 'إيقاف', 'record': 'تسجيل', 'read': 'قراءة',
    'verdict': 'إصدار الحكم', 'correct_verdict': 'تصحيح الحكم', 'reset_verdict': 'إعادة الحكم إلى فارغ',
    'update_state': 'تحديث آخر حالة', 'register': 'تنزيل وتسجيل', 'mark_missing': 'رصد أنه غاب عن القرص',
    'propose_delete': 'اقتراح حذف', 'delete': 'تسجيل أن المستخدم حذفه', 'supersede': 'إلغاء بقرار لاحق',
    'edit_text': 'تعديل النص', 'resume': 'إعادة تفعيل', 'mark_period_done': 'تعليم الفترة منجزة',
    'start': 'بدء', 'close': 'إغلاق', 'link': 'ربط شيء بشيء', 'add_evidence': 'إضافة دليل',
    'confirm_values': 'تأكيد قيم وضعها Claude استنتاجًا',
}

U, C, P = 'user', 'claude', 'program'


def R(scope, action, actors, froms=(None,), to=None, evidence_for=(C,)):
    """One permission line per actor and per starting status.
    froms: statuses the action may start from; None = the thing does not exist yet (create) or any status.
    to: the status the action leads to; None = status unchanged, or decided by the program.
    evidence_for: Claude lines that must give a source and a verbatim quote.
    A user line always needs evidence: the user's own words, quoted from a session with Claude
    (because the program cannot tell who is calling it)."""
    out = []
    for a in actors:
        for f in froms:
            out.append((scope, action, a, f, to, 1 if (a in evidence_for or a == U) else 0))
    return out


OPEN = ('open', 'deferred')
ACTION_RULES = []
A = ACTION_RULES.extend

# Follow-up things, shared by the group
A(R('followup', 'create', [C, U], to='open'))
A(R('followup', 'hand_over', [C, U], OPEN))
A(R('followup', 'change_due', [C, U], OPEN))
A(R('followup', 'set_next_check', [C, U, P], OPEN, evidence_for=()))
A(R('followup', 'defer', [U], ('open',), to='deferred'))
A(R('followup', 'complete', [C, U], OPEN, to='done'))
A(R('followup', 'reopen', [C], ('done',), to='open'))
A(R('followup', 'reopen', [U], ('done', 'cancelled'), to='open'))
A(R('followup', 'merge', [C, U], OPEN, to='done'))
A(R('followup', 'cancel', [U], OPEN, to='cancelled'))
A(R('followup', 'mark_late', [P], OPEN))
A(R('followup', 'assign', [C, U], OPEN))
# Decision needed
A(R('decision_needed', 'record_decision', [C, U], OPEN, to='done'))
# For information: two statuses only
A(R('for_info', 'create', [C, U], to='new'))
A(R('for_info', 'show', [P, C], ('new',), evidence_for=()))
A(R('for_info', 'mark_seen', [U], ('new',), to='seen'))
A(R('for_info', 'convert', [U, C], ('new', 'seen')))
A(R('for_info', 'assign', [C, U], ('new',)))
# a for-information thing still new keeps its next-step holder and dates current,
# like any follow-up thing (the old files change them; without these lines the door refused)
A(R('for_info', 'hand_over', [C, U], ('new',)))
A(R('for_info', 'change_due', [C, U], ('new',)))
A(R('for_info', 'set_next_check', [C, U, P], ('new',), evidence_for=()))
# Reminder
A(R('reminder', 'create', [U, C], to='scheduled'))
A(R('reminder', 'show', [P], ('scheduled',), to='shown', evidence_for=()))
A(R('reminder', 'mark_seen', [U], ('scheduled', 'shown'), to='seen'))
A(R('reminder', 'defer', [U], ('scheduled', 'shown'), to='scheduled'))
A(R('reminder', 'cancel', [U], ('scheduled', 'shown'), to='cancelled'))
# Draft
A(R('draft', 'create', [C], to='ready', evidence_for=()))
A(R('draft', 'edit', [U, C], ('ready',)))
A(R('draft', 'send', [U, C], ('ready',), to='sent_as_is', evidence_for=()))
A(R('draft', 'mark_sent_as_is', [C, P], ('ready',), to='sent_as_is', evidence_for=()))
A(R('draft', 'mark_sent_edited', [C, P], ('ready',), to='sent_edited', evidence_for=()))
A(R('draft', 'abandon', [U, C], ('ready',), to='abandoned', evidence_for=()))
# Deferred check
A(R('deferred_check', 'create', [C, U], to='scheduled'))
A(R('deferred_check', 'execute', [C, P], ('scheduled',), to='executed', evidence_for=()))
A(R('deferred_check', 'cancel', [U, C], ('scheduled',), to='cancelled', evidence_for=()))

# Party
A(R('party', 'create', [C, U], to='unconfirmed'))
A(R('party', 'confirm', [C, U], ('unconfirmed',), to='confirmed'))
A(R('party', 'edit', [C, U], ('unconfirmed', 'confirmed')))
A(R('party', 'link_org', [C, U], ('unconfirmed', 'confirmed')))
A(R('party', 'change_relation', [U], ('unconfirmed', 'confirmed')))
A(R('party', 'merge', [C, U], ('unconfirmed', 'confirmed'), to='inactive'))
A(R('party', 'deactivate', [U], ('unconfirmed', 'confirmed'), to='inactive'))
# Area
A(R('area', 'create', [U], to='active'))
A(R('area', 'rename', [U], ('active',)))
A(R('area', 'archive', [U], ('active',), to='archived'))
# Project
A(R('project', 'create', [U], to='active'))
A(R('project', 'pause', [U], ('active',), to='paused'))
A(R('project', 'end', [U], ('active', 'paused'), to='ended'))
# Channel
A(R('channel', 'create', [U], to='connected'))
A(R('channel', 'update_watermark', [C, P], ('connected',), evidence_for=()))
A(R('channel', 'mark_unavailable', [P], ('connected',), to='unavailable'))
A(R('channel', 'mark_available', [P], ('unavailable',), to='connected'))
A(R('channel', 'stop', [U], ('connected', 'unavailable'), to='stopped'))

# Sources (status of a source = its reading verdict; "none" = no verdict yet)
A(R('source', 'record', [C, P], to='none', evidence_for=()))
A(R('source', 'read', [C], ('none',), evidence_for=()))
A(R('source', 'verdict', [C], ('none',), evidence_for=()))
A(R('source', 'correct_verdict', [C, U], ('linked', 'informed', 'ignored')))
A(R('source', 'reset_verdict', [P], ('ignored',), to='none', evidence_for=()))
A(R('source', 'assign', [C, U], ('none', 'linked', 'informed', 'ignored')))
A(R('external_record', 'update_state', [C, P], ('none', 'linked', 'informed', 'ignored'), evidence_for=()))
# File (its own statuses)
A(R('file', 'register', [P]))
A(R('file', 'mark_missing', [P], ('kept',), to='missing'))
A(R('file', 'propose_delete', [P], ('kept',)))
A(R('file', 'delete', [U], ('kept', 'missing'), to='deleted_by_user'))

# Recorded decision
A(R('decision', 'create', [C], to='in_force'))
A(R('decision', 'supersede', [U], ('in_force',), to='superseded'))
# Rule
A(R('rule', 'create', [C, U], to='in_force', evidence_for=()))
A(R('rule', 'edit_text', [U], ('in_force', 'paused')))
A(R('rule', 'pause', [U], ('in_force',), to='paused'))
A(R('rule', 'resume', [U], ('paused',), to='in_force'))
A(R('rule', 'cancel', [U], ('in_force', 'paused'), to='cancelled'))
# Recurring job
A(R('job', 'create', [U], to='enabled'))
A(R('job', 'edit', [U], ('enabled', 'paused')))
A(R('job', 'execute', [C], ('enabled',), evidence_for=()))
A(R('job', 'mark_period_done', [P], ('enabled',)))
A(R('job', 'pause', [U], ('enabled',), to='paused'))
A(R('job', 'resume', [U], ('paused',), to='enabled'))
A(R('job', 'cancel', [U], ('enabled', 'paused'), to='cancelled'))
# Run
A(R('run', 'start', [P], to='running'))
A(R('run', 'close', [P], ('running',)))
# a run records each enabled channel it did not read, with a reason from a closed list
A(R('run', 'note_skip', [C, P], ('running',), evidence_for=()))

# Values Claude set by inference stay marked until confirmed
A(R('followup', 'confirm_values', [C, U]))
A(R('source', 'confirm_values', [C, U]))
# Any thing
A(R('*', 'link', [C, U]))
A(R('*', 'add_evidence', [C, U]))


def seed(conn):
    conn.executemany('INSERT INTO grp(code,name_ar,name_en) VALUES(?,?,?)', GROUPS)
    for code, g, ar, en, st, fields in TYPES:
        conn.execute('INSERT INTO type(code,grp,name_ar,name_en,statuses,fields) VALUES(?,?,?,?,?,?)',
                     (code, g, ar, en, json.dumps(st), json.dumps(fields, ensure_ascii=False)))
    conn.executemany('INSERT INTO action_rule(scope,action,actor,from_status,to_status,needs_evidence) '
                     'VALUES(?,?,?,?,?,?)', ACTION_RULES)
