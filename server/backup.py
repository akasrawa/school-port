"""Backups: a portable .zip with every table (data.json) and every uploaded file.

The same format works for SQLite (local install) and PostgreSQL (Vercel), so a backup taken on the
school computer can be restored on Vercel and the other way round. Older backups that contain an
``exams.sqlite3`` file are still accepted.
"""
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime

from flask import current_app, g

from .db import SCHEMA, get_db, is_postgres, migrate

NAME_RE = re.compile(r"^backup-\d{8}-\d{6}-(manual|auto|pre-restore)\.zip$")
TABLES = [
    "users", "classes", "class_teachers", "class_members", "forms", "form_classes", "form_students",
    "extra_attempts", "questions", "attempts", "answers", "events", "question_bank", "settings", "labels",
]
ID_TABLES = {"users", "classes", "forms", "questions", "attempts", "answers", "events", "question_bank"}
_auto_lock = threading.Lock()


def serverless():
    return bool(os.environ.get("VERCEL") or os.environ.get("SERVERLESS"))


def disk_backups():
    """Backups can be kept on the server only where the disk is permanent (not on Vercel)."""
    return not serverless()


def backup_dir(app=None):
    app = app or current_app
    path = app.config["BACKUP_DIR"]
    os.makedirs(path, exist_ok=True)
    return path


def _columns(db, table):
    cur = db.execute(f"SELECT * FROM {table} LIMIT 0")
    if getattr(cur, "description", None):
        return [d[0] for d in cur.description]
    return list(getattr(cur, "_columns", []))


def _jsonable(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    return value


def export_tables(db):
    data = {}
    for table in TABLES:
        cols = _columns(db, table)
        rows = db.execute(f"SELECT * FROM {table}").fetchall()
        data[table] = {"columns": cols, "rows": [[_jsonable(r[i]) for i in range(len(cols))] for r in rows]}
    return data


def build_zip(db, kind="manual"):
    """Returns (filename, bytes) of a complete backup."""
    from . import storage

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    data = export_tables(db)
    counts = {t: len(data[t]["rows"]) for t in ("users", "classes", "forms", "questions", "attempts")}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(data, ensure_ascii=False))
        for folder, name, content in storage.all_files(db):
            zf.writestr(f"uploads/media/{name}" if folder == "media" else f"uploads/{name}", content)
        zf.writestr("manifest.json", json.dumps({
            "created": stamp, "kind": kind, "counts": counts, "app": "exam-forms", "version": 3,
            "backend": "postgres" if is_postgres() else "sqlite",
        }))
    return f"backup-{stamp}-{kind}.zip", buffer.getvalue()


def create_backup(kind="manual", app=None, db=None):
    """Write a backup file into instance/backups (local installs). Returns its name."""
    app = app or current_app._get_current_object()
    own = db is None
    if own:
        from .db import connect

        db = connect(app.config["DATABASE"])
    try:
        name, content = build_zip(db, kind)
    finally:
        if own:
            db.close()
    path = os.path.join(backup_dir(app), name)
    if os.path.exists(path):
        time.sleep(1.1)
        return create_backup(kind, app)
    with open(path + ".part", "wb") as fh:
        fh.write(content)
    os.replace(path + ".part", path)
    return name


def list_backups(app=None):
    if not disk_backups():
        return []
    folder = backup_dir(app)
    out = []
    for name in sorted(os.listdir(folder), reverse=True):
        if not NAME_RE.match(name):
            continue
        full = os.path.join(folder, name)
        info = {"name": name, "size": os.path.getsize(full), "mtime": int(os.path.getmtime(full)), "kind": name.split("-")[-1][:-4]}
        try:
            with zipfile.ZipFile(full) as zf:
                info["counts"] = json.loads(zf.read("manifest.json")).get("counts", {})
        except (KeyError, ValueError, zipfile.BadZipFile):
            info["counts"] = {}
        out.append(info)
    return out


def prune(keep, app=None):
    folder = backup_dir(app)
    autos = sorted(n for n in os.listdir(folder) if NAME_RE.match(n) and n.endswith("-auto.zip"))
    for name in autos[:-keep] if keep > 0 else []:
        os.remove(os.path.join(folder, name))
    pre = sorted(n for n in os.listdir(folder) if NAME_RE.match(n) and n.endswith("-pre-restore.zip"))
    for name in pre[:-5]:
        os.remove(os.path.join(folder, name))


def safe_path(name):
    if not disk_backups() or not NAME_RE.match(name or ""):
        return None
    path = os.path.join(backup_dir(), name)
    return path if os.path.exists(path) else None


