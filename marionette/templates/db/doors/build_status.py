"""Marionette by Hesham Elmahdy (github.com/heshamfm): the status page, in an installation that keeps its memory in
the database. A door to python3 tools/mrun.py status.
Usage: python3 tools/build_status.py [--out view/status.md] --live-check "<time and result of the live check>" """
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--out', default=os.path.join(os.path.dirname(HERE), 'view', 'status.md'))
ap.add_argument('--live-check', default='-')
a, _ = ap.parse_known_args()
notes = os.path.join(os.path.dirname(HERE), 'view', 'run_notes.md')
args = [sys.executable, os.path.join(HERE, 'mrun.py'), 'status', '--out', a.out, '--live-check', a.live_check]
if os.path.exists(notes):
    args += ['--notes', notes]
sys.exit(subprocess.call(args))
