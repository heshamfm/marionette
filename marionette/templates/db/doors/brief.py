"""Marionette by Hesham Elmahdy (github.com/heshamfm): the run brief, in an installation that keeps its memory in
the database. A door to python3 tools/mrun.py brief, which reads the database.
Usage: python3 tools/brief.py [--full-questions]"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call([sys.executable, os.path.join(HERE, 'mrun.py'), 'brief'] + sys.argv[1:]))
