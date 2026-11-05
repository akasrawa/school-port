import io
import os
import uuid
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .access import (
    assigned_student_ids,
    is_admin,
    manageable_student_ids,
    own_attempt,
    own_class,
    own_form,
    visible_classes,
)
from .arabicfix import fix_pdf_strings
from .db import get_db
from .grading import (
    AUTO,
    CHOICE_TYPES,
    MANUAL,
    TYPES,
    answer_text,
    correct_text,
    eff_points,
    form_analytics,
    has_key,
    is_manual,
    load_questions,
    recalc_attempt,
    regrade_form,
)
from .i18n import current_lang, t
from .settings import flag
from .utils import fmt_num, gen_code, jd, jl, login_required, now, pct

bp = Blueprint("teacher", __name__, url_prefix="/teacher")

IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
AUDIO_EXT = {"mp3", "m4a", "wav", "ogg", "oga", "webm", "aac", "mp4"}
AUDIO_MAX_BYTES = 20 * 1024 * 1024
Q_COLUMNS = "type, text, description, image, audio, points, required, options_json, correct_json, explanation, partial, manual_grade"


def question_values(q):
    return (
        q["type"], q["text"], q["description"], q.get("image"), q.get("audio"), q["points"], q.get("required", 1),
        jd(q["options"]) if q.get("options") is not None else None,
        jd(q["correct"]) if q.get("correct") is not None else None,
        q.get("explanation") or "", q.get("partial", 0), 1 if q.get("manual_grade") else 0,
    )


def insert_question(db, fid, position, q):
    return db.execute(
        f"INSERT INTO questions(form_id, position, {Q_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (fid, position) + question_values(q),
    ).lastrowid


def media_exists(name):
    from . import storage

    return storage.exists("media", name)


def can_import_excel():
    return is_admin() or flag("teachers_excel_import")


def search_forms(db, q="", status="", class_id=None, teacher_id=None, subject="", grade="", limit=500):
    """Exam search engine: title, code, subject, grade, description, teacher name and question text."""
    sql = """SELECT f.*, u.name AS teacher_name,
           (SELECT COUNT(*) FROM questions q WHERE q.form_id=f.id AND q.type!='section') AS qcount,
           (SELECT COUNT(*) FROM attempts a WHERE a.form_id=f.id AND a.is_preview=0 AND a.status!='in_progress') AS acount,
           (SELECT COUNT(*) FROM attempts a WHERE a.form_id=f.id AND a.is_preview=0 AND a.status='submitted') AS pending,
           (SELECT AVG(a.total_score*100.0/a.max_score) FROM attempts a WHERE a.form_id=f.id AND a.is_preview=0 AND a.status!='in_progress' AND a.max_score>0) AS avg_pct
           FROM forms f LEFT JOIN users u ON u.id=f.teacher_id WHERE 1=1"""
    args = []
    if not is_admin():
        sql += " AND f.teacher_id=?"
        args.append(g.user["id"])
    elif teacher_id:
        sql += " AND f.teacher_id=?"
        args.append(teacher_id)
    if q:
        like = f"%{q}%"
        sql += """ AND (f.title LIKE ? OR f.code LIKE ? OR f.subject LIKE ? OR f.grade LIKE ? OR f.description LIKE ?
                   OR u.name LIKE ? OR EXISTS(SELECT 1 FROM questions qq WHERE qq.form_id=f.id AND qq.text LIKE ?))"""
        args += [like] * 7
    if status in ("draft", "published", "closed"):
        sql += " AND f.status=?"
        args.append(status)
    if class_id:
        sql += " AND f.id IN (SELECT form_id FROM form_classes WHERE class_id=?)"
        args.append(class_id)
    if subject:
        sql += " AND f.subject=?"
        args.append(subject)
    if grade:
        sql += " AND f.grade=?"
        args.append(grade)
    sql += f" ORDER BY f.updated_at DESC LIMIT {int(limit)}"
    return db.execute(sql, args).fetchall()


def facet_values(db, column):
    sql = f"SELECT DISTINCT {column} v FROM forms WHERE {column}!=''"
    args = []
    if not is_admin():
        sql += " AND teacher_id=?"
        args.append(g.user["id"])
    return [r["v"] for r in db.execute(sql + " ORDER BY v", args)]


# ---------------------------------------------------------------- dashboard
@bp.get("/")
@login_required("staff")
def dashboard():
    db = get_db()
    uid = g.user["id"]
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "")
    class_id = request.args.get("class", type=int)
    subject = request.args.get("subject", "")
    grade = request.args.get("grade", "")
    forms = search_forms(db, q, status, class_id, None, subject, grade)
    mine = forms if not is_admin() else search_forms(db)
    class_list = visible_classes(db)
    student_ids = manageable_student_ids(db)
    stats = {
        "forms": len(mine),
        "published": sum(1 for f in mine if f["status"] == "published"),
        "submissions": sum(f["acount"] for f in mine),
        "pending": sum(f["pending"] for f in mine),
        "students": len(student_ids) if student_ids is not None else db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='student'").fetchone()["c"],
        "classes": len(class_list),
    }
    recent_sql = """SELECT a.*, f.title AS form_title, f.pass_percent FROM attempts a JOIN forms f ON f.id=a.form_id
           WHERE a.is_preview=0 AND a.status!='in_progress'"""
    recent = db.execute(
        recent_sql + ("" if is_admin() else " AND f.teacher_id=?") + " ORDER BY a.submitted_at DESC LIMIT 8",
        () if is_admin() else (uid,),
    ).fetchall()
    filtered = bool(q or status or class_id or subject or grade)
    waiting = not_started_summary(db, None if is_admin() else uid, 10000)
    stats["not_started"] = sum(len(w["waiting"]) for w in waiting)
    return render_template(
        "teacher/dashboard.html", forms=forms, stats=stats, recent=recent, q=q, status=status,
        class_id=class_id, subject=subject, grade=grade, classes=class_list, filtered=filtered,
        subjects=facet_values(db, "subject"), grades=facet_values(db, "grade"),
        needs_admin=not db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone(),
        waiting=waiting[:6],
    )


# ------------------------------------------------------------------ builder
def _new_unique_code(db):
    while True:
        code = gen_code(8)
        if not db.execute("SELECT 1 FROM forms WHERE code=?", (code,)).fetchone():
            return code


@bp.post("/forms/new")
@login_required("staff")
def new_form():
    db = get_db()
    stamp = now()
    cur = db.execute(
        """INSERT INTO forms(teacher_id, code, title, description, show_results, show_answers, max_attempts, created_at, updated_at)
           VALUES(?,?,?,?, 'after_grading', 1, 1, ?,?)""",
        (g.user["id"], _new_unique_code(db), t("untitled_exam"), "", stamp, stamp),
    )
    db.commit()
    return redirect(url_for("teacher.edit_form", fid=cur.lastrowid))


