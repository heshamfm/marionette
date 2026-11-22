#!/usr/bin/env python3
"""Marionette by Hesham Elmahdy (github.com/heshamfm): bring an installation on the database up to this release.

An installation keeps copies of the programs in F/tools/ and its memory in F/db/marionette.db. A new release fixes
defects in both: the programs, and sometimes data the old programs left wrong. This program brings an installation
up to the release it ships with, without losing anything and without overwriting anything the owner changed:

  --check   says what would change, file by file and in the data, and changes nothing;
  --apply   takes a full copy first (database and programs) into F/archive/upgrade_<from>_to_<to>_<time>/, then:
            replaces every program file that is exactly a published copy (never one the owner changed: the new
            version is put beside it as <name>.new-<version> and named in the report), brings the permission and
            type tables up to the new seed (adds, never removes or changes), applies the data fixes of each release
            in order, and records the release in the database (meta "marionette_version"), state.json and runs.log;
  --undo    puts the database and the programs back from the latest copy; the database as it was is moved aside,
            never deleted, and the report says how many changes were recorded after the upgrade.

It refuses while a run is writing (the lock), and never deletes a file: the folder may forbid it.
Run from the followup folder (F) with the copy that came with the skill:
    python3 tools/db_install/upgrade.py --followup . --check
    python3 tools/db_install/upgrade.py --followup . --apply
    python3 tools/db_install/upgrade.py --followup . --undo
Output is JSON. Exit code 0 when done or nothing to do, 2 when refused.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mdb  # noqa: E402  (the NEW door, from the skill's folder)

PROGRAMS = ('mdb.py', 'mrun.py', 'schema_v0.1.sql', 'seed_v0.1.py', 'migrate.py', 'upgrade.py')
DOORS = ('brief.py', 'run_gate.py', 'build_status.py')
GUIDE = ('db_usage.md',)
MANIFEST = '.marionette_manifest.json'
LOCK_MINUTES = 30

# sha256 of every program file as published, by release, so an untouched copy can be told from one the owner changed
PUBLISHED = {
    '1.5': {
        'mdb.py': '07a6fa19823e07758138f309bb2f963bc41cd5932bd87a2281b1477f41911578',
        'mrun.py': 'b05b289eb4b21a66adc9658bd6a4662dbc370653baea4e693bcb45cb3da6bf07',
        'schema_v0.1.sql': '467ac65fec46daad9918301652fec374d34173d9440b660c3921492cf01d4ec0',
        'seed_v0.1.py': '6c6711bc255d6f14ddbb53da722a2bf4b0d0591d9f254d03fecdeb6335ceb9d5',
        'migrate.py': 'bc7297a72d96495da8370ff4c2743485648647c6ae55b473414f8da6437381d8',
        'db_usage.md': '33ca2a1a2e0e3bf99ea02026334adc4e2f88cccbba36a5ece6eb45056f3dbdac',
        'brief.py': 'adfa4519e75e39babd15a4c1c7dc3224deec8ca042437af8d61ae5d95feefa2d',
        'run_gate.py': '1c1710fd6f57778e6e1e62571685d4e927d7951863ace32accaead84a797947a',
        'build_status.py': '09bd0fcc3146cc214d7290881af38242436e2e33abcf937bcc6887a00a23d93f',
    },
}
PUBLISHED['1.6'] = dict(PUBLISHED['1.5'], **{
    'mrun.py': '1e1efac985744ef70b681083c0b9a6e5f6efef904d6e7e0a6807d393e4d31473'})
RELEASES = ('1.5', '1.6', '1.7')   # in order; the data fixes of each release after the installed one are applied


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


CORE = ('mdb.py', 'mrun.py', 'seed_v0.1.py', 'schema_v0.1.sql')   # one set: never mixed across releases


def source_of(name):
    # in the skill's folder (or tools/db_install/) the doors sit in doors/; in an installed tools/ beside the rest
    d = os.path.join(HERE, 'doors', name)
    return d if name in DOORS and os.path.exists(d) else os.path.join(HERE, name)


def now_text(tz):
    return mdb.local_now(tz)[:16]


class Upgrade:
    def __init__(self, followup):
        self.F = os.path.abspath(followup)
        self.tools = os.path.join(self.F, 'tools')
        self.db = os.path.join(self.F, 'db', 'marionette.db')
        if not os.path.exists(os.path.join(self.tools, 'db_usage.md')) or not os.path.exists(self.db):
            raise mdb.Refused('this installation keeps its memory in files; move it to the database first '
                              '(the skill, "Moving an installation to the database")')
        c = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
        c.row_factory = sqlite3.Row
        meta = {r['key']: r['value'] for r in c.execute('SELECT key, value FROM meta')}
        self.tz = meta.get('timezone', 'UTC')
        self.installed = meta.get('marionette_version') or self.guess_version()
        self.target = mdb.VERSION
        self.conn_ro = c

    def guess_version(self):
        """Before 1.7 the release was not recorded in the database. The installed run-time layer tells it best (a
        skill update may have replaced it after the move); else state.json, which records the release of the move."""
        p = os.path.join(self.tools, 'mrun.py')
        if os.path.exists(p):
            h = sha(p)
            for v in reversed(RELEASES):
                if PUBLISHED.get(v, {}).get('mrun.py') == h:
                    return v
        try:
            st = json.load(open(os.path.join(self.F, 'state.json'), encoding='utf-8'))
            v = (st.get('memory') or {}).get('version')
            if v:
                return v
        except (OSError, ValueError):
            pass
        return '1.5'

    # ---------------------------------------------------------------- the plan
    def known_hashes(self, name):
        hs = {v[name] for v in PUBLISHED.values() if name in v}
        man = os.path.join(self.tools, MANIFEST)
        if os.path.exists(man):
            try:
                hs.add(json.load(open(man, encoding='utf-8'))['files'][name])
            except (KeyError, ValueError):
                pass
        return hs

    def plan_files(self):
        out = []
        for name in PROGRAMS + DOORS + GUIDE:
            src = source_of(name)
            dst = os.path.join(self.tools, name)
            new = sha(src)
            if not os.path.exists(dst):
                out.append({'file': name, 'action': 'install'})
            elif sha(dst) == new:
                out.append({'file': name, 'action': 'current'})
            elif sha(dst) in self.known_hashes(name):
                out.append({'file': name, 'action': 'replace'})
            else:
                out.append({'file': name, 'action': 'keep_changed',
                            'why': 'this copy differs from every published version: the owner or a session changed '
                                   f'it; the new version is put beside it as {name}.new-{self.target} to compare'})
        return out

    def lock(self, own_run=None):
        """A run that is writing holds the upgrade back, except the run of the session or task doing it."""
        for r in self.conn_ro.execute("SELECT t.id, r.started FROM run r JOIN thing t ON t.id=r.thing_id "
                                      "WHERE r.status='running'"):
            if own_run is not None and r['id'] == int(own_run):
                continue
            last = self.conn_ro.execute('SELECT max(at) FROM audit WHERE run_id=? OR thing_id=?',
                                        (r['id'], r['id'])).fetchone()[0] or r['started']
            age = (mdb.Door.as_time(mdb.local_now(self.tz)) - mdb.Door.as_time(last)).total_seconds() / 60
            if age < LOCK_MINUTES:
                return f'run {r["id"]} is writing (started {r["started"][:16]}); wait until it ends'
        return None

    def data_plan(self):
        """What the data steps would change, counted without changing anything."""
        c = self.conn_ro
        seed = mdb.load_seed()
        types = {r[0] for r in c.execute('SELECT code FROM type')}
        rules = {tuple(r) for r in c.execute('SELECT scope, action, actor, from_status FROM action_rule')}
        new_types = [t[0] for t in seed.TYPES if t[0] not in types]
        new_rules = {(r[0], r[1], r[2], r[3]) for r in seed.ACTION_RULES} - rules
        undated = self.undated(c)
        return {'types_added': new_types, 'permission_lines_added': len(new_rules),
                'open_items_given_a_next_check': len(undated) if self.before('1.7') else 0}

    def before(self, release):
        return RELEASES.index(self.installed) < RELEASES.index(release) if self.installed in RELEASES else True

    @staticmethod
    def undated(c):
        out = []
        for r in c.execute("SELECT t.id, t.type, f.details FROM followup f JOIN thing t ON t.id=f.thing_id WHERE "
                           "t.type IN ('commitment','reply_needed','decision_needed','for_info') AND f.status IN "
                           "('open','deferred','new') AND f.due IS NULL AND f.next_check IS NULL"):
            d = json.loads(r['details'] or '{}')
            if not (r['type'] == 'decision_needed' and (d.get('old_question') or d.get('kind') == 'question')):
                out.append(r['id'])
        return out

    def check(self):
        files = self.plan_files()
        todo = [f for f in files if f['action'] != 'current']
        return {'installed': self.installed, 'this_release': self.target,
                'up_to_date': self.installed == self.target and not [f for f in todo if f['action'] != 'keep_changed'],
                'lock': self.lock(), 'files': files, 'data': self.data_plan(),
                'rules_to_propose': self.rule_notes()}

    def rule_notes(self):
        """Rule texts a release adds to the owner's manual (upgrades/<release>.md beside this program). The manual is
        the owner's: they are proposed, never written by this program; the skill shows them and adds what the owner
        approves."""
        out = []
        for v in RELEASES:
            if self.installed in RELEASES and RELEASES.index(v) <= RELEASES.index(self.installed):
                continue
            p = os.path.join(HERE, 'upgrades', f'{v}.md')
            if os.path.exists(p):
                out.append(p)
        return out

    # ---------------------------------------------------------------- apply
    def copies(self):
        """Upgrade copies, newest first, by the time each one recorded (never by folder name: 1.10 sorts before 1.9)."""
        out = []
        for d in glob.glob(os.path.join(self.F, 'archive', 'upgrade_*_to_*')):
            p = os.path.join(d, 'upgrade.json')
            if os.path.exists(p):
                info = json.load(open(p, encoding='utf-8'))
                out.append((info.get('started_at', ''), d, info))
        return [(d, info) for _, d, info in sorted(out, key=lambda x: x[0], reverse=True)]

    def unfinished(self):
        for d, info in self.copies():
            if info.get('state') == 'started' and not info.get('undone'):
                return d
        return None

    def apply(self, approval=None, own_run=None):
        why = self.lock(own_run)
        if why:
            raise mdb.Refused(why)
        half = self.unfinished()
        if half:
            raise mdb.Refused(f'an earlier upgrade stopped half way ({os.path.relpath(half, self.F)}); run --undo '
                              'first, which puts back the copy taken before it, then upgrade again')
        plan = self.check()
        changed_core = [f['file'] for f in plan['files'] if f['action'] == 'keep_changed' and f['file'] in CORE]
        if changed_core:
            raise mdb.Refused('these programs were changed in this installation: ' + ', '.join(changed_core) +
                              '. They work only together with the other programs of the same release, so nothing '
                              'was changed. The owner decides: keep this release, or replace them (their changes '
                              f'are then lost unless carried into the new version, beside each as <name>.new-{self.target} '
                              'after copying it there from the skill).')
        if plan['up_to_date'] and not plan['data']['types_added'] and not plan['data']['permission_lines_added']:
            return {'applied': False, 'why': f'already on {self.target}', **plan}
        base = os.path.join(self.F, 'archive', f'upgrade_{self.installed}_to_{self.target}_'
                                               f'{re.sub(r"[^0-9]", "", mdb.local_now(self.tz))}')
        where, n = base, 1
        while os.path.exists(where):
            n += 1
            where = f'{base}_{n}'
        os.makedirs(os.path.join(where, 'tools'))
        os.makedirs(os.path.join(where, 'db'))
        # 1. a full copy first: the database through SQLite's backup into a temporary file (a mounted folder may
        #    refuse SQLite's own writes there), then copied; the programs as they are
        try:
            src = mdb.connect(self.db)
            tmp = os.path.join(tempfile.mkdtemp(prefix='mupg_'), 'copy.db')
            dst = sqlite3.connect(tmp)
            src.backup(dst)
            dst.close()
            src.close()
        except sqlite3.OperationalError as e:
            raise mdb.Refused(f'the database could not be copied ({e}); nothing was changed, try again later')
        shutil.copyfile(tmp, os.path.join(where, 'db', 'marionette.db'))
        max_audit = sqlite3.connect(tmp).execute('SELECT coalesce(max(id),0) FROM audit').fetchone()[0]
        for name in PROGRAMS + DOORS + GUIDE + (MANIFEST,):
            p = os.path.join(self.tools, name)
            if os.path.exists(p):
                shutil.copyfile(p, os.path.join(where, 'tools', name))
        info = {'from': self.installed, 'to': self.target, 'started_at': mdb.local_now(self.tz), 'state': 'started',
                'max_audit_before': max_audit, 'approval': approval,
                'had': sorted(os.listdir(os.path.join(where, 'tools')))}
        self.write_info(where, info)   # from here on --undo can put everything back, even after a failure
        try:
            return self.apply_steps(plan, where, info, own_run)
        except sqlite3.OperationalError as e:
            info['error'] = str(e)
            self.write_info(where, info)
            raise mdb.Refused(f'the upgrade stopped half way ({e}); run --undo to put back the copy taken before it')

    @staticmethod
    def write_info(where, info):
        with open(os.path.join(where, 'upgrade.json'), 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=1)

    def apply_steps(self, plan, where, info, own_run):
        # 2. the programs
        done = []
        for f in plan['files']:
            name, act = f['file'], f['action']
            if act in ('install', 'replace'):
                shutil.copyfile(source_of(name), os.path.join(self.tools, name))
                done.append(f'{name}: {"installed" if act == "install" else "replaced"}')
            elif act == 'keep_changed':
                shutil.copyfile(source_of(name), os.path.join(self.tools, f'{name}.new-{self.target}'))
                done.append(f'{name}: kept (changed locally); new version beside it')
        # 3. the data, through the NEW door
        door = mdb.Door(self.db)
        c = door.conn
        seed = mdb.load_seed()
        c.execute('BEGIN IMMEDIATE')
        added_types = []
        for code, g, ar, en, st, fields in seed.TYPES:
            if not c.execute('SELECT 1 FROM type WHERE code=?', (code,)).fetchone():
                c.execute('INSERT INTO type(code,grp,name_ar,name_en,statuses,fields) VALUES(?,?,?,?,?,?)',
                          (code, g, ar, en, json.dumps(st), json.dumps(fields, ensure_ascii=False)))
                added_types.append(code)
        added_rules = 0
        for r in seed.ACTION_RULES:
            # "IS", not "=": a permission line for a new thing has no starting status (NULL), and NULLs never collide
            # in a UNIQUE index, so INSERT OR IGNORE alone would add those lines again on every upgrade
            if not c.execute('SELECT 1 FROM action_rule WHERE scope=? AND action=? AND actor=? AND from_status IS ?',
                             r[:4]).fetchone():
                c.execute('INSERT INTO action_rule(scope,action,actor,from_status,to_status,needs_evidence) '
                          'VALUES(?,?,?,?,?,?)', r)
                added_rules += 1
        c.execute('COMMIT')
        run = door.do('start', 'program', type='run', params={
            'title': f'upgrade {self.installed} to {self.target}', 'trigger_kind': 'upgrade'})['id']
        fixes = []
        if self.before('1.7'):
            nxt = (datetime.date.fromisoformat(door.now()[:10]) + datetime.timedelta(days=1)).isoformat()
            ids = self.undated(c)
            for tid in ids:
                door.do('set_next_check', 'program', tid, params={'next_check': nxt}, run=run)
            if ids:
                fixes.append(f'{len(ids)} open items had no due date and no next check; their next check is {nxt}')
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('marionette_version',?)", (self.target,))
        c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('upgraded_at',?)", (door.now()[:16],))
        c.execute('COMMIT')
        door.do('close', 'program', run, params={'summary': {'upgrade': self.target, 'files': done, 'fixes': fixes}})
        max_after = c.execute('SELECT coalesce(max(id),0) FROM audit').fetchone()[0]
        door.conn.close()
        # 4. the manifest of what is installed now (only what this release installed: a copy the owner changed is
        #    never recorded as known, so a later upgrade keeps it too), state.json and runs.log
        kept = {f['file'] for f in plan['files'] if f['action'] == 'keep_changed'}
        files = {n: sha(source_of(n)) for n in PROGRAMS + DOORS + GUIDE if n not in kept}
        with open(os.path.join(self.tools, MANIFEST), 'w', encoding='utf-8') as f:
            json.dump({'version': self.target, 'files': files}, f, indent=1)
        info.update(state='done', max_audit_after=max_after, files=done, fixes=fixes)
        self.write_info(where, info)
        stp = os.path.join(self.F, 'state.json')
        if os.path.exists(stp):
            st = json.load(open(stp, encoding='utf-8'))
            st.setdefault('memory', {})['version'] = self.target
            with open(stp + '.tmp', 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
            os.replace(stp + '.tmp', stp)
        with open(os.path.join(self.F, 'runs.log'), 'a', encoding='utf-8') as f:
            f.write(f'\n## {now_text(self.tz)} upgrade {self.installed} -> {self.target}\n'
                    f'Copy before: {os.path.relpath(where, self.F)}. Programs: {"; ".join(done) or "none"}. '
                    f'Types added: {", ".join(added_types) or "none"}. Permission lines added: {added_rules}. '
                    f'Data: {"; ".join(fixes) or "nothing to fix"}. Undo: upgrade.py --undo.\n')
        return {'applied': True, 'from': self.installed, 'to': self.target, 'copy': os.path.relpath(where, self.F),
                'files': done, 'types_added': added_types, 'permission_lines_added': added_rules, 'fixes': fixes,
                'rules_to_propose': plan['rules_to_propose']}

    # ---------------------------------------------------------------- undo
    def undo(self, own_run=None):
        why = self.lock(own_run)
        if why:
            raise mdb.Refused(why)
        live = [(d, i) for d, i in self.copies() if not i.get('undone')]
        if not live:
            raise mdb.Refused('there is no upgrade to undo')
        where, info = live[0]
        since = info.get('max_audit_after') or info['max_audit_before']
        after = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True).execute(
            'SELECT count(*) FROM audit WHERE id>?', (since,)).fetchone()[0]
        aside = os.path.join(self.F, 'archive', f'undone_upgrade_{re.sub(r"[^0-9]", "", mdb.local_now(self.tz))}')
        n, base = 1, aside
        while os.path.exists(aside):
            n += 1
            aside = f'{base}_{n}'
        os.makedirs(os.path.join(aside, 'tools'))
        os.makedirs(os.path.join(aside, 'db'))
        shutil.copyfile(self.db, os.path.join(aside, 'db', 'marionette.db'))
        shutil.copyfile(os.path.join(where, 'db', 'marionette.db'), self.db)
        had = set(info.get('had') or os.listdir(os.path.join(where, 'tools')))
        for name in PROGRAMS + DOORS + GUIDE + (MANIFEST,):
            cur = os.path.join(self.tools, name)
            if os.path.exists(cur):
                shutil.copyfile(cur, os.path.join(aside, 'tools', name))
            if name in had:
                shutil.copyfile(os.path.join(where, 'tools', name), cur)
            elif os.path.exists(cur) and name == MANIFEST:
                os.replace(cur, os.path.join(aside, 'tools', name + '.moved'))
        info['undone'] = mdb.local_now(self.tz)
        self.write_info(where, info)
        stp = os.path.join(self.F, 'state.json')
        if os.path.exists(stp):
            st = json.load(open(stp, encoding='utf-8'))
            st.setdefault('memory', {})['version'] = info['from']
            with open(stp, 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.F, 'runs.log'), 'a', encoding='utf-8') as f:
            f.write(f'\n## {now_text(self.tz)} upgrade to {info["to"]} undone; back on {info["from"]}. The database '
                    f'as it was is kept in {os.path.relpath(aside, self.F)} ({after} changes recorded after the '
                    'upgrade are only there).\n')
        return {'undone': True, 'back_on': info['from'], 'changes_after_upgrade_kept_aside': after,
                'aside': os.path.relpath(aside, self.F)}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Bring a Marionette installation up to this release')
    ap.add_argument('--followup', required=True, help='the followup folder of the installation')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true')
    g.add_argument('--apply', action='store_true')
    g.add_argument('--undo', action='store_true')
    ap.add_argument('--approval', help="the owner's words agreeing, when a session applies it")
    ap.add_argument('--run', help='the run number of the session or task doing the upgrade, so its own lock does '
                                  'not hold it back')
    a = ap.parse_args(argv)
    try:
        u = Upgrade(a.followup)
        out = u.check() if a.check else u.apply(a.approval, a.run) if a.apply else u.undo(a.run)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    except mdb.Refused as e:
        print(json.dumps({'refused': str(e)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
