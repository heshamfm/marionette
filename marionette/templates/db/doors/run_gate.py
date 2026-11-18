"""Marionette by Hesham Elmahdy (github.com/heshamfm): the end-of-run check, in an installation that keeps its
memory in the database. A door to python3 tools/mrun.py gate --run <run number>.
Given --start "YYYY-MM-DD HH:MM", it finds the run that started then (or the run still working) and checks it.
Exit code 1 when an enabled channel was left without an accepted reason or something read is not classified."""
import argparse
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mrun  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--start')
ap.add_argument('--run', type=int)
a = ap.parse_args()
run = a.run
if run is None:
    c = sqlite3.connect('file:' + mrun.default_db() + '?mode=ro', uri=True)
    r = None
    if a.start:
        r = c.execute("SELECT thing_id FROM run WHERE substr(started,1,16)=? ORDER BY thing_id DESC LIMIT 1",
                      (a.start.strip()[:16],)).fetchone()
    if not r:
        r = c.execute("SELECT thing_id FROM run WHERE status='running' ORDER BY thing_id DESC LIMIT 1").fetchone()
    if not r:
        print('End-of-run check: no run started at that time and no run is working now. '
              'Start each run with: python3 tools/mrun.py run-start')
        sys.exit(1)
    run = r[0]
sys.exit(subprocess.call([sys.executable, os.path.join(HERE, 'mrun.py'), 'gate', '--run', str(run)]))
