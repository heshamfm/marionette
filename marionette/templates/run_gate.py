#!/usr/bin/env python3
"""Marionette end-of-run check. Read-only.

Usage, from the followup folder:  python3 tools/run_gate.py --start "YYYY-MM-DD HH:MM"
(--start is the local time the run started, as written in state.json.)

It answers one question the run cannot be trusted to answer about itself: which enabled channels
were NOT read in this run, and was there a real reason? A channel counts as read when its
watermark in state.json is at or after the run start. For every other enabled channel the run
must have written a line in view/run_skips.tsv:

    <run start> <TAB> <channel> <TAB> <reason code> <TAB> <one plain sentence>

Reason codes accepted: tool_absent, page_failed, permission_refused, not_due, partly_read.
Anything else, or no line at all, is printed as a VIOLATION and the exit code is 1.
It also reports decisions marked as rules that do not name the file that carries them
(a decision whose text starts with "RULE:" must contain "file: <name>").
The run copies this script's output, word for word, to the top of its message to the owner."""
import os, re, sys, json, argparse

VALID = {
    'tool_absent': 'the tool was not available',
    'page_failed': 'the page would not load',
    'permission_refused': 'permission was refused',
    'not_due': 'not due yet',
    'partly_read': 'partly read',
}


def check(root, start):
    rd = lambda *p: open(os.path.join(root, *p), encoding='utf-8').read()
    start = start.strip()[:16]
    wm = json.loads(rd('state.json')).get('watermarks', {})
    enabled = [m.group(1) for m in re.finditer(r'(?m)^## (\S+)[ \t]*\nstatus:[ \t]*(\S+)', rd('channels.md'))
               if m.group(2).lower().startswith('enabled')]
    skips = {}
    sp = os.path.join(root, 'view', 'run_skips.tsv')
    if os.path.exists(sp):
        for line in open(sp, encoding='utf-8').read().splitlines():
            c = line.split('\t')
            if len(c) >= 3 and c[0].strip()[:16] == start:
                skips[c[1].strip()] = (c[2].strip(), c[3].strip() if len(c) > 3 else '')
    read, bad, noted = 0, [], []
    for ch in enabled:
        w = (wm.get(ch) or '')[:16]
        if w and w >= start:
            read += 1
            continue
        code, why = skips.get(ch, ('', ''))
        last = w or 'never'
        if code in VALID:
            noted.append(f'NOTE: channel {ch} was not read: {VALID[code]}. {why} (last read: {last})')
        elif code or why:
            given = f'{code} {why}'.strip()
            bad.append(f'VIOLATION: channel {ch} was left unread and the reason given ("{given}") '
                       f'is not an accepted one. Last read: {last}.')
        else:
            bad.append(f'VIOLATION: channel {ch} was left unread and no reason was written. Last read: {last}.')
    other = []
    dp = os.path.join(root, 'decisions.md')
    if os.path.exists(dp):
        for line in open(dp, encoding='utf-8').read().splitlines():
            m = re.match(r'- (D\d+) \| [\d-]+ \| *RULE:', line)
            if m and 'file:' not in line:
                other.append(f'MISSING: rule decision {m.group(1)} does not name the file that carries it.')
    out = [f'End-of-run check ({start}): {read} of {len(enabled)} enabled channels were read.'] + bad + noted + other
    if not (bad or noted or other):
        out.append('Every enabled channel was read, and nothing is missing.')
    return out, (1 if bad else 0)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Marionette end-of-run check')
    ap.add_argument('--start', required=True, help='local time the run started, YYYY-MM-DD HH:MM')
    ap.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    lines, code = check(a.root, a.start)
    print('\n'.join(lines))
    sys.exit(code)
