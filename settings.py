"""School-wide settings and admin label overrides (cached per process, refreshed on change)."""
import threading

from flask import g

from .db import get_db

DEFAULTS = {
    "school_name_ar": "",
    "school_name_en": "",
    "allow_student_signup": "0",
    "allow_teacher_signup": "0",
    "teachers_excel_import": "0",
    "teachers_manage_students": "1",
    "default_manual_grade": "1",
    "auto_backup_hours": "24",
    "backup_keep": "14",
    "last_auto_backup": "0",
}

_lock = threading.Lock()
_cache = {"version": None, "settings": None, "labels": None}


def _version(db):
    row = db.execute("SELECT value FROM settings WHERE key='_version'").fetchone()
    return row["value"] if row else "0"


def _load(db):
    if g.get("_settings_ok") and _cache["settings"] is not None:
        return
    version = _version(db)
    if _cache["version"] == version and _cache["settings"] is not None:
        g._settings_ok = True
        return
    with _lock:
        settings = dict(DEFAULTS)
        for row in db.execute("SELECT key, value FROM settings"):
            settings[row["key"]] = row["value"]
        labels = {}
        for row in db.execute("SELECT key, lang, text FROM labels"):
            labels[(row["key"], row["lang"])] = row["text"]
        _cache.update(version=version, settings=settings, labels=labels)
    g._settings_ok = True


def bump(db):
    db.execute(
        "INSERT INTO settings(key, value) VALUES('_version', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(settings.value AS INTEGER) + 1 AS TEXT)"
    )
    _cache["settings"] = None
    g._settings_ok = False


def get_setting(key, db=None):
    db = db or get_db()
    _load(db)
    return _cache["settings"].get(key, DEFAULTS.get(key, ""))


def flag(key, db=None):
    return get_setting(key, db) == "1"


def set_setting(db, key, value):
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    bump(db)


def label_override(key, lang):
    try:
        db = get_db()
        _load(db)
    except Exception:  # outside an app context
        return None
    return _cache["labels"].get((key, lang))


def set_label(db, key, lang, text):
    text = (text or "").strip()
    if text:
        db.execute(
            "INSERT INTO labels(key, lang, text) VALUES(?,?,?) ON CONFLICT(key, lang) DO UPDATE SET text=excluded.text",
            (key, lang, text[:500]),
        )
    else:
        db.execute("DELETE FROM labels WHERE key=? AND lang=?", (key, lang))
    bump(db)