@bp.get("/forms/<int:fid>/edit")
@login_required("staff")
def edit_form(fid):
    form = own_form(fid)
    db = get_db()
    questions = load_questions(db, fid)
    payload_questions = [
        {
            "id": q["id"],
            "type": q["type"],
            "text": q["text"],
            "description": q["description"] or "",
            "image": q["image"] or "",
            "audio": q["audio"] or "",
            "points": q["points"],
            "required": bool(q["required"]),
            "options": q["options"],
            "correct": q["correct"],
            "explanation": q["explanation"] or "",
            "partial": bool(q["partial"]),
            "manual_grade": bool(q["manual_grade"]),
        }
        for q in questions
    ]
    classes = visible_classes(db)
    selected = [
        r["class_id"] for r in db.execute("SELECT class_id FROM form_classes WHERE form_id=?", (fid,))
    ]
    selected_students = [
        r["student_id"] for r in db.execute("SELECT student_id FROM form_students WHERE form_id=?", (fid,))
    ]
    allowed = manageable_student_ids(db)
    student_sql = """SELECT u.id, u.name, u.username,
        (SELECT GROUP_CONCAT(c.name, '، ') FROM classes c JOIN class_members m ON m.class_id=c.id WHERE m.student_id=u.id) AS class_names
        FROM users u WHERE u.role='student' AND u.active=1"""
    if allowed is not None:
        ids = list(allowed | set(selected_students)) or [-1]
        student_sql += f" AND u.id IN ({','.join('?' * len(ids))})"
        students = db.execute(student_sql + " ORDER BY u.name", ids).fetchall()
    else:
        students = db.execute(student_sql + " ORDER BY u.name").fetchall()
    attempts = db.execute(
        "SELECT COUNT(*) c FROM attempts WHERE form_id=? AND is_preview=0 AND status!='in_progress'",
        (fid,),
    ).fetchone()["c"]
    keys = [
        "type_mcq", "type_checkbox", "type_dropdown", "type_truefalse", "type_short", "type_number", "type_draw",
        "draw_note", "draw_lines", "draw_height",
        "type_paragraph", "type_file", "type_scale", "type_date", "type_match", "type_fill", "type_order",
        "type_section", "question_text", "question_help", "section_title", "section_body",
        "points", "required", "option_n", "add_option", "remove", "move_up", "move_down", "duplicate",
        "correct_answer", "accepted_answers", "accepted_answers_hint", "numeric_answer", "tolerance",
        "partial_credit", "explanation", "explanation_hint", "scale_max", "scale_min_label",
        "scale_max_label", "manual_grade_note", "info_only_note", "true", "false", "saving", "saved",
        "unsaved", "confirm_delete_question", "no_questions", "question_n", "total_points",
        "questions_count", "save_failed", "copy_done", "autograded", "manual_graded", "survey_q",
        "file_upload_note", "no_key_warning", "add_image", "change_image", "remove_image", "uploading",
        "match_left", "match_right", "add_pair", "distractors", "distractors_hint", "fill_template",
        "fill_template_hint", "word_bank", "order_answer", "order_answer_hint", "order_preview",
        "collapse_all", "expand_all", "insert_here", "drag_hint", "image_error", "blanks_found",
        "section_note", "pick_correct_hint", "untitled_question", "partial_auto_note",
        "bank_save_one", "bank_saved", "bank_exists", "bank_title", "bank_none_found", "bank_added", "loading",
        "add_audio", "record_audio", "stop_recording", "remove_audio", "recording", "mic_denied", "fmt_hint",
        "err_audio_too_large", "grading_mode", "grading_auto", "grading_manual", "manual_key_hint",
        "model_answer", "model_answer_ph",
    ]
    i18n = {k: t(k) for k in keys}
    form_data = {
        "id": fid,
        "code": form["code"],
        "status": form["status"],
        "imageUrl": url_for("teacher.upload_image", fid=fid),
        "bankUrl": url_for("teacher.api_bank"),
        "bankUsedUrl": url_for("teacher.api_bank_used"),
        "defaultManual": flag("default_manual_grade"),
        "mediaBase": url_for("exam.media", name="__NAME__"),
        "settings": {
            "title": form["title"],
            "description": form["description"] or "",
            "subject": form["subject"] or "",
            "grade": form["grade"] or "",
            "time_limit_min": form["time_limit_min"],
            "opens_at": form["opens_at"],
            "closes_at": form["closes_at"],
            "max_attempts": form["max_attempts"],
            "shuffle_questions": bool(form["shuffle_questions"]),
            "shuffle_options": bool(form["shuffle_options"]),
            "show_results": form["show_results"],
            "show_answers": bool(form["show_answers"]),
            "pass_percent": form["pass_percent"],
            "require_login": bool(form["require_login"]),
            "block_copy": bool(form["block_copy"]),
            "detect_tabs": bool(form["detect_tabs"]),
            "require_fullscreen": bool(form["require_fullscreen"]),
            "max_violations": form["max_violations"],
            "class_ids": selected,
            "student_ids": selected_students,
        },
        "questions": payload_questions,
    }
    return render_template(
        "teacher/builder.html",
        form=form,
        classes=classes,
        selected=selected,
        students=students,
        selected_students=selected_students,
        form_data=form_data,
        i18n=i18n,
        has_attempts=attempts,
        can_import=can_import_excel(),
        subjects=facet_values(db, "subject"),
        grades=facet_values(db, "grade"),
    )


