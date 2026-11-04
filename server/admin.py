"""Principal (admin) control panel."""
import os
import tempfile

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from . import backup as backups
from .db import get_db
from .i18n import TEXT, current_lang, t
from .settings import DEFAULTS, get_setting, set_label, set_setting
from .teacher import facet_values, not_started_summary, search_forms
from .utils import login_required

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Groups shown in the label editor so the principal can find things quickly.
LABEL_GROUPS = [
    ("lbl_group_main", ["app_name", "app_tagline", "footer_note", "hero_eyebrow", "hero_title", "hero_text"]),
    ("lbl_group_roles", ["role_admin", "role_teacher", "role_student", "students", "teachers", "nav_classes",
                         "nav_dashboard", "nav_my_exams", "nav_users", "nav_admin", "class_name", "exam"]),
    ("lbl_group_login", ["login_title", "login_sub", "login_field", "login_field_hint", "password"]),
]


@bp.before_request
def only_admin():
    if g.user is None:
        return redirect(url_for("auth.login", next=request.path))
    if g.user["role"] != "admin":
        abort(403)
    return None


@bp.get("/")
@login_required("admin")
def dashboard():
    db = get_db()
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
    stats = {
        "teachers": one("SELECT COUNT(*) FROM users WHERE role='teacher'"),
        "students": one("SELECT COUNT(*) FROM users WHERE role='student'"),
        "classes": one("SELECT COUNT(*) FROM classes"),
        "forms": one("SELECT COUNT(*) FROM forms"),
        "published": one("SELECT COUNT(*) FROM forms WHERE status='published'"),
        "submissions": one("SELECT COUNT(*) FROM attempts WHERE is_preview=0 AND status!='in_progress'"),
        "pending": one("SELECT COUNT(*) FROM attempts WHERE is_preview=0 AND status='submitted'"),
        "running": one("SELECT COUNT(*) FROM attempts WHERE is_preview=0 AND status='in_progress'"),
    }
    teachers = db.execute(
        """SELECT u.id, u.name, u.username, u.last_login,
           (SELECT COUNT(*) FROM forms f WHERE f.teacher_id=u.id) AS forms,
           (SELECT COUNT(*) FROM attempts a JOIN forms f ON f.id=a.form_id WHERE f.teacher_id=u.id AND a.status='submitted' AND a.is_preview=0) AS pending
           FROM users u WHERE u.role='teacher' ORDER BY u.name"""
    ).fetchall()
    recent = db.execute(
        """SELECT a.*, f.title AS form_title, f.pass_percent FROM attempts a JOIN forms f ON f.id=a.form_id
           WHERE a.is_preview=0 AND a.status!='in_progress' ORDER BY a.submitted_at DESC LIMIT 10"""
    ).fetchall()
    last_backups = backups.list_backups()[:3]
    waiting = not_started_summary(db)
    stats["not_started"] = sum(len(w["waiting"]) for w in waiting)
    return render_template(
        "admin/dashboard.html", stats=stats, teachers=teachers, recent=recent, last_backups=last_backups,
        waiting=waiting,
    )


@bp.get("/exams")
@login_required("admin")
def exams():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "")
    teacher_id = request.args.get("teacher", type=int)
    class_id = request.args.get("class", type=int)
    subject = request.args.get("subject", "")
    grade = request.args.get("grade", "")
    forms = search_forms(db, q, status, class_id, teacher_id, subject, grade)
    teachers = db.execute("SELECT id, name FROM users WHERE role IN ('teacher','admin') ORDER BY name").fetchall()
    classes = db.execute("SELECT id, name FROM classes ORDER BY name").fetchall()
    return render_template(
        "admin/exams.html", forms=forms, q=q, status=status, teacher_id=teacher_id, class_id=class_id,
        subject=subject, grade=grade, teachers=teachers, classes=classes,
        subjects=facet_values(db, "subject"), grades=facet_values(db, "grade"),
    )


@bp.post("/exams/<int:fid>/owner")
@login_required("admin")
def change_owner(fid):
    db = get_db()
    tid = request.form.get("teacher_id", type=int)
    if tid and db.execute("SELECT 1 FROM users WHERE id=? AND role IN ('teacher','admin')", (tid,)).fetchone():
        db.execute("UPDATE forms SET teacher_id=? WHERE id=?", (tid, fid))
        db.commit()
        flash(t("flash_saved"), "success")
    return redirect(request.form.get("back") if (request.form.get("back") or "").startswith("/") else url_for("admin.exams"))


# ----------------------------------------------------------------- settings
BOOL_SETTINGS = ["allow_student_signup", "allow_teacher_signup", "teachers_excel_import", "teachers_manage_students"]


@bp.route("/settings", methods=["GET", "POST"])
@login_required("admin")
def settings():
    db = get_db()
    if request.method == "POST":
        for key in BOOL_SETTINGS:
            set_setting(db, key, "1" if request.form.get(key) else "0")
        try:
            hours = max(0, min(24 * 30, int(request.form.get("auto_backup_hours") or 0)))
            keep = max(1, min(365, int(request.form.get("backup_keep") or 14)))
        except ValueError:
            hours, keep = 24, 14
        set_setting(db, "auto_backup_hours", hours)
        set_setting(db, "backup_keep", keep)
        db.commit()
        flash(t("flash_saved"), "success")
        return redirect(url_for("admin.settings"))
    values = {key: get_setting(key) for key in DEFAULTS}
    return render_template("admin/settings.html", values=values, bools=BOOL_SETTINGS)


