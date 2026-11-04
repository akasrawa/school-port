"""User management shared by the principal (admin) and teachers.

Admins manage everyone (admins, teachers, students). Teachers manage students only:
the students in their classes and the ones they created.
"""
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from .access import is_admin, manageable_student_ids, visible_classes
from .auth import MIN_PASSWORD, create_user, validate_account
from .db import get_db
from .i18n import t
from .settings import flag
from .utils import clean_username, gen_password, login_required

bp = Blueprint("users", __name__, url_prefix="/users")

ROLES = ("student", "teacher", "admin")


def _guard_teacher():
    if not is_admin() and not flag("teachers_manage_students"):
        flash(t("flash_forbidden"), "error")
        return redirect(url_for("teacher.dashboard"))
    return None


def _next_number_username(db):
    """Next free numeric username (1001, 1002, ...)."""
    numbers = [int(r[0]) for r in db.execute("SELECT username FROM users") if str(r[0]).isdigit() and len(str(r[0])) < 10]
    return str(max([1000] + numbers) + 1)


def _get_user(db, uid):
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if user is None:
        abort(404)
    if is_admin():
        return user
    allowed = manageable_student_ids(db)
    if user["role"] != "student" or user["id"] not in allowed:
        abort(404)
    return user


def _class_choices(db):
    return visible_classes(db)


def _set_memberships(db, user_id, class_ids):
    visible = {c["id"] for c in _class_choices(db)}
    wanted = {cid for cid in class_ids if cid in visible}
    for cid in visible:
        if cid in wanted:
            db.execute("INSERT OR IGNORE INTO class_members(class_id, student_id) VALUES(?,?)", (cid, user_id))
        else:
            db.execute("DELETE FROM class_members WHERE class_id=? AND student_id=?", (cid, user_id))


def _int_list(values):
    out = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            pass
    return out


