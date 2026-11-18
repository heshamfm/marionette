-- Marionette by Hesham Elmahdy (github.com/heshamfm): the database, schema 0.1. One file, SQLite.
-- Every connection must run: PRAGMA foreign_keys=ON; PRAGMA journal_mode=TRUNCATE;
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE grp(code TEXT PRIMARY KEY, name_ar TEXT NOT NULL, name_en TEXT NOT NULL);
CREATE TABLE type(code TEXT PRIMARY KEY, grp TEXT NOT NULL REFERENCES grp(code), name_ar TEXT NOT NULL, name_en TEXT NOT NULL,
  statuses TEXT NOT NULL CHECK(json_valid(statuses)), fields TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(fields)));
-- the one counter for every thing of every type
CREATE TABLE thing(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL REFERENCES type(code), title TEXT NOT NULL,
  created_at TEXT NOT NULL, created_by TEXT NOT NULL CHECK(created_by IN('user','claude','program')),
  area_id INTEGER REFERENCES thing(id), project_id INTEGER REFERENCES thing(id));
CREATE TRIGGER thing_no_delete BEFORE DELETE ON thing BEGIN SELECT RAISE(ABORT,'nothing is ever deleted; close or cancel it instead'); END;
-- reference records
CREATE TABLE party(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), kind TEXT NOT NULL CHECK(kind IN('person','org','system')),
  relation TEXT NOT NULL DEFAULT 'stranger', org_id INTEGER REFERENCES party(thing_id), role_in_org TEXT,
  is_user INTEGER NOT NULL DEFAULT 0 CHECK(is_user IN(0,1)),
  status TEXT NOT NULL DEFAULT 'unconfirmed' CHECK(status IN('unconfirmed','confirmed','inactive')), external_link TEXT);
CREATE UNIQUE INDEX party_one_user ON party(is_user) WHERE is_user=1;
CREATE TABLE party_handle(id INTEGER PRIMARY KEY, party_id INTEGER NOT NULL REFERENCES party(thing_id),
  kind TEXT NOT NULL CHECK(kind IN('alias','email','phone','whatsapp','address','domain')), value TEXT NOT NULL);
CREATE UNIQUE INDEX party_email_once ON party_handle(lower(value)) WHERE kind='email';
CREATE TABLE area(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), description TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN('active','archived')));
CREATE TABLE project(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), area_id INTEGER NOT NULL REFERENCES area(thing_id),
  external_link TEXT, started TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN('active','paused','ended')));
CREATE TABLE channel(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), connection TEXT NOT NULL, reads TEXT, watermark TEXT,
  send_policy TEXT NOT NULL DEFAULT 'draft_only', last_result TEXT,
  status TEXT NOT NULL DEFAULT 'connected' CHECK(status IN('connected','unavailable','stopped')));
-- follow-up things: one table for the 7 types; type-specific fields in details
CREATE TABLE followup(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), status TEXT NOT NULL,
  holder_id INTEGER NOT NULL REFERENCES party(thing_id), due TEXT, next_check TEXT,
  close_reason TEXT CHECK(close_reason IS NULL OR close_reason IN('done','handed_over','merged','not_needed')),
  details TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details)));
CREATE TRIGGER followup_status_ins BEFORE INSERT ON followup BEGIN
  SELECT RAISE(ABORT,'status not allowed for this type') WHERE NOT EXISTS(
    SELECT 1 FROM thing t JOIN type ty ON ty.code=t.type, json_each(ty.statuses) j WHERE t.id=NEW.thing_id AND j.value=NEW.status); END;
CREATE TRIGGER followup_status_upd BEFORE UPDATE OF status ON followup BEGIN
  SELECT RAISE(ABORT,'status not allowed for this type') WHERE NOT EXISTS(
    SELECT 1 FROM thing t JOIN type ty ON ty.code=t.type, json_each(ty.statuses) j WHERE t.id=NEW.thing_id AND j.value=NEW.status); END;
-- system memory
CREATE TABLE run(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), started TEXT NOT NULL, ended TEXT, trigger_kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN('running','complete','complete_with_gaps','failed')),
  summary TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(summary)));
-- sources and evidence
CREATE TABLE source(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), channel_id INTEGER NOT NULL REFERENCES channel(thing_id),
  external_id TEXT NOT NULL, permalink TEXT, source_date TEXT,
  read_state TEXT NOT NULL DEFAULT 'unread' CHECK(read_state IN('unread','partial','full','failed')), read_fail_reason TEXT,
  verdict TEXT CHECK(verdict IS NULL OR verdict IN('linked','informed','ignored')), verdict_reason TEXT,
  run_id INTEGER REFERENCES run(thing_id), details TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details)),
  UNIQUE(channel_id, external_id),
  CHECK(verdict IS NULL OR read_state='full'),
  CHECK(verdict IS NOT 'ignored' OR verdict_reason IS NOT NULL));
