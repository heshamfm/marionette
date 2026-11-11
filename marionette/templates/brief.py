"""Marionette run brief. Read-only. Usage, from the followup folder: python3 tools/brief.py"""
import os, re, json, glob, datetime as dt
from zoneinfo import ZoneInfo
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rd(*a):
    with open(os.path.join(R, *a), encoding='utf-8') as f:
        return f.read()
st = json.loads(rd('state.json')); ow = st.get('owner', {}); lb = st.get('labels', {})
now = dt.datetime.now(ZoneInfo(ow.get('timezone') or 'UTC')).replace(tzinfo=None)
if os.environ.get('MARIONETTE_NOW'):  # for tests only: fixed local time "YYYY-MM-DD HH:MM"
    now = dt.datetime.strptime(os.environ['MARIONETTE_NOW'], '%Y-%m-%d %H:%M')
today = now.date().isoformat(); stamp = now.strftime('%Y-%m-%d %H:%M')
WD = set(ow.get('working_days', [0, 1, 2, 3, 4]))
OPEN = lb.get('open', 'open'); CLOSED = set(lb.get('closed', ['done', 'closed_no_action']))
def tsv(name):
    if not os.path.exists(os.path.join(R, name)):
        return []
    L = [l for l in rd(name).splitlines() if l.strip()]
    if not L:
        return []
    h = L[0].split('\t')
    return [dict(zip(h, (l.split('\t') + [''] * len(h))[:len(h)])) for l in L[1:]]
def parse_when(v):
    """"YYYY-MM-DD HH:MM" is that minute; "YYYY-MM-DD" alone means the end of that day. None if neither."""
    v = (v or '').strip()
    try:
        return dt.datetime.strptime(v[:16], '%Y-%m-%d %H:%M')
    except ValueError:
        pass
    try:
        return dt.datetime.strptime(v[:10], '%Y-%m-%d') + dt.timedelta(days=1)
    except ValueError:
        return None
def working_hours_since(t0):
    """Hours between t0 and now that fall on working days."""
    h, t = 0.0, t0
    while t < now:
        nxt = min(dt.datetime.combine(t.date() + dt.timedelta(days=1), dt.time()), now)
        if t.weekday() in WD:
            h += (nxt - t).total_seconds() / 3600
        t = nxt
    return h
def first_seen(r):
    fn = os.path.join(R, 'items', r['key'] + '.md')
    ts = re.findall(r'(?m)^- (\d{4}-\d\d-\d\d \d\d:\d\d) \|', rd('items', r['key'] + '.md')) if os.path.exists(fn) else []
    if ts:
        return min(ts)
    le = (r.get('last_event') or '')[:16]
    return le if parse_when(le) else stamp
def late(r):
    d = parse_when(r.get('deadline'))
    if d and d <= now:
        return 'deadline passed ' + r['deadline']
    if r.get('status') == OPEN and not r.get('deadline'):
        f = first_seen(r); t0 = parse_when(f)
        if len(f) == 10 and t0:
            t0 -= dt.timedelta(days=1)  # a date alone: count from the start of that day
        if t0 and working_hours_since(t0) >= 24:
            return 'not addressed since ' + f
    return ''
print('# Marionette brief ' + stamp + ' | mode=' + str(st.get('mode')) + ' | lock=' + str(st.get('lock')))
print('watermarks: ' + '; '.join(k + '=' + str(v) for k, v in st.get('watermarks', {}).items()))
print('last_audit=' + str(st.get('last_audit')) + ' | jobs: ' + ('; '.join(k + '=' + str(v.get('last_period')) for k, v in st.get('jobs', {}).items()) or 'none'))
rows = tsv('index.tsv'); op = [r for r in rows if r.get('status') not in CLOSED]
op.sort(key=lambda r: (late(r) == '', r.get('deadline') or '9999', r.get('last_event') or ''))
print('\n## Open items (%d of %d)' % (len(op), len(rows)))
for r in op:
    l = late(r)
    print('- ' + ' | '.join([r['key'], r.get('status', ''), r.get('type', ''), 'due ' + (r.get('deadline') or '-')] + (['LATE: ' + l] if l else []) + [r.get('counterparty', ''), r.get('title', ''), 'last ' + r.get('last_event', '')]))
print('count: open %d, late %d, closed %d' % (len(op), sum(1 for r in op if late(r)), len(rows) - len(op)))
dr = [r for r in tsv('drafts.tsv') if r.get('status') in ('waiting', 'scheduled')]
print('\n## Drafts waiting (%d)' % len(dr))
for r in dr:
    print('- ' + ' | '.join([r.get('draft_id', ''), 'item ' + r.get('item_key', ''), 'created ' + r.get('created', ''), r.get('note', '')]))
q = rd('questions.md') if os.path.exists(os.path.join(R, 'questions.md')) else ''
m = re.search(r'(?m)^' + re.escape(lb.get('answered_heading', '## Answered')), q)
oq = [l for l in (q[:m.start()] if m else q).splitlines() if re.match(r'^- \d{4}-\d\d-\d\d', l)]
print('\n## Open questions (%d)' % len(oq))
for l in oq:
    print(l[:300])
rem = []
for fn in sorted(glob.glob(os.path.join(R, 'reminders', '*.md'))):
    t = open(fn, encoding='utf-8').read()
    d = re.search(r'(?m)^due: ?(.*)$', t); v = re.search(r'(?m)^delivered: ?(.*)$', t)
    if v and v.group(1).strip():
        continue
    due = d.group(1).strip() if d else ''
    flag = 'NO DATE: show in every full status' if due.lower() in ('', 'none') else ('DUE NOW' if due[:16] <= stamp else 'later')
    rem.append('- ' + os.path.basename(fn) + ' | due ' + (due or '-') + ' | ' + flag)
print('\n## Reminders not delivered (%d)' % len(rem))
print('\n'.join(rem))
