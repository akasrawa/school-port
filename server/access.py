"""Who may see / change what. Admins can do everything; teachers work on their own exams and classes."""
from flask import abort, g

from .db import get_db


def is_admin(user=None):
    user = user if user is not None else g.get("user")
    return user is not None and user["role"] == "admin"


def is_staff(user=None):
    user = user if user is not None else g.get("user")
    return user is not None and user["role"] in ("admin", "teacher")


def teacher_class_ids(db, uid):
    rows = db.execute(
        """SELECT id FROM classes WHERE teacher_id=?
           UNION SELECT class_id FROM class_teachers WHERE teacher_id=?""",
        (uid, uid),
    ).fetchall()
    return [r[0] for r in rows]


def visible_classes(db):
    """Classes the current staff member can work with."""
    if is_admin():
        return db.execute(
            """SELECT c.*, u.name AS teacher_name FROM classes c LEFT JOIN users u ON u.id=c.teacher_id
               ORDER BY c.name"""
        ).fetchall()
    ids = teacher_class_ids(db, g.user["id"])
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return db.execute(
        f"""SELECT c.*, u.name AS teacher_name FROM classes c LEFT JOIN users u ON u.id=c.teacher_id
            WHERE c.id IN ({marks}) ORDER BY c.name""",
        ids,
    ).fetchall()


def can_manage_class(db, classroom):
    if is_admin():
        return True
    return classroom["id"] in teacher_class_ids(db, g.user["id"])


def manageable_student_ids(db):
    """Students a teacher may edit: in her classes or created by her. Admin: all (None = no limit)."""
    if is_admin():
        return None
    uid = g.user["id"]
    ids = teacher_class_ids(db, uid)
    rows = []
    if ids:
        marks = ",".join("?" * len(ids))
        rows = db.execute(f"SELECT student_id FROM class_members WHERE class_id IN ({marks})", ids).fetchall()
    created = db.execute("SELECT id FROM users WHERE role='student' AND created_by=?", (uid,)).fetchall()
    return {r[0] for r in rows} | {r[0] for r in created}


def can_manage_student(db, student):
    if student is None or student["role"] != "student":
        return False
    allowed = manageable_student_ids(db)
    return allowed is None or student["id"] in allowed


def own_form(fid):
    row = get_db().execute("SELECT * FROM forms WHERE id=?", (fid,)).fetchone()
    if row is None or not (is_admin() or row["teacher_id"] == g.user["id"]):
        abort(404)
    return row


def own_class(cid):
    db = get_db()
    row = db.execute("SELECT * FROM classes WHERE id=?", (cid,)).fetchone()
    if row is None or not can_manage_class(db, row):
        abort(404)
    return row


def own_attempt(aid):
    row = get_db().execute(
        "SELECT a.*, f.teacher_id FROM attempts a JOIN forms f ON f.id=a.form_id WHERE a.id=?",
        (aid,),
    ).fetchone()
    if row is None or not (is_admin() or row["teacher_id"] == g.user["id"]):
        abort(404)
    return row


def assigned_student_ids(db, form_id):
    """Every student expected to take an exam (assigned classes + individually assigned)."""
    rows = db.execute(
        """SELECT m.student_id FROM form_classes fc JOIN class_members m ON m.class_id=fc.class_id WHERE fc.form_id=?
           UNION SELECT student_id FROM form_students WHERE form_id=?""",
        (form_id, form_id),
    ).fetchall()
    return [r[0] for r in rows]


def allowed_attempts(db, form, user_id):
    """Max attempts for this student (0 = unlimited) including retakes granted by the teacher."""
    if not form["max_attempts"]:
        return 0
    row = db.execute(
        "SELECT extra FROM extra_attempts WHERE form_id=? AND user_id=?", (form["id"], user_id)
    ).fetchone()
    return form["max_attempts"] + (row["extra"] if row else 0)