CREATE TRIGGER run_close BEFORE UPDATE OF status ON run WHEN NEW.status IN('complete','complete_with_gaps') BEGIN
  SELECT RAISE(ABORT,'a source read in this run has no verdict and no recorded reason') WHERE EXISTS(
    SELECT 1 FROM source s WHERE s.run_id=NEW.thing_id AND s.verdict IS NULL AND s.read_fail_reason IS NULL);
  SELECT RAISE(ABORT,'some sources could not be read: close as complete_with_gaps') WHERE NEW.status='complete' AND EXISTS(
    SELECT 1 FROM source s WHERE s.run_id=NEW.thing_id AND s.verdict IS NULL); END;
CREATE TABLE file(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), original_name TEXT NOT NULL, stored_name TEXT,
  sha256 TEXT UNIQUE, size INTEGER, mime TEXT, lives TEXT NOT NULL CHECK(lives IN('store','user_disk','provider_link')),
  status TEXT NOT NULL DEFAULT 'kept' CHECK(status IN('kept','referenced','deleted_by_user','missing')),
  downloaded_at TEXT, from_source INTEGER REFERENCES source(thing_id));
CREATE TABLE decision(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), verbatim TEXT NOT NULL, said_at TEXT NOT NULL,
  session_id INTEGER REFERENCES source(thing_id),
  status TEXT NOT NULL DEFAULT 'in_force' CHECK(status IN('in_force','superseded')), superseded_by INTEGER REFERENCES decision(thing_id));
CREATE TRIGGER decision_text_fixed BEFORE UPDATE OF verbatim ON decision BEGIN SELECT RAISE(ABORT,'the wording of a decision never changes'); END;
CREATE TABLE rule(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), text TEXT NOT NULL,
  decision_id INTEGER NOT NULL REFERENCES decision(thing_id), scope TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(scope)),
  enforced_by TEXT NOT NULL CHECK(enforced_by IN('program','claude')),
  status TEXT NOT NULL DEFAULT 'in_force' CHECK(status IN('in_force','paused','cancelled')));
CREATE TABLE job(thing_id INTEGER PRIMARY KEY REFERENCES thing(id), instructions TEXT NOT NULL, schedule TEXT NOT NULL,
  channels TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(channels)),
  send_permission TEXT NOT NULL DEFAULT 'draft_only' CHECK(send_permission IN('draft_only','approved_text')),
  approved_texts TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(approved_texts)), last_period TEXT,
  status TEXT NOT NULL DEFAULT 'enabled' CHECK(status IN('enabled','paused','cancelled')),
  CHECK(send_permission='draft_only' OR json_array_length(approved_texts)>0));
-- links, evidence, audit, permissions
CREATE TABLE link(id INTEGER PRIMARY KEY, from_id INTEGER NOT NULL REFERENCES thing(id), to_id INTEGER NOT NULL REFERENCES thing(id),
  role TEXT NOT NULL, inferred INTEGER NOT NULL DEFAULT 0 CHECK(inferred IN(0,1)), created_at TEXT NOT NULL, UNIQUE(from_id,to_id,role));
CREATE TABLE evidence(id INTEGER PRIMARY KEY, thing_id INTEGER NOT NULL REFERENCES thing(id), source_id INTEGER NOT NULL REFERENCES source(thing_id),
  quote TEXT NOT NULL, position TEXT, quote_date TEXT, inferred INTEGER NOT NULL DEFAULT 0 CHECK(inferred IN(0,1)));
CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL CHECK(actor IN('user','claude','program')),
  run_id INTEGER REFERENCES run(thing_id), thing_id INTEGER NOT NULL REFERENCES thing(id), action TEXT NOT NULL,
  field TEXT, old_value TEXT, new_value TEXT, evidence_id INTEGER REFERENCES evidence(id), note TEXT);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'the audit trail is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'the audit trail is append-only'); END;
CREATE TABLE action_rule(id INTEGER PRIMARY KEY, scope TEXT NOT NULL, action TEXT NOT NULL,
  actor TEXT NOT NULL CHECK(actor IN('user','claude','program')), from_status TEXT, to_status TEXT,
  needs_evidence INTEGER NOT NULL DEFAULT 0 CHECK(needs_evidence IN(0,1)), UNIQUE(scope,action,actor,from_status));
