"""PostgreSQL support with the same calling style the app uses for SQLite.

The code base talks to the database with SQLite-flavoured SQL (``?`` placeholders, ``INSERT OR IGNORE``,
``GROUP_CONCAT`` ...). When ``DATABASE_URL`` points to PostgreSQL (for example Neon on Vercel) every
statement goes through :func:`translate` and rows come back as :class:`Row`, which behaves like
``sqlite3.Row`` (``row["name"]``, ``row[0]``, ``dict(row)``).
"""
import decimal
import importlib
import os
import re

# Tables whose primary key is an auto-increment "id" (so INSERT can report lastrowid).
ID_TABLES = {
    "users", "classes", "forms", "questions", "attempts", "answers", "events", "question_bank",
}

_INSERT_RE = re.compile(r"^\s*INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+([A-Za-z_]+)", re.I)


_NAMED_RE = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def translate(sql, has_params=True, named=False):
    """SQLite dialect -> PostgreSQL dialect (only the constructs this project uses)."""
    s = sql
    ignore = bool(re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", s, re.I))
    s = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", s, flags=re.I)
    s = re.sub(r"\bGROUP_CONCAT\s*\(", "string_agg(", s, flags=re.I)
    s = re.sub(r"\bIFNULL\s*\(", "COALESCE(", s, flags=re.I)
    s = re.sub(r"\bIS\s+NOT\s+\?", "IS DISTINCT FROM ?", s, flags=re.I)
    s = re.sub(r"\bIS\s+\?", "IS NOT DISTINCT FROM ?", s, flags=re.I)
    s = re.sub(r"\bLIKE\b", "ILIKE", s)
    s = s.rstrip().rstrip(";")
    if ignore:
        s += " ON CONFLICT DO NOTHING"
    m = _INSERT_RE.match(sql)
    if m and m.group(1).lower() in ID_TABLES and not re.search(r"\bRETURNING\b", s, re.I):
        s += " RETURNING id"
    if has_params:
        s = s.replace("%", "%%")
        if named:  # sqlite ":name" -> psycopg "%(name)s"
            s = _NAMED_RE.sub(lambda m: "%%(%s)s" % m.group(1), s)
        else:
            s = s.replace("?", "%s")
    return s


def _convert(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, memoryview):
        return bytes(value)
    return value


class Row(tuple):
    """Tuple that can also be indexed by column name, like sqlite3.Row."""

    def __new__(cls, values, columns):
        obj = super().__new__(cls, [_convert(v) for v in values])
        obj._columns = columns
        obj._index = {c: i for i, c in enumerate(columns)}
        return obj

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._columns)

    def get(self, key, default=None):
        return self[key] if key in self._index else default


class Cursor:
    def __init__(self, raw=None, lastrowid=None):
        self._raw = raw
        self.lastrowid = lastrowid
        self._buffer = None
        self._columns = []
        if raw is not None and raw.description:
            self._columns = [getattr(d, "name", None) or d[0] for d in raw.description]
        self.rowcount = getattr(raw, "rowcount", -1) if raw is not None else 0

    def _wrap(self, values):
        return Row(values, self._columns) if values is not None else None

    def fetchone(self):
        if self._buffer is not None:
            return self._buffer.pop(0) if self._buffer else None
        if self._raw is None or not self._columns:
            return None
        return self._wrap(self._raw.fetchone())

    def fetchall(self):
        if self._buffer is not None:
            rows, self._buffer = self._buffer, []
            return rows
        if self._raw is None or not self._columns:
            return []
        return [self._wrap(r) for r in self._raw.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class PGConnection:
    backend = "postgres"

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith("PRAGMA"):
            return Cursor()
        named = isinstance(params, dict)
        params = dict(params) if named else tuple(params or ())
        translated = translate(sql, bool(params), named)
        raw = self._raw.execute(translated, params) if params else self._raw.execute(translated)
        cur = Cursor(raw)
        if "RETURNING id" in translated and translated.endswith("RETURNING id"):
            row = cur.fetchone()
            cur.lastrowid = row[0] if row else None
            cur._buffer = [row] if row else []
        return cur

    def executescript(self, script):
        for statement in split_statements(script):
            self._raw.execute(statement)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._raw.rollback()
        except Exception:
            pass
        self._raw.close()


def split_statements(script):
    return [s.strip() for s in script.split(";") if s.strip()]


def database_url():
    for key in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL"):
        value = os.environ.get(key, "")
        if value.startswith(("postgres://", "postgresql://")):
            return value
    return ""


def pg_connect(url):
    driver = os.environ.get("EXAMS_PG_DRIVER")
    if driver:  # used by the test-suite
        return PGConnection(importlib.import_module(driver).connect(url))
    import psycopg

    # prepare_threshold=None keeps it compatible with PgBouncer / Neon's pooled connections.
    return PGConnection(psycopg.connect(url, prepare_threshold=None, connect_timeout=15))


def pg_schema(sqlite_schema):
    """Derive the PostgreSQL schema from the SQLite one."""
    s = sqlite_schema
    s = s.replace("INTEGER PRIMARY KEY", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
    s = re.sub(r"TEXT NOT NULL UNIQUE COLLATE NOCASE", "CITEXT NOT NULL UNIQUE", s)
    s = re.sub(r"TEXT COLLATE NOCASE", "CITEXT", s)
    s = re.sub(r"\bINTEGER\b", "BIGINT", s)
    s = re.sub(r"\bREAL\b", "DOUBLE PRECISION", s)
    s = re.sub(r"\bBLOB\b", "BYTEA", s)
    return s
