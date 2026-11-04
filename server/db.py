import sqlite3

from flask import current_app, g

from .dbcompat import database_url, pg_connect, pg_schema, split_statements

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email TEXT COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','teacher','student')),
  active INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER,
  created_at INTEGER NOT NULL,
  last_login INTEGER,
  auth_version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS classes(
  id INTEGER PRIMARY KEY,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  join_code TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS class_teachers(
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY(class_id, teacher_id)
);

CREATE TABLE IF NOT EXISTS class_members(
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY(class_id, student_id)
);

CREATE TABLE IF NOT EXISTS forms(
  id INTEGER PRIMARY KEY,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  subject TEXT NOT NULL DEFAULT '',
  grade TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  time_limit_min INTEGER NOT NULL DEFAULT 0,
  opens_at INTEGER,
  closes_at INTEGER,
  max_attempts INTEGER NOT NULL DEFAULT 1,
  shuffle_questions INTEGER NOT NULL DEFAULT 0,
  shuffle_options INTEGER NOT NULL DEFAULT 0,
  show_results TEXT NOT NULL DEFAULT 'after_grading',
  show_answers INTEGER NOT NULL DEFAULT 1,
  pass_percent INTEGER NOT NULL DEFAULT 50,
  require_login INTEGER NOT NULL DEFAULT 1,
  block_copy INTEGER NOT NULL DEFAULT 0,
  detect_tabs INTEGER NOT NULL DEFAULT 0,
  require_fullscreen INTEGER NOT NULL DEFAULT 0,
  max_violations INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS form_classes(
  form_id INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  PRIMARY KEY(form_id, class_id)
);

CREATE TABLE IF NOT EXISTS form_students(
  form_id INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY(form_id, student_id)
);

CREATE TABLE IF NOT EXISTS extra_attempts(
  form_id INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  extra INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(form_id, user_id)
);

CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY,
  form_id INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  type TEXT NOT NULL,
  text TEXT NOT NULL,
  description TEXT DEFAULT '',
  image TEXT,
  audio TEXT,
  points REAL NOT NULL DEFAULT 1,
  required INTEGER NOT NULL DEFAULT 1,
  options_json TEXT,
  correct_json TEXT,
  explanation TEXT DEFAULT '',
  partial INTEGER NOT NULL DEFAULT 0,
  manual_grade INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY,
  form_id INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  taker_name TEXT NOT NULL,
  attempt_no INTEGER NOT NULL DEFAULT 1,
  started_at INTEGER NOT NULL,
  deadline_at INTEGER,
  submitted_at INTEGER,
  status TEXT NOT NULL DEFAULT 'in_progress',
  total_score REAL NOT NULL DEFAULT 0,
  max_score REAL NOT NULL DEFAULT 0,
  pending INTEGER NOT NULL DEFAULT 0,
  violations INTEGER NOT NULL DEFAULT 0,
  auto_submitted INTEGER NOT NULL DEFAULT 0,
  late INTEGER NOT NULL DEFAULT 0,
  is_preview INTEGER NOT NULL DEFAULT 0,
  seed INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS answers(
  id INTEGER PRIMARY KEY,
  attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  value_json TEXT,
  file_path TEXT,
  file_name TEXT,
  points REAL,
  manual INTEGER NOT NULL DEFAULT 0,
  feedback TEXT DEFAULT '',
  UNIQUE(attempt_id, question_id)
);

CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY,
  attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  detail TEXT DEFAULT '',
  at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS question_bank(
  id INTEGER PRIMARY KEY,
  owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  type TEXT NOT NULL,
  text TEXT NOT NULL,
  description TEXT DEFAULT '',
  image TEXT,
  audio TEXT,
  points REAL NOT NULL DEFAULT 1,
  options_json TEXT,
  correct_json TEXT,
  explanation TEXT DEFAULT '',
  partial INTEGER NOT NULL DEFAULT 0,
  manual_grade INTEGER NOT NULL DEFAULT 0,
  subject TEXT NOT NULL DEFAULT '',
  grade TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  shared INTEGER NOT NULL DEFAULT 1,
  uses INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS files(
  name TEXT PRIMARY KEY,
  mime TEXT,
  size INTEGER NOT NULL DEFAULT 0,
  data BLOB,
  created_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS labels(
  key TEXT NOT NULL,
  lang TEXT NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY(key, lang)
);

CREATE INDEX IF NOT EXISTS idx_attempts_form ON attempts(form_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_form ON questions(form_id);
CREATE INDEX IF NOT EXISTS idx_answers_attempt ON answers(attempt_id);
CREATE INDEX IF NOT EXISTS idx_events_attempt ON events(attempt_id);
CREATE INDEX IF NOT EXISTS idx_members_student ON class_members(student_id);
CREATE INDEX IF NOT EXISTS idx_form_students_student ON form_students(student_id);
"""


def is_postgres():
    return bool(database_url())


def connect(path=None):
    """New connection to the configured database (PostgreSQL if DATABASE_URL is set, else SQLite)."""
    url = database_url()
    if url:
        return pg_connect(url)
    conn = sqlite3.connect(path or current_app.config["DATABASE"], timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def migrate(conn):
    """Upgrade databases created by the first version of the platform."""
    tables = _tables(conn)
    if "users" in tables and "username" not in _columns(conn, "users"):
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            """
            BEGIN;
            CREATE TABLE users_new(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              email TEXT COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('admin','teacher','student')),
              active INTEGER NOT NULL DEFAULT 1,
              created_by INTEGER,
              created_at INTEGER NOT NULL,
              last_login INTEGER
            );
            INSERT INTO users_new(id, name, username, email, password_hash, role, created_at)
              SELECT id, name, email, email, password_hash, role, created_at FROM users;
            DROP TABLE users;
            ALTER TABLE users_new RENAME TO users;
            COMMIT;
            """
        )
        conn.execute("PRAGMA foreign_keys = ON")
    if "forms" in tables:
        cols = _columns(conn, "forms")
        if "subject" not in cols:
            conn.execute("ALTER TABLE forms ADD COLUMN subject TEXT NOT NULL DEFAULT ''")
        if "grade" not in cols:
            conn.execute("ALTER TABLE forms ADD COLUMN grade TEXT NOT NULL DEFAULT ''")
    if "questions" in tables and "image" not in _columns(conn, "questions"):
        conn.execute("ALTER TABLE questions ADD COLUMN image TEXT")
    if "questions" in tables and "audio" not in _columns(conn, "questions"):
        conn.execute("ALTER TABLE questions ADD COLUMN audio TEXT")
    if "questions" in tables and "manual_grade" not in _columns(conn, "questions"):
        conn.execute("ALTER TABLE questions ADD COLUMN manual_grade INTEGER NOT NULL DEFAULT 0")
    if "question_bank" in tables and "manual_grade" not in _columns(conn, "question_bank"):
        conn.execute("ALTER TABLE question_bank ADD COLUMN manual_grade INTEGER NOT NULL DEFAULT 0")
    if "users" in _tables(conn) and "auth_version" not in _columns(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0")
    conn.commit()


# Columns added after the first PostgreSQL release are listed here so old databases get them.
PG_LATE_COLUMNS = [
    ("questions", "manual_grade", "BIGINT NOT NULL DEFAULT 0"),
    ("question_bank", "manual_grade", "BIGINT NOT NULL DEFAULT 0"),
]


SCHEMA_VERSION = "2.5"


def init_postgres():
    conn = pg_connect(database_url())
    raw = conn._raw
    try:  # skip the DDL on every cold start once the schema is current
        row = raw.execute("SELECT value FROM settings WHERE key='_schema'").fetchone()
        if row and row[0] == SCHEMA_VERSION:
            conn.close()
            return
    except Exception:
        raw.rollback()
    raw.execute("CREATE EXTENSION IF NOT EXISTS citext")
    for statement in split_statements(pg_schema(SCHEMA)):
        raw.execute(statement)
    for table, column, kind in PG_LATE_COLUMNS:
        raw.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind}")
    raw.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL AND email != ''")
    raw.execute(
        "INSERT INTO settings(key, value) VALUES('_schema', %s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    conn.close()


def init_db(path):
    if is_postgres():
        init_postgres()
        return
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    conn.executescript(SCHEMA)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL AND email != ''"
    )
    conn.commit()
    conn.close()