@bp.post("/samples")
@login_required("admin")
def samples():
    from .seed import install_samples

    db = get_db()
    n = install_samples(db, g.user["id"])
    db.commit()
    flash(t("flash_samples", n=n), "success")
    return redirect(url_for("admin.exams"))


# ------------------------------------------------------------------- labels
@bp.route("/labels", methods=["GET", "POST"])
@login_required("admin")
def labels():
    db = get_db()
    if request.method == "POST":
        changed = 0
        for field, value in request.form.items():
            if not field.startswith("lbl__"):
                continue
            _, key, lang = field.split("__", 2)
            if key not in TEXT or lang not in ("ar", "en"):
                continue
            default = TEXT[key][1] if lang == "ar" else TEXT[key][0]
            value = value.strip()
            current = db.execute("SELECT text FROM labels WHERE key=? AND lang=?", (key, lang)).fetchone()
            new_value = "" if value == default else value
            if (current["text"] if current else "") != new_value:
                set_label(db, key, lang, new_value)
                changed += 1
        db.commit()
        flash(t("flash_labels_saved", n=changed), "success")
        return redirect(url_for("admin.labels", q=request.args.get("q", ""), group=request.args.get("group", "")))
    q = (request.args.get("q") or "").strip().lower()
    group = request.args.get("group", "")
    overrides = {(r["key"], r["lang"]): r["text"] for r in db.execute("SELECT * FROM labels")}
    if q:
        keys = [k for k, (en, ar) in TEXT.items()
                if q in k.lower() or q in en.lower() or q in ar
                or q in overrides.get((k, "ar"), "").lower() or q in overrides.get((k, "en"), "").lower()]
    elif group == "changed":
        keys = sorted({k for (k, _lang) in overrides if k in TEXT})
    elif group == "all":
        keys = list(TEXT.keys())
    else:
        keys = [k for _name, ks in LABEL_GROUPS for k in ks if k in TEXT]
    rows = [
        {"key": k, "en": TEXT[k][0], "ar": TEXT[k][1],
         "en_o": overrides.get((k, "en")), "ar_o": overrides.get((k, "ar"))}
        for k in keys[:400]
    ]
    return render_template(
        "admin/labels.html", rows=rows, q=q, group=group, total=len(keys), changed=len(overrides),
        groups=LABEL_GROUPS,
    )


@bp.post("/labels/reset")
@login_required("admin")
def labels_reset():
    db = get_db()
    db.execute("DELETE FROM labels")
    from .settings import bump

    bump(db)
    db.commit()
    flash(t("flash_labels_reset"), "success")
    return redirect(url_for("admin.labels"))


# ------------------------------------------------------------------ backups
@bp.get("/backups")
@login_required("admin")
def backup_list():
    return render_template(
        "admin/backups.html", items=backups.list_backups(), on_disk=backups.disk_backups(),
        hours=get_setting("auto_backup_hours"), keep=get_setting("backup_keep"),
    )


@bp.post("/backups/create")
@login_required("admin")
def backup_create():
    if not backups.disk_backups():
        return redirect(url_for("admin.backup_download_now"))
    name = backups.create_backup("manual", db=get_db())
    flash(t("flash_backup_created", name=name), "success")
    return redirect(url_for("admin.backup_list"))


@bp.get("/backups/<name>")
@login_required("admin")
def backup_download(name):
    path = backups.safe_path(name)
    if not path:
        abort(404)
    return send_file(path, as_attachment=True, download_name=name, mimetype="application/zip")


@bp.get("/backups/download-now")
@login_required("admin")
def backup_download_now():
    import io

    name, content = backups.build_zip(get_db(), "manual")
    return send_file(io.BytesIO(content), as_attachment=True, download_name=name, mimetype="application/zip")


@bp.post("/backups/<name>/delete")
@login_required("admin")
def backup_delete(name):
    path = backups.safe_path(name)
    if not path:
        abort(404)
    os.remove(path)
    flash(t("flash_deleted"), "success")
    return redirect(url_for("admin.backup_list"))


@bp.post("/backups/restore")
@login_required("admin")
def backup_restore():
    if request.form.get("confirm") != "RESTORE":
        flash(t("err_restore_confirm"), "error")
        return redirect(url_for("admin.backup_list"))
    name = request.form.get("name")
    if name:
        path = backups.safe_path(name)
        if not path:
            abort(404)
        error = backups.restore(path)
    else:
        file = request.files.get("file")
        if file is None or not file.filename:
            flash(t("err_upload"), "error")
            return redirect(url_for("admin.backup_list"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "upload.bin")
            file.save(path)
            error = backups.restore(path)
    if error:
        flash(t(error), "error")
        return redirect(url_for("admin.backup_list"))
    flash(t("flash_restored"), "success")
    return redirect(url_for("auth.index"))


_ = current_lang