def _tables_from_sqlite_file(path):
    """Read an old-style backup database (upgrading it to the current columns first)."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "old.sqlite3")
        src = sqlite3.connect(path)
        dest = sqlite3.connect(copy)
        with dest:
            src.backup(dest)
        src.close()
        try:
            ok = dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            names = {r[0] for r in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError:
            dest.close()
            return None
        if not ok or not {"users", "forms", "questions", "attempts"} <= names:
            dest.close()
            return None
        migrate(dest)
        dest.executescript(SCHEMA)
        data = {}
        for table in TABLES:
            cur = dest.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            data[table] = {"columns": cols, "rows": [list(r) for r in cur.fetchall()]}
        dest.close()
        return data


def _read_backup(upload_path):
    """Returns (tables, files) where files is a list of (folder, name, bytes)."""
    files = []
    if zipfile.is_zipfile(upload_path):
        with zipfile.ZipFile(upload_path) as zf:
            names = zf.namelist()
            if "data.json" in names:
                tables = json.loads(zf.read("data.json"))
            elif "exams.sqlite3" in names:
                with tempfile.TemporaryDirectory() as tmp:
                    target = os.path.join(tmp, "exams.sqlite3")
                    with open(target, "wb") as fh:
                        fh.write(zf.read("exams.sqlite3"))
                    tables = _tables_from_sqlite_file(target)
            else:
                return None, []
            for member in names:
                if not member.startswith("uploads/") or member.endswith("/"):
                    continue
                rel = member[len("uploads/"):]
                folder = "media" if rel.startswith("media/") else "answers"
                files.append((folder, os.path.basename(rel), zf.read(member)))
        return tables, files
    return _tables_from_sqlite_file(upload_path), []


def import_tables(db, tables):
    for table in reversed(TABLES):
        db.execute(f"DELETE FROM {table}")
    for table in TABLES:
        block = tables.get(table)
        if not block or not block.get("rows"):
            continue
        have = set(_columns(db, table))
        cols = [c for c in block["columns"] if c in have]
        index = [block["columns"].index(c) for c in cols]
        rows = [[row[i] for i in index] for row in block["rows"]]
        marks = "(" + ",".join("?" * len(cols)) + ")"
        for start in range(0, len(rows), 200):
            chunk = rows[start:start + 200]
            db.execute(
                f"INSERT INTO {table}({','.join(cols)}) VALUES " + ",".join([marks] * len(chunk)),
                [value for row in chunk for value in row],
            )
    if is_postgres():
        for table in ID_TABLES:
            db.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}"
            )


def restore(upload_path):
    """Restore from a backup .zip (or a bare .sqlite3 file). Returns None on success or an error key."""
    from . import storage
    from .settings import _cache, bump

    tables, files = _read_backup(upload_path)
    if not tables or not tables.get("users", {}).get("rows"):
        return "err_backup_invalid"
    db = get_db()
    if disk_backups():
        create_backup("pre-restore", db=db)
    try:
        if not is_postgres():
            db.execute("PRAGMA foreign_keys = OFF")
        import_tables(db, tables)
        if storage.in_database():
            db.execute("DELETE FROM files")
        for folder, name, content in files:
            storage.save(folder, name, content, db=db)
        bump(db)
        db.commit()
    except Exception:
        db.rollback()
        current_app.logger.exception("restore failed")
        return "err_backup_invalid"
    finally:
        if not is_postgres():
            db.execute("PRAGMA foreign_keys = ON")
    _cache["settings"] = None
    _cache["version"] = None
    return None


def maybe_auto_backup():
    """Called after requests; makes an automatic backup when the configured interval has passed."""
    if not disk_backups():
        return
    from .settings import get_setting, set_setting

    try:
        hours = float(get_setting("auto_backup_hours") or 0)
        if hours <= 0:
            return
        last = float(get_setting("last_auto_backup") or 0)
        if time.time() - last < hours * 3600:
            return
        if not _auto_lock.acquire(blocking=False):
            return
    except Exception:
        return
    try:
        db = get_db()
        set_setting(db, "last_auto_backup", int(time.time()))
        db.commit()
        keep = int(get_setting("backup_keep") or 14)
    except Exception:
        _auto_lock.release()
        return
    app = current_app._get_current_object()

    def run():
        try:
            with app.app_context():
                create_backup("auto", app)
                prune(keep, app)
        except Exception:  # never break the site because of a backup
            app.logger.exception("automatic backup failed")
        finally:
            _auto_lock.release()

    threading.Thread(target=run, daemon=True).start()


_ = g
