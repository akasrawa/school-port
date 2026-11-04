"""Where uploaded files live: on disk (local install) or inside the database (Vercel / PostgreSQL).

Two folders are used: ``media`` (question images and audio, public) and ``answers`` (students' files
and handwriting, private). Names are random, so they never collide.
"""
import mimetypes
import os

from flask import current_app

from .db import get_db, is_postgres
from .utils import now


def in_database():
    return is_postgres() or os.environ.get("FILE_STORAGE") == "db"


def _disk_path(folder, name):
    base = current_app.config["UPLOAD_DIR"]
    path = os.path.join(base, folder) if folder == "media" else base
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, os.path.basename(name))


def _key(folder, name):
    return f"{folder}/{os.path.basename(name)}"


def save(folder, name, data, mime=None, db=None):
    mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
    if in_database():
        db = db or get_db()
        db.execute("DELETE FROM files WHERE name=?", (_key(folder, name),))
        db.execute(
            "INSERT INTO files(name, mime, size, data, created_at) VALUES(?,?,?,?,?)",
            (_key(folder, name), mime, len(data), data, now()),
        )
        return
    with open(_disk_path(folder, name), "wb") as fh:
        fh.write(data)


def load(folder, name, db=None):
    """Returns (bytes, mime) or (None, None)."""
    if in_database():
        row = (db or get_db()).execute("SELECT data, mime FROM files WHERE name=?", (_key(folder, name),)).fetchone()
        if row is None:
            return None, None
        return bytes(row["data"]), row["mime"]
    path = _disk_path(folder, name)
    if not os.path.exists(path):
        return None, None
    with open(path, "rb") as fh:
        return fh.read(), mimetypes.guess_type(path)[0] or "application/octet-stream"


def exists(folder, name, db=None):
    if in_database():
        return (db or get_db()).execute("SELECT 1 FROM files WHERE name=?", (_key(folder, name),)).fetchone() is not None
    return os.path.exists(_disk_path(folder, name))


def delete(folder, name, db=None):
    if not name:
        return
    if in_database():
        (db or get_db()).execute("DELETE FROM files WHERE name=?", (_key(folder, name),))
        return
    path = _disk_path(folder, name)
    if os.path.exists(path):
        os.remove(path)


def all_files(db=None):
    """Every stored file as (folder, name, bytes) – used by backups."""
    if in_database():
        for row in (db or get_db()).execute("SELECT name, data FROM files ORDER BY name"):
            folder, _, name = row["name"].partition("/")
            yield folder, name, bytes(row["data"])
        return
    base = current_app.config["UPLOAD_DIR"]
    for root, _dirs, files in os.walk(base):
        for filename in files:
            full = os.path.join(root, filename)
            rel = os.path.relpath(full, base)
            folder = "media" if rel.startswith("media" + os.sep) else "answers"
            with open(full, "rb") as fh:
                yield folder, filename, fh.read()