@bp.get("/")
@login_required("staff")
def index():
    blocked = _guard_teacher()
    if blocked:
        return blocked
    db = get_db()
    q = (request.args.get("q") or "").strip()
    role = request.args.get("role") or ("" if is_admin() else "student")
    if role == "all":
        role = ""
    cid = request.args.get("class", type=int)
    status = request.args.get("status", "")
    sql = """SELECT u.*, (SELECT GROUP_CONCAT(c.name, '، ') FROM classes c JOIN class_members m ON m.class_id=c.id
                          WHERE m.student_id=u.id) AS class_names,
             (SELECT COUNT(*) FROM attempts a WHERE a.user_id=u.id AND a.is_preview=0 AND a.status!='in_progress') AS exams_taken
             FROM users u WHERE 1=1"""
    args = []
    if not is_admin():
        ids = manageable_student_ids(db)
        if not ids:
            ids = {-1}
        sql += f" AND u.id IN ({','.join('?' * len(ids))})"
        args += list(ids)
        role = "student"
    if role in ROLES:
        sql += " AND u.role=?"
        args.append(role)
    if q:
        sql += " AND (u.name LIKE ? OR u.username LIKE ? OR IFNULL(u.email,'') LIKE ?)"
        args += [f"%{q}%"] * 3
    if cid:
        sql += " AND u.id IN (SELECT student_id FROM class_members WHERE class_id=?)"
        args.append(cid)
    if status == "active":
        sql += " AND u.active=1"
    elif status == "disabled":
        sql += " AND u.active=0"
    sql += " ORDER BY CASE u.role WHEN 'admin' THEN 0 WHEN 'teacher' THEN 1 ELSE 2 END, u.name LIMIT 1000"
    rows = db.execute(sql, args).fetchall()
    counts = {
        r["role"]: r["c"] for r in db.execute("SELECT role, COUNT(*) c FROM users GROUP BY role")
    } if is_admin() else {}
    return render_template(
        "users/index.html", rows=rows, q=q, role=role, cid=cid, status=status,
        classes=_class_choices(db), counts=counts,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required("staff")
def new():
    blocked = _guard_teacher()
    if blocked:
        return blocked
    db = get_db()
    roles = ROLES if is_admin() else ("student",)
    role = request.values.get("role", "student")
    role = role if role in roles else "student"
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        username = clean_username(request.form.get("username")) or _next_number_username(db)
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip() or gen_password()
        error = validate_account(db, name, username, email, password)
        if error:
            flash(error, "error")
        else:
            uid = create_user(db, name, username, password, role, email, g.user["id"])
            if role == "student":
                _set_memberships(db, uid, _int_list(request.form.getlist("class_ids")))
            elif role == "teacher":
                for cid in _int_list(request.form.getlist("class_ids")):
                    db.execute("INSERT OR IGNORE INTO class_teachers(class_id, teacher_id) VALUES(?,?)", (cid, uid))
            db.commit()
            return render_template(
                "users/credentials.html",
                creds=[{"name": name, "username": username, "password": password, "role": role}],
                back=url_for("users.index", role=role if is_admin() else None),
            )
    return render_template(
        "users/new.html", role=role, roles=roles, classes=_class_choices(db),
        preselect=request.args.get("class", type=int),
    )


SPLIT_RE = re.compile(r"\s*[,\t;،]\s*")


@bp.route("/bulk", methods=["GET", "POST"])
@login_required("staff")
def bulk():
    blocked = _guard_teacher()
    if blocked:
        return blocked
    db = get_db()
    roles = ("student", "teacher") if is_admin() else ("student",)
    role = request.values.get("role", "student")
    role = role if role in roles else "student"
    if request.method == "POST":
        class_ids = _int_list(request.form.getlist("class_ids"))
        shared_password = request.form.get("shared_password", "").strip()
        creds, errors, linked = [], [], 0
        lines = [ln for ln in (request.form.get("bulk") or "").splitlines() if ln.strip()]
        for number, line in enumerate(lines[:500], start=1):
            parts = SPLIT_RE.split(line.strip())
            name = parts[0][:100] if parts else ""
            username = clean_username(parts[1]) if len(parts) > 1 else ""
            password = (parts[2].strip() if len(parts) > 2 else "") or shared_password
            if not name:
                errors.append(t("bulk_line_error", n=number, msg=t("err_name_required")))
                continue
            existing = None
            if username:
                existing = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if existing is not None:
                if existing["role"] == "student" and role == "student" and class_ids:
                    _set_memberships_add(db, existing["id"], class_ids)
                    linked += 1
                else:
                    errors.append(t("bulk_line_error", n=number, msg=t("err_username_taken", username=username)))
                continue
            username = username or _next_number_username(db)
            password = password or gen_password()
            error = validate_account(db, name, username, "", password)
            if error:
                errors.append(t("bulk_line_error", n=number, msg=error))
                continue
            uid = create_user(db, name, username, password, role, None, g.user["id"])
            if role == "student":
                _set_memberships_add(db, uid, class_ids)
            creds.append({"name": name, "username": username, "password": password, "role": role})
        db.commit()
        if linked:
            flash(t("flash_students_linked", n=linked), "info")
        for err in errors[:30]:
            flash(err, "error")
        if not creds:
            if not linked and not errors:
                flash(t("bulk_empty"), "error")
            return redirect(url_for("users.bulk", role=role))
        return render_template(
            "users/credentials.html", creds=creds,
            back=url_for("users.index", role=role if is_admin() else None),
        )
    return render_template(
        "users/bulk.html", role=role, roles=roles, classes=_class_choices(db),
        preselect=request.args.get("class", type=int),
    )


def _set_teacher_classes(db, teacher_id, class_ids):
    """Make the teacher's classes exactly `class_ids`.

    A class she owns but that is unticked is handed to the principal doing the edit, so the class
    (and its students) is kept but no longer appears for this teacher."""
    wanted = set(class_ids)
    db.execute("DELETE FROM class_teachers WHERE teacher_id=?", (teacher_id,))
    owned = {r[0] for r in db.execute("SELECT id FROM classes WHERE teacher_id=?", (teacher_id,))}
    for cid in owned - wanted:
        db.execute("UPDATE classes SET teacher_id=? WHERE id=?", (g.user["id"], cid))
    for cid in wanted - owned:
        if db.execute("SELECT 1 FROM classes WHERE id=?", (cid,)).fetchone():
            db.execute("INSERT OR IGNORE INTO class_teachers(class_id, teacher_id) VALUES(?,?)", (cid, teacher_id))


def _set_memberships_add(db, user_id, class_ids):
    visible = {c["id"] for c in _class_choices(db)}
    for cid in class_ids:
        if cid in visible:
            db.execute("INSERT OR IGNORE INTO class_members(class_id, student_id) VALUES(?,?)", (cid, user_id))


@bp.route("/<int:uid>", methods=["GET", "POST"])
@login_required("staff")
def edit(uid):
    blocked = _guard_teacher()
    if blocked:
        return blocked
    db = get_db()
    user = _get_user(db, uid)
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        username = clean_username(request.form.get("username"))
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        error = validate_account(db, name, username, email, password, exclude_id=uid, password_required=False)
        role = user["role"]
        if is_admin() and request.form.get("role") in ROLES:
            role = request.form.get("role")
        active = 1 if request.form.get("active") else 0
        if uid == g.user["id"]:
            role, active = user["role"], 1  # never lock yourself out
        if not error and user["role"] == "admin" and (role != "admin" or not active):
            others = db.execute("SELECT COUNT(*) c FROM users WHERE role='admin' AND active=1 AND id!=?", (uid,)).fetchone()["c"]
            if not others:
                error = t("err_last_admin")
        if error:
            flash(error, "error")
        else:
            db.execute(
                "UPDATE users SET name=?, username=?, email=?, role=?, active=? WHERE id=?",
                (name, username, email or None, role, active, uid),
            )
            if password:
                db.execute("UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?", (generate_password_hash(password), uid))
            if role == "student":
                _set_memberships(db, uid, _int_list(request.form.getlist("class_ids")))
            elif role == "teacher" and is_admin():
                _set_teacher_classes(db, uid, _int_list(request.form.getlist("class_ids")))
            db.commit()
            if password:
                if uid == g.user["id"]:
                    session["av"] = user["auth_version"] + 1
                flash(t("flash_password_set", name=name, password=password), "info")
            flash(t("flash_saved"), "success")
            return redirect(url_for("users.edit", uid=uid))
    if user["role"] == "student":
        member_of = {r[0] for r in db.execute("SELECT class_id FROM class_members WHERE student_id=?", (uid,))}
    else:
        member_of = {r[0] for r in db.execute("SELECT class_id FROM class_teachers WHERE teacher_id=?", (uid,))}
        member_of |= {r[0] for r in db.execute("SELECT id FROM classes WHERE teacher_id=?", (uid,))}
    attempts = db.execute(
        """SELECT a.*, f.title, f.pass_percent, f.teacher_id FROM attempts a JOIN forms f ON f.id=a.form_id
           WHERE a.user_id=? AND a.is_preview=0 ORDER BY a.started_at DESC LIMIT 50""",
        (uid,),
    ).fetchall()
    return render_template(
        "users/edit.html", u=user, classes=_class_choices(db), member_of=member_of, attempts=attempts,
        roles=ROLES, min_password=MIN_PASSWORD,
    )


@bp.post("/<int:uid>/reset")
@login_required("staff")
def reset(uid):
    blocked = _guard_teacher()
    if blocked:
        return blocked
    db = get_db()
    user = _get_user(db, uid)
    password = request.form.get("password", "").strip() or gen_password()
    if len(password) < MIN_PASSWORD:
        flash(t("err_password_short"), "error")
    else:
        db.execute("UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?", (generate_password_hash(password), uid))
        db.commit()
        if uid == g.user["id"]:
            session["av"] = user["auth_version"] + 1
        flash(t("flash_password_set", name=user["name"], password=password), "info")
    back = request.form.get("back") or ""
    return redirect(back if back.startswith("/") and not back.startswith("//") else url_for("users.edit", uid=uid))


@bp.post("/<int:uid>/delete")
@login_required("staff")
def delete(uid):
    blocked = _guard_teacher()
    if blocked:
        return blocked
    db = get_db()
    user = _get_user(db, uid)
    if uid == g.user["id"]:
        abort(400)
    if not is_admin() and user["created_by"] != g.user["id"]:
        flash(t("err_delete_not_creator"), "error")
        return redirect(url_for("users.edit", uid=uid))
    if user["role"] == "teacher" and db.execute("SELECT 1 FROM forms WHERE teacher_id=?", (uid,)).fetchone():
        flash(t("err_teacher_has_exams"), "error")
        return redirect(url_for("users.edit", uid=uid))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    flash(t("flash_deleted"), "success")
    return redirect(url_for("users.index"))


@bp.post("/bulk-action")
@login_required("staff")
def bulk_action():
    """Apply an action to several selected users (reset passwords, add to class, disable)."""
    blocked = _guard_teacher()
    if blocked:
        return blocked
    db = get_db()
    ids = _int_list(request.form.getlist("ids"))
    action = request.form.get("action")
    users = [_get_user(db, uid) for uid in ids]
    creds = []
    for user in users:
        if action == "reset":
            password = gen_password()
            db.execute("UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?", (generate_password_hash(password), user["id"]))
            creds.append({"name": user["name"], "username": user["username"], "password": password, "role": user["role"]})
        elif action == "add_class" and user["role"] == "student":
            cid = request.form.get("class_id", type=int)
            if cid:
                _set_memberships_add(db, user["id"], [cid])
        elif action in ("disable", "enable") and user["id"] != g.user["id"] and user["role"] != "admin":
            db.execute("UPDATE users SET active=? WHERE id=?", (1 if action == "enable" else 0, user["id"]))
    db.commit()
    if creds:
        return render_template("users/credentials.html", creds=creds, back=url_for("users.index"))
    flash(t("flash_saved"), "success")
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url) else url_for("users.index"))