@bp.post("/api/forms/<int:fid>/image")
@login_required("staff")
def upload_image(fid):
    """Upload a question picture or audio file (stored on disk or in the database)."""
    from . import storage

    own_form(fid)
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(ok=False, error=t("err_upload")), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    data = file.read()
    if ext in AUDIO_EXT or (file.mimetype or "").startswith("audio/"):
        if ext not in AUDIO_EXT:
            ext = "webm"
        if len(data) > min(AUDIO_MAX_BYTES, current_app.config["MAX_CONTENT_LENGTH"]):
            return jsonify(ok=False, error=t("err_audio_too_large")), 413
        name = f"a{fid}_{uuid.uuid4().hex[:16]}.{ext}"
        storage.save("media", name, data, file.mimetype if (file.mimetype or "").startswith("audio/") else None)
        get_db().commit()
        return jsonify(ok=True, kind="audio", name=name, url=url_for("exam.media", name=name))
    if ext not in IMAGE_EXT:
        return jsonify(ok=False, error=t("err_image_type")), 400
    if len(data) > current_app.config["MAX_UPLOAD_BYTES"]:
        return jsonify(ok=False, error=t("err_file_too_large")), 413
    try:
        from PIL import Image

        Image.open(io.BytesIO(data)).verify()
        img = Image.open(io.BytesIO(data))
        if max(img.size) > 1400 and ext in ("png", "jpg", "jpeg", "webp"):
            img.thumbnail((1400, 1400))
            out = io.BytesIO()
            img.save(out, format={"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[ext])
            data = out.getvalue()
    except ImportError:
        pass
    except Exception:
        return jsonify(ok=False, error=t("err_image_type")), 400
    name = f"q{fid}_{uuid.uuid4().hex[:16]}.{ext}"
    storage.save("media", name, data)
    get_db().commit()
    return jsonify(ok=True, kind="image", name=name, url=url_for("exam.media", name=name))


def _int(value, low, high, default):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _opt_ts(value):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def clean_settings(raw):
    show = raw.get("show_results")
    return {
        "title": (raw.get("title") or "").strip()[:200] or t("untitled_exam"),
        "description": (raw.get("description") or "").strip()[:4000],
        "subject": (raw.get("subject") or "").strip()[:80],
        "grade": (raw.get("grade") or "").strip()[:80],
        "time_limit_min": _int(raw.get("time_limit_min"), 0, 1440, 0),
        "opens_at": _opt_ts(raw.get("opens_at")),
        "closes_at": _opt_ts(raw.get("closes_at")),
        "max_attempts": _int(raw.get("max_attempts"), 0, 50, 1),
        "shuffle_questions": 1 if raw.get("shuffle_questions") else 0,
        "shuffle_options": 1 if raw.get("shuffle_options") else 0,
        "show_results": show if show in ("immediate", "after_grading", "never") else "after_grading",
        "show_answers": 1 if raw.get("show_answers") else 0,
        "pass_percent": _int(raw.get("pass_percent"), 0, 100, 50),
        "require_login": 1 if raw.get("require_login") else 0,
        "block_copy": 1 if raw.get("block_copy") else 0,
        "detect_tabs": 1 if raw.get("detect_tabs") else 0,
        "require_fullscreen": 1 if raw.get("require_fullscreen") else 0,
        "max_violations": _int(raw.get("max_violations"), 0, 50, 0),
    }


def _clean_image(value, allowed=IMAGE_EXT):
    name = os.path.basename(str(value or ""))
    if not name or "." not in name or name.rsplit(".", 1)[-1].lower() not in allowed:
        return None
    return name if media_exists(name) else None


def _str_list(values, limit=60, size=300):
    if not isinstance(values, list):
        return []
    return [str(v).strip()[:size] for v in values if str(v).strip()][:limit]


def clean_question(raw):
    kind = raw.get("type")
    if kind not in TYPES:
        raise ValueError(t("err_bad_type"))
    text = (raw.get("text") or "").strip()
    if not text and kind != "section":
        raise ValueError(t("err_question_text"))
    try:
        points = float(raw.get("points", 1))
    except (TypeError, ValueError):
        points = 1.0
    points = max(0.0, min(1000.0, round(points, 2)))
    out = {
        "id": raw.get("id") if isinstance(raw.get("id"), int) else None,
        "type": kind,
        "text": text[:1500],
        "description": (raw.get("description") or "").strip()[:6000],
        "image": _clean_image(raw.get("image")),
        "audio": _clean_image(raw.get("audio"), AUDIO_EXT),
        "points": 0.0 if kind in ("scale", "date", "section") else points,
        "required": 0 if kind == "section" else (1 if raw.get("required") else 0),
        "explanation": (raw.get("explanation") or "").strip()[:2000],
        "partial": 1 if kind in ("checkbox", "match", "fill") and raw.get("partial") else 0,
        "manual_grade": 1 if kind in AUTO and raw.get("manual_grade") else 0,
        "options": None,
        "correct": None,
    }
    correct = raw.get("correct")
    options = raw.get("options")
    if kind in CHOICE_TYPES:
        opts = [str(o).strip()[:300] for o in (options or [])] if isinstance(options, list) else []
        if len(opts) < 2 or len(opts) > 30 or any(not o for o in opts):
            raise ValueError(t("err_options"))
        out["options"] = opts
        if kind == "checkbox":
            if isinstance(correct, list):
                picked = sorted({int(i) for i in correct if isinstance(i, int) and 0 <= i < len(opts)})
                out["correct"] = picked or None
        elif isinstance(correct, int) and not isinstance(correct, bool) and 0 <= correct < len(opts):
            out["correct"] = correct
    elif kind == "truefalse":
        out["correct"] = correct if correct in ("true", "false") else None
    elif kind in ("short", "order"):
        answers = _str_list(correct, 30, 500)
        out["correct"] = answers or None
        if kind == "order" and not answers:
            raise ValueError(t("err_order_answer"))
    elif kind == "number":
        if isinstance(correct, dict) and correct.get("value") not in (None, ""):
            try:
                out["correct"] = {
                    "value": float(correct["value"]),
                    "tolerance": abs(float(correct.get("tolerance") or 0)),
                }
            except (TypeError, ValueError):
                raise ValueError(t("err_number"))
    elif kind == "draw":
        raw_opts = options if isinstance(options, dict) else {}
        out["options"] = {"lines": bool(raw_opts.get("lines", True)), "height": _int(raw_opts.get("height"), 200, 900, 380)}
    elif kind == "scale":
        raw_opts = options if isinstance(options, dict) else {}
        out["options"] = {
            "max": _int(raw_opts.get("max"), 3, 10, 5),
            "min_label": str(raw_opts.get("min_label") or "")[:60],
            "max_label": str(raw_opts.get("max_label") or "")[:60],
        }
    elif kind == "match":
        raw_opts = options if isinstance(options, dict) else {}
        pairs = []
        for pair in raw_opts.get("pairs") or []:
            if isinstance(pair, list) and len(pair) == 2:
                left, right = str(pair[0]).strip()[:300], str(pair[1]).strip()[:300]
                if left and right:
                    pairs.append([left, right])
        if len(pairs) < 1:
            raise ValueError(t("err_match_pairs"))
        out["options"] = {"pairs": pairs[:40], "distractors": _str_list(raw_opts.get("distractors"), 20)}
    elif kind == "fill":
        raw_opts = options if isinstance(options, dict) else {}
        template = str(raw_opts.get("template") or "").strip()[:6000]
        out["options"] = {
            "template": template,
            "bank": bool(raw_opts.get("bank")),
            "distractors": _str_list(raw_opts.get("distractors"), 20),
        }
        from .grading import fill_blanks

        if not fill_blanks({"options": out["options"]}):
            raise ValueError(t("err_fill_blanks"))
    return out


@bp.post("/api/forms/<int:fid>/save")
@login_required("staff")
def api_save(fid):
    own_form(fid)
    data = fix_pdf_strings(request.get_json(silent=True) or {})
    settings = clean_settings(data.get("settings") or {})
    raw_questions = data.get("questions") or []
    if not isinstance(raw_questions, list) or len(raw_questions) > 200:
        return jsonify(ok=False, error=t("err_too_many_questions")), 400
    cleaned = []
    for index, raw in enumerate(raw_questions):
        try:
            cleaned.append(clean_question(raw if isinstance(raw, dict) else {}))
        except ValueError as exc:
            return jsonify(ok=False, error=t("err_question_n", n=index + 1, msg=str(exc)), index=index), 400
    db = get_db()
    stamp = now()
    db.execute(
        """UPDATE forms SET title=:title, description=:description, subject=:subject, grade=:grade,
           time_limit_min=:time_limit_min,
           opens_at=:opens_at, closes_at=:closes_at, max_attempts=:max_attempts,
           shuffle_questions=:shuffle_questions, shuffle_options=:shuffle_options,
           show_results=:show_results, show_answers=:show_answers, pass_percent=:pass_percent,
           require_login=:require_login, block_copy=:block_copy, detect_tabs=:detect_tabs,
           require_fullscreen=:require_fullscreen, max_violations=:max_violations,
           updated_at=:updated WHERE id=:id""",
        {**settings, "updated": stamp, "id": fid},
    )
    existing = {r["id"] for r in db.execute("SELECT id FROM questions WHERE form_id=?", (fid,))}
    keep, ids = set(), []
    for position, q in enumerate(cleaned):
        if q["id"] in existing:
            db.execute(
                """UPDATE questions SET position=?, type=?, text=?, description=?, image=?, audio=?, points=?, required=?,
                   options_json=?, correct_json=?, explanation=?, partial=?, manual_grade=? WHERE id=?""",
                (position,) + question_values(q) + (q["id"],),
            )
            qid = q["id"]
        else:
            qid = insert_question(db, fid, position, q)
        keep.add(qid)
        ids.append(qid)
    for stale in existing - keep:
        db.execute("DELETE FROM questions WHERE id=?", (stale,))
    raw_settings = data.get("settings") or {}
    visible = {c["id"] for c in visible_classes(db)}
    if visible:
        db.execute(
            "DELETE FROM form_classes WHERE form_id=? AND class_id IN (%s)" % ",".join("?" * len(visible)),
            (fid, *visible),
        )
    for cid in raw_settings.get("class_ids") or []:
        if isinstance(cid, int) and cid in visible:
            db.execute("INSERT OR IGNORE INTO form_classes(form_id, class_id) VALUES(?,?)", (fid, cid))
    allowed = manageable_student_ids(db)
    wanted = {sid for sid in (raw_settings.get("student_ids") or []) if isinstance(sid, int)}
    current = {r[0] for r in db.execute("SELECT student_id FROM form_students WHERE form_id=?", (fid,))}
    for sid in current - wanted:
        if allowed is None or sid in allowed:
            db.execute("DELETE FROM form_students WHERE form_id=? AND student_id=?", (fid, sid))
    for sid in wanted - current:
        if (allowed is None or sid in allowed) and db.execute(
            "SELECT 1 FROM users WHERE id=? AND role='student'", (sid,)
        ).fetchone():
            db.execute("INSERT OR IGNORE INTO form_students(form_id, student_id) VALUES(?,?)", (fid, sid))
    regrade_form(db, fid)
    db.commit()
    return jsonify(ok=True, ids=ids, updated_at=stamp)


@bp.post("/forms/<int:fid>/status")
@login_required("staff")
def set_status(fid):
    form = own_form(fid)
    status = request.form.get("status")
    db = get_db()
    if status not in ("draft", "published", "closed"):
        abort(400)
    if status == "published":
        count = db.execute("SELECT COUNT(*) c FROM questions WHERE form_id=?", (fid,)).fetchone()["c"]
        if count == 0:
            flash(t("err_publish_empty"), "error")
            return redirect(url_for("teacher.edit_form", fid=fid))
    db.execute("UPDATE forms SET status=?, updated_at=? WHERE id=?", (status, now(), fid))
    db.commit()
    flash(t("flash_status_" + status), "success")
    return redirect(request.form.get("back") if (request.form.get("back") or "").startswith("/") else url_for("teacher.dashboard"))


@bp.post("/forms/<int:fid>/duplicate")
@login_required("staff")
def duplicate_form(fid):
    form = own_form(fid)
    db = get_db()
    stamp = now()
    cur = db.execute(
        """INSERT INTO forms(teacher_id, code, title, description, subject, grade, status, time_limit_min, opens_at, closes_at,
           max_attempts, shuffle_questions, shuffle_options, show_results, show_answers, pass_percent,
           require_login, block_copy, detect_tabs, require_fullscreen, max_violations, created_at, updated_at)
           VALUES(?,?,?,?,?,?, 'draft', ?,?,?, ?,?,?,?,?,?, ?,?,?,?,?, ?,?)""",
        (
            g.user["id"], _new_unique_code(db), (form["title"] + " " + t("copy_suffix"))[:200], form["description"],
            form["subject"], form["grade"],
            form["time_limit_min"], form["opens_at"], form["closes_at"], form["max_attempts"],
            form["shuffle_questions"], form["shuffle_options"], form["show_results"], form["show_answers"],
            form["pass_percent"], form["require_login"], form["block_copy"], form["detect_tabs"],
            form["require_fullscreen"], form["max_violations"], stamp, stamp,
        ),
    )
    new_id = cur.lastrowid
    db.execute(
        """INSERT INTO questions(form_id, position, type, text, description, image, audio, points, required,
           options_json, correct_json, explanation, partial, manual_grade)
           SELECT ?, position, type, text, description, image, audio, points, required, options_json, correct_json,
           explanation, partial, manual_grade FROM questions WHERE form_id=? ORDER BY position, id""",
        (new_id, fid),
    )
    db.execute(
        "INSERT INTO form_classes(form_id, class_id) SELECT ?, class_id FROM form_classes WHERE form_id=?",
        (new_id, fid),
    )
    db.commit()
    flash(t("flash_duplicated"), "success")
    return redirect(url_for("teacher.edit_form", fid=new_id))


def _delete_files(db, where, args):
    from . import storage

    for row in db.execute(f"SELECT file_path FROM answers WHERE file_path IS NOT NULL AND {where}", args).fetchall():
        storage.delete("answers", row["file_path"], db)


@bp.post("/forms/<int:fid>/delete")
@login_required("staff")
def delete_form(fid):
    own_form(fid)
    db = get_db()
    _delete_files(db, "attempt_id IN (SELECT id FROM attempts WHERE form_id=?)", (fid,))
    db.execute("DELETE FROM forms WHERE id=?", (fid,))
    db.commit()
    flash(t("flash_deleted"), "success")
    return redirect(url_for("teacher.dashboard"))


# -------------------------------------------------------------- submissions
def _roster(db, fid):
    """Assigned students with their attempt status for this exam."""
    ids = assigned_student_ids(db, fid)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return db.execute(
        f"""SELECT u.id, u.name, u.username,
            (SELECT GROUP_CONCAT(c.name, '، ') FROM classes c JOIN class_members m ON m.class_id=c.id WHERE m.student_id=u.id) AS class_names,
            (SELECT COUNT(*) FROM attempts a WHERE a.form_id=? AND a.user_id=u.id AND a.is_preview=0 AND a.status!='in_progress') AS done,
            (SELECT COUNT(*) FROM attempts a WHERE a.form_id=? AND a.user_id=u.id AND a.is_preview=0 AND a.status='in_progress') AS running,
            (SELECT extra FROM extra_attempts e WHERE e.form_id=? AND e.user_id=u.id) AS extra,
            u.last_login
            FROM users u WHERE u.id IN ({marks}) AND u.active=1 ORDER BY u.name""",
        (fid, fid, fid, *ids),
    ).fetchall()


@bp.get("/forms/<int:fid>/submissions")
@login_required("staff")
def submissions(fid):
    form = own_form(fid)
    db = get_db()
    flt = request.args.get("filter", "all")
    roster = _roster(db, fid)
    not_started = [r for r in roster if not r["done"] and not r["running"]]
    in_progress = db.execute(
        """SELECT a.*, u.username FROM attempts a LEFT JOIN users u ON u.id=a.user_id
           WHERE a.form_id=? AND a.is_preview=0 AND a.status='in_progress' ORDER BY a.started_at""",
        (fid,),
    ).fetchall()
    rows = []
    if flt not in ("not_started", "in_progress"):
        sql = """SELECT a.*, u.username,
                 (SELECT GROUP_CONCAT(c.name, '، ') FROM classes c JOIN class_members m ON m.class_id=c.id
                  WHERE m.student_id=a.user_id) AS class_names,
                 (SELECT extra FROM extra_attempts e WHERE e.form_id=a.form_id AND e.user_id=a.user_id) AS extra
                 FROM attempts a LEFT JOIN users u ON u.id=a.user_id
                 WHERE a.form_id=? AND a.is_preview=0 AND a.status!='in_progress'"""
        if flt == "pending":
            sql += " AND a.status='submitted'"
        elif flt == "graded":
            sql += " AND a.status='graded'"
        elif flt == "flagged":
            sql += " AND (a.violations>0 OR a.late=1 OR a.auto_submitted=1)"
        sql += " ORDER BY a.submitted_at DESC"
        rows = db.execute(sql, (fid,)).fetchall()
    owner = db.execute("SELECT name FROM users WHERE id=?", (form["teacher_id"],)).fetchone()
    return render_template(
        "teacher/submissions.html", form=form, rows=rows, flt=flt, running=len(in_progress), owner_name=owner["name"] if owner else "",
        in_progress=in_progress, not_started=not_started, roster_size=len(roster),
    )


def not_started_summary(db, teacher_id=None, limit=12):
    """Published, open exams with the number of assigned students who have not started yet."""
    sql = "SELECT f.*, u.name AS teacher_name FROM forms f LEFT JOIN users u ON u.id=f.teacher_id WHERE f.status='published'"
    args = []
    if teacher_id:
        sql += " AND f.teacher_id=?"
        args.append(teacher_id)
    stamp = now()
    out = []
    for form in db.execute(sql + " ORDER BY f.updated_at DESC", args).fetchall():
        if form["closes_at"] and form["closes_at"] < stamp:
            continue
        roster = _roster(db, form["id"])
        if not roster:
            continue
        waiting = [r for r in roster if not r["done"] and not r["running"]]
        out.append({
            "form": form, "assigned": len(roster), "done": sum(1 for r in roster if r["done"]),
            "running": sum(1 for r in roster if r["running"]), "waiting": waiting,
        })
    out.sort(key=lambda x: -len(x["waiting"]))
    return out[:limit]


PEOPLE_KINDS = ("submissions", "pending", "not_started")


@bp.get("/students/<kind>")
@login_required("staff")
def people(kind):
    """Student-level lists behind the dashboard counters: submissions, waiting for grading, not started."""
    if kind not in PEOPLE_KINDS:
        abort(404)
    db = get_db()
    teacher_id = None if is_admin() else g.user["id"]
    q = (request.args.get("q") or "").strip()
    rows, waiting = [], []
    if kind == "not_started":
        for w in not_started_summary(db, teacher_id, limit=10000):
            for s in w["waiting"]:
                waiting.append({"student": s, "form": w["form"]})
        if q:
            ql = q.lower()
            waiting = [r for r in waiting if ql in (r["student"]["name"] or "").lower()
                       or ql in str(r["student"]["username"] or "").lower() or ql in (r["form"]["title"] or "").lower()]
        waiting.sort(key=lambda r: (r["student"]["name"] or "", r["form"]["title"] or ""))
    else:
        sql = """SELECT a.*, f.title AS form_title, f.pass_percent, u.username, tu.name AS teacher_name,
                 (SELECT GROUP_CONCAT(c.name, '، ') FROM classes c JOIN class_members m ON m.class_id=c.id
                  WHERE m.student_id=a.user_id) AS class_names
                 FROM attempts a JOIN forms f ON f.id=a.form_id
                 LEFT JOIN users u ON u.id=a.user_id LEFT JOIN users tu ON tu.id=f.teacher_id
                 WHERE a.is_preview=0 AND a.status!='in_progress'"""
        args = []
        if kind == "pending":
            sql += " AND a.status='submitted'"
        if teacher_id:
            sql += " AND f.teacher_id=?"
            args.append(teacher_id)
        if q:
            sql += " AND (a.taker_name LIKE ? OR u.username LIKE ? OR f.title LIKE ?)"
            args += [f"%{q}%"] * 3
        sql += " ORDER BY a.submitted_at " + ("ASC" if kind == "pending" else "DESC") + " LIMIT 1000"
        rows = db.execute(sql, args).fetchall()
    counts = _people_counts(db, teacher_id)
    return render_template("teacher/people.html", kind=kind, rows=rows, waiting=waiting, q=q, counts=counts)


def _people_counts(db, teacher_id):
    sql = """SELECT COUNT(*) AS n, SUM(CASE WHEN a.status='submitted' THEN 1 ELSE 0 END) AS p
             FROM attempts a JOIN forms f ON f.id=a.form_id WHERE a.is_preview=0 AND a.status!='in_progress'"""
    row = db.execute(sql + (" AND f.teacher_id=?" if teacher_id else ""), (teacher_id,) if teacher_id else ()).fetchone()
    waiting = not_started_summary(db, teacher_id, limit=10000)
    return {"submissions": row["n"] or 0, "pending": row["p"] or 0,
            "not_started": sum(len(w["waiting"]) for w in waiting)}


@bp.post("/forms/<int:fid>/retake/<int:uid>")
@login_required("staff")
def allow_retake(fid, uid):
    """Give one student one more attempt at an exam (exams are once-only by default)."""
    form = own_form(fid)
    db = get_db()
    student = db.execute("SELECT * FROM users WHERE id=? AND role='student'", (uid,)).fetchone()
    if student is None:
        abort(404)
    if form["max_attempts"]:
        db.execute(
            """INSERT INTO extra_attempts(form_id, user_id, extra) VALUES(?,?,1)
               ON CONFLICT(form_id, user_id) DO UPDATE SET extra=extra_attempts.extra+1""",
            (fid, uid),
        )
        db.commit()
    flash(t("flash_retake", name=student["name"]), "success")
    back = request.form.get("back") or ""
    return redirect(back if back.startswith("/") and not back.startswith("//") else url_for("teacher.submissions", fid=fid))


@bp.post("/forms/<int:fid>/assign-student")
@login_required("staff")
def assign_student(fid):
    """Assign this exam to one specific student (in addition to any assigned classes)."""
    own_form(fid)
    db = get_db()
    sid = request.form.get("student_id", type=int)
    allowed = manageable_student_ids(db)
    if sid and (allowed is None or sid in allowed):
        db.execute("INSERT OR IGNORE INTO form_students(form_id, student_id) VALUES(?,?)", (fid, sid))
        db.commit()
        flash(t("flash_assigned"), "success")
    back = request.form.get("back") or ""
    return redirect(back if back.startswith("/") and not back.startswith("//") else url_for("teacher.submissions", fid=fid))


@bp.post("/forms/<int:fid>/regrade")
@login_required("staff")
def regrade(fid):
    own_form(fid)
    db = get_db()
    regrade_form(db, fid)
    db.commit()
    flash(t("flash_regraded"), "success")
    return redirect(url_for("teacher.submissions", fid=fid))


@bp.get("/attempts/<int:aid>")
@login_required("staff")
def attempt_detail(aid):
    attempt = own_attempt(aid)
    db = get_db()
    form = db.execute("SELECT * FROM forms WHERE id=?", (attempt["form_id"],)).fetchone()
    questions = load_questions(db, form["id"])
    questions = [q for q in questions if q["type"] != "section"]
    answers = {r["question_id"]: r for r in db.execute("SELECT * FROM answers WHERE attempt_id=?", (aid,))}
    events = db.execute("SELECT * FROM events WHERE attempt_id=? ORDER BY at", (aid,)).fetchall()
    student = db.execute("SELECT * FROM users WHERE id=?", (attempt["user_id"],)).fetchone() if attempt["user_id"] else None
    items = []
    for q in questions:
        row = answers.get(q["id"])
        items.append(
            {
                "q": q,
                "answer": row,
                "value": jl(row["value_json"], None) if row else None,
                "max": eff_points(q),
                "manual_type": is_manual(q),
            }
        )
    return render_template(
        "teacher/attempt.html", attempt=attempt, form=form, items=items, events=events, student=student
    )


@bp.post("/attempts/<int:aid>/grade")
@login_required("staff")
def grade_attempt(aid):
    attempt = own_attempt(aid)
    if attempt["status"] == "in_progress":
        abort(400)
    db = get_db()
    questions = load_questions(db, attempt["form_id"])
    for q in questions:
        maximum = eff_points(q)
        row = db.execute(
            "SELECT * FROM answers WHERE attempt_id=? AND question_id=?", (aid, q["id"])
        ).fetchone()
        if row is None:
            continue
        feedback = (request.form.get(f"feedback_{q['id']}") or "").strip()[:2000]
        raw = request.form.get(f"points_{q['id']}", "").strip()
        updates = {"feedback": feedback}
        if maximum > 0 and raw != "":
            try:
                value = max(0.0, min(maximum, round(float(raw.replace(",", ".")), 2)))
            except ValueError:
                value = None
            if value is not None and (is_manual(q) or row["points"] is None or abs(value - row["points"]) > 1e-9):
                updates["points"] = value
                updates["manual"] = 1
        sets = ", ".join(f"{k}=?" for k in updates)
        db.execute(f"UPDATE answers SET {sets} WHERE id=?", (*updates.values(), row["id"]))
    recalc_attempt(db, aid)
    db.commit()
    flash(t("flash_graded"), "success")
    nxt = request.form.get("next_pending")
    if nxt:
        following = db.execute(
            "SELECT id FROM attempts WHERE form_id=? AND status='submitted' AND is_preview=0 AND id!=? ORDER BY submitted_at LIMIT 1",
            (attempt["form_id"], aid),
        ).fetchone()
        if following:
            return redirect(url_for("teacher.attempt_detail", aid=following["id"]))
    return redirect(url_for("teacher.submissions", fid=attempt["form_id"]))


@bp.post("/attempts/<int:aid>/delete")
@login_required("staff")
def delete_attempt(aid):
    attempt = own_attempt(aid)
    if not is_admin():
        abort(403)
    db = get_db()
    _delete_files(db, "attempt_id=?", (aid,))
    db.execute("DELETE FROM attempts WHERE id=?", (aid,))
    db.commit()
    flash(t("flash_attempt_deleted"), "success")
    return redirect(url_for("teacher.submissions", fid=attempt["form_id"]))


@bp.get("/answers/<int:answer_id>/file")
@login_required("staff")
def answer_file(answer_id):
    row = get_db().execute(
        """SELECT an.*, f.teacher_id FROM answers an JOIN attempts a ON a.id=an.attempt_id
           JOIN forms f ON f.id=a.form_id WHERE an.id=?""",
        (answer_id,),
    ).fetchone()
    if row is None or not (is_admin() or row["teacher_id"] == g.user["id"]) or not row["file_path"]:
        abort(404)
    from . import storage

    data, mime = storage.load("answers", row["file_path"])
    if data is None:
        abort(404)
    inline = request.args.get("inline") == "1"
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=not inline, download_name=row["file_name"] or "file")


# ---------------------------------------------------------------- analytics
@bp.get("/forms/<int:fid>/analytics")
@login_required("staff")
def analytics(fid):
    form = own_form(fid)
    db = get_db()
    questions = load_questions(db, fid)
    questions = [q for q in questions if q["type"] != "section"]
    data = form_analytics(db, form, questions)
    top = db.execute(
        """SELECT a.*, u.email FROM attempts a LEFT JOIN users u ON u.id=a.user_id
           WHERE a.form_id=? AND a.is_preview=0 AND a.status!='in_progress' AND a.max_score>0
           ORDER BY a.total_score*1.0/a.max_score DESC, a.submitted_at - a.started_at LIMIT 5""",
        (fid,),
    ).fetchall()
    return render_template("teacher/analytics.html", form=form, data=data, top=top)


def _local(ts):
    if not ts:
        return ""
    offset = timedelta(hours=current_app.config["EXPORT_UTC_OFFSET_HOURS"])
    return (datetime.fromtimestamp(ts, tz=timezone.utc) + offset).strftime("%Y-%m-%d %H:%M")


@bp.get("/forms/<int:fid>/export.xlsx")
@login_required("staff")
def export_xlsx(fid):
    form = own_form(fid)
    db = get_db()
    questions = load_questions(db, fid)
    questions = [q for q in questions if q["type"] != "section"]
    rtl = current_lang() == "ar"
    head_fill = PatternFill("solid", fgColor="1D4ED8")
    head_font = Font(bold=True, color="FFFFFF")
    green = PatternFill("solid", fgColor="DCFCE7")
    red = PatternFill("solid", fgColor="FEE2E2")

    def style_header(ws, row=1):
        for cell in ws[row]:
            cell.fill, cell.font = head_fill, head_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = ws.cell(row=row + 1, column=1)
        ws.sheet_view.rightToLeft = rtl

    def autosize(ws, cap=48):
        for idx, col in enumerate(ws.columns, start=1):
            width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
            ws.column_dimensions[get_column_letter(idx)].width = min(cap, max(10, width + 2))

    attempts = db.execute(
        """SELECT a.*, u.username AS email,
           (SELECT GROUP_CONCAT(c.name, ', ') FROM classes c JOIN class_members m ON m.class_id=c.id
            WHERE m.student_id=a.user_id) AS class_names
           FROM attempts a LEFT JOIN users u ON u.id=a.user_id
           WHERE a.form_id=? AND a.is_preview=0 AND a.status!='in_progress'
           ORDER BY a.taker_name, a.attempt_no""",
        (fid,),
    ).fetchall()
    answers = {}
    for row in db.execute(
        "SELECT an.* FROM answers an JOIN attempts a ON a.id=an.attempt_id WHERE a.form_id=?", (fid,)
    ):
        answers[(row["attempt_id"], row["question_id"])] = row

    wb = Workbook()
    ws = wb.active
    ws.title = t("sheet_results")[:31]
    header = [
        "#", t("col_name"), t("col_username"), t("col_class"), t("col_attempt"), t("col_started"),
        t("col_submitted"), t("col_minutes"), t("col_score"), t("col_max"), t("col_percent"),
        t("col_result"), t("col_status"), t("col_violations"), t("col_flags"),
    ] + [f"Q{i + 1}" for i in range(len(questions))]
    ws.append(header)
    style_header(ws)
    for i, a in enumerate(attempts, start=1):
        percent = pct(a["total_score"], a["max_score"])
        passed = percent >= form["pass_percent"]
        flags = []
        if a["late"]:
            flags.append(t("flag_late"))
        if a["auto_submitted"]:
            flags.append(t("flag_auto"))
        row = [
            i, a["taker_name"], a["email"] or "", a["class_names"] or "", a["attempt_no"],
            _local(a["started_at"]), _local(a["submitted_at"]),
            round((a["submitted_at"] - a["started_at"]) / 60, 1) if a["submitted_at"] else "",
            a["total_score"], a["max_score"], percent,
            t("passed") if passed else t("failed"),
            t("status_graded") if a["status"] == "graded" else t("status_pending"),
            a["violations"], ", ".join(flags),
        ]
        for q in questions:
            ans = answers.get((a["id"], q["id"]))
            row.append(ans["points"] if ans and ans["points"] is not None else "")
        ws.append(row)
        ws.cell(row=ws.max_row, column=12).fill = green if passed else red
    autosize(ws)

    ws2 = wb.create_sheet(t("sheet_answers")[:31])
    ws2.append(["#", t("col_name"), t("col_attempt")] + [f"Q{i + 1}" for i in range(len(questions))])
    style_header(ws2)
    for i, a in enumerate(attempts, start=1):
        row = [i, a["taker_name"], a["attempt_no"]]
        for q in questions:
            ans = answers.get((a["id"], q["id"]))
            row.append(answer_text(q, jl(ans["value_json"], None)) if ans else "")
        ws2.append(row)
    autosize(ws2)

    ws3 = wb.create_sheet(t("sheet_questions")[:31])
    ws3.append(["Q", t("col_question"), t("col_type"), t("col_points"), t("col_correct_answer"), t("col_correct_rate"), t("col_avg_points")])
    style_header(ws3)
    analytics_data = form_analytics(db, form, questions)
    for idx, item in enumerate(analytics_data["questions"], start=1):
        q = item["q"]
        ws3.append(
            [
                f"Q{idx}", q["text"], t("type_" + q["type"]), item["points"], correct_text(q),
                item["correct_rate"] if item["correct_rate"] is not None else "",
                item["avg_points"] if item["avg_points"] is not None else "",
            ]
        )
    autosize(ws3)
    for row in ws3.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    safe = "".join(c for c in form["title"] if c.isalnum() or c in " -_")[:40].strip() or "exam"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{safe}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ------------------------------------------------------------------ classes
def _new_class_code(db):
    while True:
        code = gen_code(6)
        if not db.execute("SELECT 1 FROM classes WHERE join_code=?", (code,)).fetchone():
            return code


@bp.route("/classes", methods=["GET", "POST"])
@login_required("staff")
def classes():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        if not name:
            flash(t("err_class_name"), "error")
        else:
            owner = g.user["id"]
            if is_admin() and request.form.get("teacher_id", type=int):
                owner = request.form.get("teacher_id", type=int)
            db.execute(
                "INSERT INTO classes(teacher_id, name, join_code, created_at) VALUES(?,?,?,?)",
                (owner, name, _new_class_code(db), now()),
            )
            db.commit()
            flash(t("flash_class_created"), "success")
        return redirect(url_for("teacher.classes"))
    ids = [c["id"] for c in visible_classes(db)] or [-1]
    marks = ",".join("?" * len(ids))
    rows = db.execute(
        f"""SELECT c.*, u.name AS teacher_name,
           (SELECT COUNT(*) FROM class_members m WHERE m.class_id=c.id) AS members,
           (SELECT COUNT(*) FROM form_classes fc WHERE fc.class_id=c.id) AS forms_count,
           (SELECT GROUP_CONCAT(t.name, '، ') FROM class_teachers ct JOIN users t ON t.id=ct.teacher_id WHERE ct.class_id=c.id) AS co_teachers
           FROM classes c LEFT JOIN users u ON u.id=c.teacher_id WHERE c.id IN ({marks}) ORDER BY c.name""",
        ids,
    ).fetchall()
    teachers = db.execute("SELECT id, name FROM users WHERE role IN ('teacher','admin') AND active=1 ORDER BY name").fetchall() if is_admin() else []
    return render_template("teacher/classes.html", rows=rows, teachers=teachers)


@bp.route("/classes/<int:cid>", methods=["GET", "POST"])
@login_required("staff")
def class_detail(cid):
    classroom = own_class(cid)
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        if name:
            db.execute("UPDATE classes SET name=? WHERE id=?", (name, cid))
        if is_admin():
            owner = request.form.get("teacher_id", type=int)
            if owner:
                db.execute("UPDATE classes SET teacher_id=? WHERE id=?", (owner, cid))
            db.execute("DELETE FROM class_teachers WHERE class_id=?", (cid,))
            for tid in request.form.getlist("co_teachers"):
                if tid.isdigit():
                    db.execute("INSERT OR IGNORE INTO class_teachers(class_id, teacher_id) VALUES(?,?)", (cid, int(tid)))
        db.commit()
        flash(t("flash_saved"), "success")
        return redirect(url_for("teacher.class_detail", cid=cid))
    members = db.execute(
        """SELECT u.*, (SELECT COUNT(*) FROM attempts a WHERE a.user_id=u.id AND a.is_preview=0 AND a.status!='in_progress') AS exams_taken,
           (SELECT AVG(a.total_score*100.0/a.max_score) FROM attempts a
            WHERE a.user_id=u.id AND a.is_preview=0 AND a.status!='in_progress' AND a.max_score>0) AS avg_pct
           FROM users u JOIN class_members m ON m.student_id=u.id WHERE m.class_id=? ORDER BY u.name""",
        (cid,),
    ).fetchall()
    forms = db.execute(
        """SELECT f.id, f.title, f.status, f.code FROM forms f JOIN form_classes fc ON fc.form_id=f.id
           WHERE fc.class_id=? ORDER BY f.updated_at DESC""",
        (cid,),
    ).fetchall()
    teachers = db.execute("SELECT id, name FROM users WHERE role IN ('teacher','admin') AND active=1 ORDER BY name").fetchall()
    co = {r[0] for r in db.execute("SELECT teacher_id FROM class_teachers WHERE class_id=?", (cid,))}
    owner = db.execute("SELECT name FROM users WHERE id=?", (classroom["teacher_id"],)).fetchone()
    return render_template(
        "teacher/class_detail.html", classroom=classroom, members=members, forms=forms,
        teachers=teachers, co=co, owner=owner, manage_students=is_admin() or flag("teachers_manage_students"),
    )


@bp.post("/classes/<int:cid>/students/<int:sid>/remove")
@login_required("staff")
def remove_student(cid, sid):
    own_class(cid)
    db = get_db()
    db.execute("DELETE FROM class_members WHERE class_id=? AND student_id=?", (cid, sid))
    db.commit()
    flash(t("flash_student_removed"), "success")
    return redirect(url_for("teacher.class_detail", cid=cid))


@bp.post("/classes/<int:cid>/delete")
@login_required("staff")
def delete_class(cid):
    classroom = own_class(cid)
    if not is_admin() and classroom["teacher_id"] != g.user["id"]:
        abort(403)
    db = get_db()
    db.execute("DELETE FROM classes WHERE id=?", (cid,))
    db.commit()
    flash(t("flash_deleted"), "success")
    return redirect(url_for("teacher.classes"))


# ------------------------------------------------------------ question bank
BANK_COLS = "type, text, description, image, audio, points, options_json, correct_json, explanation, partial, manual_grade"


def _bank_row_to_question(row):
    return {
        "type": row["type"], "text": row["text"], "description": row["description"] or "",
        "image": row["image"], "audio": row["audio"], "points": row["points"], "required": 0 if row["type"] == "section" else 1,
        "options": jl(row["options_json"], None), "correct": jl(row["correct_json"], None),
        "explanation": row["explanation"] or "", "partial": row["partial"], "manual_grade": row["manual_grade"],
    }


def bank_add(db, q, subject="", grade="", tags="", shared=1):
    """Store a cleaned question in the bank unless an identical one is already there."""
    values = (
        q["type"], q["text"], q.get("description") or "", q.get("image"), q.get("audio"), q["points"],
        jd(q["options"]) if q.get("options") is not None else None,
        jd(q["correct"]) if q.get("correct") is not None else None,
        q.get("explanation") or "", q.get("partial", 0), 1 if q.get("manual_grade") else 0,
    )
    dup = db.execute(
        """SELECT id FROM question_bank WHERE type=? AND text=? AND IFNULL(description,'')=? AND IFNULL(options_json,'')=IFNULL(?, '')
           AND IFNULL(correct_json,'')=IFNULL(?, '') AND IFNULL(image,'')=IFNULL(?, '')""",
        (values[0], values[1], values[2], values[6], values[7], values[3]),
    ).fetchone()
    if dup:
        return dup["id"], False
    owner = g.user["id"] if g.get("user") is not None else None
    bid = db.execute(
        f"""INSERT INTO question_bank(owner_id, {BANK_COLS}, subject, grade, tags, shared, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (owner,) + values + (subject[:80], grade[:80], tags[:200], 1 if shared else 0, now()),
    ).lastrowid
    return bid, True


def bank_query(db, q="", kind="", subject="", grade="", mine=False, limit=300, ids=None):
    sql = """SELECT b.*, u.name AS owner_name FROM question_bank b LEFT JOIN users u ON u.id=b.owner_id WHERE 1=1"""
    args = []
    if not is_admin():
        sql += " AND (b.shared=1 OR b.owner_id=?)"
        args.append(g.user["id"])
    if mine:
        sql += " AND b.owner_id=?"
        args.append(g.user["id"])
    if ids is not None:
        ids = list(ids) or [-1]
        sql += f" AND b.id IN ({','.join('?' * len(ids))})"
        args += ids
    if q:
        like = f"%{q}%"
        sql += " AND (b.text LIKE ? OR b.description LIKE ? OR b.options_json LIKE ? OR b.tags LIKE ? OR b.subject LIKE ? OR b.grade LIKE ?)"
        args += [like] * 6
    if kind:
        sql += " AND b.type=?"
        args.append(kind)
    if subject:
        sql += " AND b.subject=?"
        args.append(subject)
    if grade:
        sql += " AND b.grade=?"
        args.append(grade)
    return db.execute(sql + f" ORDER BY b.uses DESC, b.created_at DESC LIMIT {int(limit)}", args).fetchall()


def _bank_facets(db, column):
    return [r[0] for r in db.execute(f"SELECT DISTINCT {column} FROM question_bank WHERE {column}!='' ORDER BY 1")]


def _bank_json(row):
    q = _bank_row_to_question(row)
    return {
        "bank_id": row["id"], "subject": row["subject"], "grade": row["grade"], "tags": row["tags"],
        "owner": row["owner_name"] or "", "mine": row["owner_id"] == g.user["id"],
        "type_label": t("type_" + row["type"]), "answer": correct_text(q) if q["type"] not in ("section",) else "",
        **q,
    }


@bp.get("/bank")
@login_required("staff")
def bank():
    db = get_db()
    args = {k: (request.args.get(k) or "").strip() for k in ("q", "type", "subject", "grade")}
    mine = request.args.get("mine") == "1"
    rows = bank_query(db, args["q"], args["type"], args["subject"], args["grade"], mine)
    items = []
    for row in rows:
        q = _bank_row_to_question(row)
        items.append({"row": row, "q": q, "answer": correct_text(q)})
    forms = search_forms(db, limit=500)
    total = db.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
    return render_template(
        "teacher/bank.html", items=items, forms=forms, mine=mine, total=total, types=sorted(TYPES),
        subjects=_bank_facets(db, "subject"), grades=_bank_facets(db, "grade"), **args,
    )


def _selected_bank_ids():
    out = []
    for v in request.form.getlist("ids"):
        if v.isdigit():
            out.append(int(v))
    return out


def _append_bank_questions(db, fid, bank_ids):
    rows = {r["id"]: r for r in bank_query(db, ids=bank_ids, limit=1000)}
    start = db.execute("SELECT COALESCE(MAX(position), -1) + 1 p FROM questions WHERE form_id=?", (fid,)).fetchone()["p"]
    added = 0
    for bid in bank_ids:
        row = rows.get(bid)
        if row is None:
            continue
        insert_question(db, fid, start + added, _bank_row_to_question(row))
        db.execute("UPDATE question_bank SET uses=uses+1 WHERE id=?", (bid,))
        added += 1
    db.execute("UPDATE forms SET updated_at=? WHERE id=?", (now(), fid))
    regrade_form(db, fid)
    return added


@bp.post("/bank/use")
@login_required("staff")
def bank_use():
    """Add the selected bank questions to an existing exam or to a brand-new exam."""
    db = get_db()
    ids = _selected_bank_ids()
    if not ids:
        flash(t("bank_select_first"), "error")
        return redirect(request.referrer or url_for("teacher.bank"))
    fid = request.form.get("fid", type=int)
    if fid:
        own_form(fid)
    else:
        stamp = now()
        title = (request.form.get("title") or "").strip()[:200] or t("untitled_exam")
        fid = db.execute(
            """INSERT INTO forms(teacher_id, code, title, description, subject, grade, show_results, show_answers,
               max_attempts, created_at, updated_at) VALUES(?,?,?,?,?,?, 'after_grading', 1, 1, ?,?)""",
            (g.user["id"], _new_unique_code(db), title, "", request.form.get("subject", "")[:80],
             request.form.get("grade", "")[:80], stamp, stamp),
        ).lastrowid
    added = _append_bank_questions(db, fid, ids)
    db.commit()
    flash(t("bank_added", n=added), "success")
    return redirect(url_for("teacher.edit_form", fid=fid))


@bp.post("/bank/<int:bid>/delete")
@login_required("staff")
def bank_delete(bid):
    db = get_db()
    row = db.execute("SELECT * FROM question_bank WHERE id=?", (bid,)).fetchone()
    if row is None or not (is_admin() or row["owner_id"] == g.user["id"]):
        abort(404)
    db.execute("DELETE FROM question_bank WHERE id=?", (bid,))
    db.commit()
    flash(t("flash_deleted"), "success")
    return redirect(request.referrer or url_for("teacher.bank"))


@bp.post("/bank/<int:bid>/share")
@login_required("staff")
def bank_share(bid):
    db = get_db()
    row = db.execute("SELECT * FROM question_bank WHERE id=?", (bid,)).fetchone()
    if row is None or not (is_admin() or row["owner_id"] == g.user["id"]):
        abort(404)
    db.execute("UPDATE question_bank SET shared=1-shared WHERE id=?", (bid,))
    db.commit()
    return redirect(request.referrer or url_for("teacher.bank"))


@bp.post("/forms/<int:fid>/bank")
@login_required("staff")
def bank_add_form(fid):
    """Save every question of an exam into the bank."""
    form = own_form(fid)
    db = get_db()
    added = 0
    for q in load_questions(db, fid):
        if q["type"] == "section":
            continue
        _bid, new = bank_add(db, q, form["subject"], form["grade"])
        added += 1 if new else 0
    db.commit()
    flash(t("bank_saved_n", n=added), "success")
    back = request.form.get("back") or ""
    return redirect(back if back.startswith("/") and not back.startswith("//") else url_for("teacher.bank"))


@bp.get("/api/bank")
@login_required("staff")
def api_bank():
    db = get_db()
    rows = bank_query(
        db, (request.args.get("q") or "").strip(), request.args.get("type", ""),
        request.args.get("subject", ""), request.args.get("grade", ""), request.args.get("mine") == "1", 200,
    )
    return jsonify(ok=True, items=[_bank_json(r) for r in rows],
                   subjects=_bank_facets(db, "subject"), grades=_bank_facets(db, "grade"))


@bp.post("/api/bank")
@login_required("staff")
def api_bank_save():
    db = get_db()
    data = request.get_json(silent=True) or {}
    try:
        q = clean_question(data.get("question") or {})
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    bid, new = bank_add(db, q, str(data.get("subject") or ""), str(data.get("grade") or ""), str(data.get("tags") or ""))
    db.commit()
    return jsonify(ok=True, id=bid, new=new, message=t("bank_saved") if new else t("bank_exists"))


@bp.post("/api/bank/used")
@login_required("staff")
def api_bank_used():
    db = get_db()
    for bid in (request.get_json(silent=True) or {}).get("ids") or []:
        if isinstance(bid, int):
            db.execute("UPDATE question_bank SET uses=uses+1 WHERE id=?", (bid,))
    db.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------- print
import re as _re

_OWN_NUMBER = _re.compile(r"^\s*(?:[0-9\u0660-\u0669]{1,3}|[A-Za-z\u0621-\u064A]{1,2}[0-9]{0,2})\s*[-.)\u2013:]")


def _paper_lang(form, questions):
    """Print the paper in the exam's own language (an English exam prints left-to-right in English)."""
    text = form["title"] + " " + " ".join(q["text"] for q in questions[:15])
    arabic = len(_re.findall(r"[\u0600-\u06FF]", text))
    latin = len(_re.findall(r"[A-Za-z]", text))
    g.force_lang = "ar" if arabic >= latin * 0.3 else "en"


def _paper_sections(questions, answers=None):
    """Group questions under their section heading and add up each section's marks (for the score table)."""
    sections, current, number = [], None, 0
    for q in questions:
        if q["type"] == "section":
            current = {"q": q, "title": q["text"], "items": [], "max": 0.0, "score": 0.0, "pending": False}
            sections.append(current)
            continue
        if current is None:
            current = {"q": None, "title": "", "items": [], "max": 0.0, "score": 0.0, "pending": False}
            sections.append(current)
        number += 1
        row = answers.get(q["id"]) if answers is not None else None
        item = {"q": q, "n": number, "max": eff_points(q), "answer": row,
                "numbered": bool(_OWN_NUMBER.match(q["text"] or "")),
                "value": jl(row["value_json"], None) if row else None}
        if q["type"] == "fill":
            from .grading import fill_parts

            item["parts"] = fill_parts(q)
        elif q["type"] == "order":
            from .grading import order_chunks

            chunks = order_chunks(q)
            item["chunks"] = sorted(chunks, key=lambda c: (len(c) * 7 + sum(map(ord, c))) % 13)
        elif q["type"] == "match":
            from .grading import match_choices, match_pairs

            item["pairs"] = match_pairs(q)
            item["choices"] = sorted(match_choices(q), key=lambda c: (sum(map(ord, c)) * 31) % 17)
        current["items"].append(item)
        current["max"] += item["max"]
        if row is not None:
            if row["points"] is None and item["max"] > 0:
                current["pending"] = True
            else:
                current["score"] += row["points"] or 0
    return [s for s in sections if s["items"] or s["q"]]


def _score_rows(sections):
    """Rows of the score table: one per titled section; questions outside any section get a row each."""
    rows = []
    for s in sections:
        if s["q"] is not None:
            if s["max"] > 0:
                rows.append({"title": s["title"], "max": s["max"], "score": s["score"], "pending": s["pending"]})
            continue
        for it in s["items"]:
            if it["max"] <= 0:
                continue
            a = it["answer"]
            pending = a is not None and a["points"] is None
            text = " ".join((it["q"]["text"] or "").split())
            rows.append({"title": text[:90] + ("…" if len(text) > 90 else ""), "max": it["max"],
                         "score": (a["points"] or 0) if a is not None else 0, "pending": pending})
    return rows


@bp.get("/forms/<int:fid>/print")
@login_required("staff")
def print_form(fid):
    from .utils import number_words

    form = own_form(fid)
    db = get_db()
    questions = load_questions(db, fid)
    _paper_lang(form, questions)
    sections = _paper_sections(questions)
    total = sum(s["max"] for s in sections)
    teacher = db.execute("SELECT name FROM users WHERE id=?", (form["teacher_id"],)).fetchone()
    return render_template(
        "teacher/print.html", form=form, sections=sections, total=total, attempt=None, teacher=teacher,
        score_rows=_score_rows(sections),
        show_key=request.args.get("key") == "1", words=lambda v: number_words(v, current_lang()),
    )


@bp.get("/attempts/<int:aid>/print")
@login_required("staff")
def print_attempt(aid):
    from .utils import number_words

    attempt = own_attempt(aid)
    db = get_db()
    form = db.execute("SELECT * FROM forms WHERE id=?", (attempt["form_id"],)).fetchone()
    answers = {r["question_id"]: r for r in db.execute("SELECT * FROM answers WHERE attempt_id=?", (aid,))}
    questions = load_questions(db, form["id"])
    _paper_lang(form, questions)
    sections = _paper_sections(questions, answers)
    total = sum(s["max"] for s in sections)
    teacher = db.execute("SELECT name FROM users WHERE id=?", (form["teacher_id"],)).fetchone()
    student = db.execute("SELECT * FROM users WHERE id=?", (attempt["user_id"],)).fetchone() if attempt["user_id"] else None
    classes = db.execute(
        "SELECT GROUP_CONCAT(c.name, '، ') n FROM classes c JOIN class_members m ON m.class_id=c.id WHERE m.student_id=?",
        (attempt["user_id"],),
    ).fetchone()["n"] if attempt["user_id"] else ""
    return render_template(
        "teacher/print.html", form=form, sections=sections, total=total, attempt=attempt, teacher=teacher,
        score_rows=_score_rows(sections),
        student=student, class_names=classes or "", show_key=True, words=lambda v: number_words(v, current_lang()),
    )
