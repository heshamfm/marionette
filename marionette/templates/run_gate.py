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
It also reads data/disposition.tsv, when it exists: every line with an empty disposition is listed under
"Read and not classified", every invalid disposition is a VIOLATION, and open items with no deadline and no
next_check date are counted and the oldest are named.
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
    unclassified, undated = dispositions(root, bad)
    out = [f'End-of-run check ({start}): {read} of {len(enabled)} enabled channels were read.'] + bad + noted + other
    if unclassified:
        out.append(f'Read and not classified ({len(unclassified)}):')
        out += ['- ' + u for u in unclassified[:40]]
        if len(unclassified) > 40:
            out.append(f'- and {len(unclassified) - 40} more in data/disposition.tsv.')
    if undated:
        out.append(f'Open items with no deadline and no next_check date ({len(undated)}). Oldest:')
        out += ['- ' + u for u in undated[:10]]
    if not (bad or noted or other or unclassified or undated):
        out.append('Every enabled channel was read, everything read is classified, and nothing is missing.')
    return out, (1 if (bad or unclassified) else 0)


CODES = ('marketing', 'job_application', 'no_action_notice', 'duplicate:', 'rule:')
CLOSED = ('done', 'dropped', 'closed')


def dispositions(root, bad):
    """Return (unclassified lines, undated open items); append invalid dispositions to bad."""
    keys, open_rows = set(), []
    for rel in ('index.tsv', os.path.join('archive', 'index_archive.tsv')):
        fp = os.path.join(root, rel)
        if not os.path.exists(fp):
            continue
        for line in open(fp, encoding='utf-8').read().splitlines()[1:]:
            c = line.split('\t')
            if not c or not c[0]:
                continue
            keys.add(c[0])
            if rel == 'index.tsv' and len(c) > 6 and c[1].strip().lower() not in CLOSED:
                open_rows.append(c)
    unclassified = []
    reg = os.path.join(root, 'data', 'disposition.tsv')
    if os.path.exists(reg):
        for line in open(reg, encoding='utf-8').read().splitlines()[1:]:
            c = [x.strip() for x in (line.split('\t') + [''] * 8)[:8]]
            sid, date, sender, subj, disp, kr = c[1], c[2], c[3], c[4], c[5], c[6]
            if not sid:
                continue
            who = f'{sender}, "{subj}" ({date[:10]})'
            if not disp:
                unclassified.append(who)
            elif disp == 'linked':
                if kr not in keys:
                    bad.append(f'VIOLATION: {who} is linked to an item that does not exist ("{kr}").')
            elif disp == 'ignored':
                if not kr.startswith(CODES):
                    bad.append(f'VIOLATION: {who} is ignored for a reason outside the closed list ("{kr}").')
            else:
                bad.append(f'VIOLATION: {who} has an unknown disposition ("{disp}").')
    undated = []
    for c in open_rows:
        if re.match(r'\d{4}-\d\d-\d\d', c[3] or ''):
            continue
        ip = os.path.join(root, 'items', c[0] + '.md')
        head = open(ip, encoding='utf-8').read().split('## ')[0] if os.path.exists(ip) else ''
        if re.search(r'(?m)^next_check: *\d{4}-\d\d-\d\d', head):
            continue
        undated.append(f'{c[6]} (last event {(c[7] if len(c) > 7 else "")[:10]})')
    undated.sort(key=lambda u: u[-11:])
    return unclassified, undated


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Marionette end-of-run check')
    ap.add_argument('--start', required=True, help='local time the run started, YYYY-MM-DD HH:MM')
    ap.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    lines, code = check(a.root, a.start)
    print('\n'.join(lines))
    sys.exit(code)
