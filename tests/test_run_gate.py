"""Tests for marionette/templates/run_gate.py. Run: python3 tests/test_run_gate.py"""
import os, json, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'marionette', 'templates'))
import run_gate

CHANNELS = '# Channels\n\n## mail\nstatus: enabled\nhow: x\n\n## spam\nstatus: enabled\nhow: x\n\n' \
           '## chat\nstatus: enabled (tested)\nhow: x\n\n## portal\nstatus: enabled\nhow: weekly\n\n' \
           '## calls\nstatus: disabled\nhow: x\n'
START = '2026-11-10 19:19'


def make(watermarks, skips='', decisions='# Decisions\n'):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'view'))
    open(os.path.join(d, 'channels.md'), 'w').write(CHANNELS)
    json.dump({'watermarks': watermarks}, open(os.path.join(d, 'state.json'), 'w'))
    open(os.path.join(d, 'view', 'run_skips.tsv'), 'w').write(skips)
    open(os.path.join(d, 'decisions.md'), 'w').write(decisions)
    return d


def test_all_read():
    d = make({'mail': '2026-11-10 20:30', 'spam': '2026-11-10 20:31', 'chat': START, 'portal': '2026-11-10 20:00'})
    out, code = run_gate.check(d, START)
    assert code == 0 and out[0].endswith('4 of 4 enabled channels were read.') and 'nothing is missing' in out[-1], out


def test_skips_and_violations():
    skips = (f'{START}\tspam\tpage_failed\tthe page stayed on Loading twice\n'
             f'{START}\tchat\tmy_choice\tto keep the run short\n'
             f'2026-11-09 10:00\tportal\tnot_due\told line from another run\n')
    d = make({'mail': '2026-11-10 20:30', 'spam': '2026-11-09 14:18', 'chat': '2026-11-09 14:20', 'portal': None},
             skips)
    out, code = run_gate.check(d, START)
    text = '\n'.join(out)
    assert code == 1, out
    assert '1 of 4 enabled channels were read' in out[0], out
    assert 'NOTE: channel spam was not read: the page would not load' in text, out
    assert 'VIOLATION: channel chat' in text and 'not an accepted one' in text, out
    assert 'VIOLATION: channel portal was left unread and no reason was written. Last read: never.' in text, out
    assert 'calls' not in text, out


def test_rule_decision_must_name_file():
    dec = ('# Decisions\n- D1 | 2026-11-01 | Marionette set up | owner\n'
           '- D2 | 2026-11-08 | RULE: never skip a channel to save time | owner, session\n'
           '- D3 | 2026-11-08 | RULE: write to Dana in English; file: rules_by_subject.md | owner, session\n')
    d = make({'mail': START, 'spam': START, 'chat': START, 'portal': START}, decisions=dec)
    out, code = run_gate.check(d, START)
    assert code == 0 and any('rule decision D2' in l for l in out) and not any('D3' in l for l in out), out


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn(); print('ok', name)
