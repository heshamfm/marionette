"""Tests for the late rule in marionette/templates/brief.py. Run: python3 tests/test_brief.py"""
import os, json, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BRIEF = os.path.join(HERE, '..', 'marionette', 'templates', 'brief.py')
SUN_THU = [6, 0, 1, 2, 3]  # Sunday to Thursday


def run(now, rows, items, days=SUN_THU):
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, 'tools')); os.makedirs(os.path.join(d, 'items'))
        shutil.copy(BRIEF, os.path.join(d, 'tools', 'brief.py'))
        json.dump({'mode': 'live', 'owner': {'timezone': 'Africa/Cairo', 'working_days': days},
                   'lock': {'holder': None, 'since': None}, 'watermarks': {}, 'jobs': {}},
                  open(os.path.join(d, 'state.json'), 'w'))
        head = 'key\tstatus\ttype\tdeadline\trecord\tcounterparty\ttitle\tlast_event\n'
        body = ''.join('%s\topen\treply_needed\t%s\t\tX\tT\t\n' % (k, dl) for k, dl in rows)
        open(os.path.join(d, 'index.tsv'), 'w').write(head + body)
        for k, ts in items.items():
            open(os.path.join(d, 'items', k + '.md'), 'w').write('# %s\n\n## Story\n- %s | opened\n' % (k, ts))
        out = subprocess.run([sys.executable, os.path.join(d, 'tools', 'brief.py')], capture_output=True, text=True,
                             env=dict(os.environ, MARIONETTE_NOW=now), check=True).stdout
        return {k: ('LATE' in next(l for l in out.splitlines() if l.startswith('- ' + k + ' '))) for k, _ in rows}
    finally:
        shutil.rmtree(d)


CASES = [
    # (description, now, [(key, deadline)], {key: first seen}, expected late per key)
    ('seen late on a working evening, next morning', '2026-11-11 09:00', [('a', '')], {'a': '2026-11-10 23:50'}, {'a': False}),
    ('seen late on a working evening, after a full working day', '2026-11-12 00:10', [('a', '')], {'a': '2026-11-10 23:50'}, {'a': True}),
    ('seen Thursday morning, weekend in between, Sunday 09:00', '2026-11-15 09:00', [('a', '')], {'a': '2026-11-12 10:00'}, {'a': False}),
    ('seen Thursday morning, weekend in between, Sunday 10:30', '2026-11-15 10:30', [('a', '')], {'a': '2026-11-12 10:00'}, {'a': True}),
    ('deadline today with a past time', '2026-11-11 09:00', [('b', '2026-11-11 03:00')], {'b': '2026-11-11 08:00'}, {'b': True}),
    ('deadline today with a future time', '2026-11-11 09:00', [('b', '2026-11-11 15:00')], {'b': '2026-11-11 08:00'}, {'b': False}),
    ('deadline today as a date, still today', '2026-11-11 09:00', [('c', '2026-11-11')], {'c': '2026-11-11 08:00'}, {'c': False}),
    ('deadline yesterday as a date', '2026-11-11 09:00', [('c', '2026-11-10')], {'c': '2026-11-09 08:00'}, {'c': True}),
]

if __name__ == '__main__':
    failed = 0
    for desc, now, rows, items, want in CASES:
        got = run(now, rows, items)
        ok = got == want
        failed += not ok
        print(('PASS ' if ok else 'FAIL ') + desc + ('' if ok else ': expected %s, got %s' % (want, got)))
    print('%d of %d passed' % (len(CASES) - failed, len(CASES)))
    sys.exit(1 if failed else 0)
