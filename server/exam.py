import io
import os
import random
import re
import uuid

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
    session,
    url_for,
)

from .access import allowed_attempts, is_admin
from .db import get_db
from .grading import (
    INFO,
    eff_points,
    fill_bank,
    fill_blanks,
    fill_parts,
    finalize_attempt,
    is_empty,
    load_questions,
    match_choices,
    match_pairs,
    option_order,
    order_chunks,
    ordered_questions,
)
from .i18n import t
from .utils import jd, jl, login_required, now

bp = Blueprint("exam", __name__)

GRACE_SECONDS = 20
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "docx", "doc", "txt", "zip", "xlsx", "pptx"}
COUNTED_EVENTS = {"tab_hidden", "window_blur", "fullscreen_exit"}
ALL_EVENTS = COUNTED_EVENTS | {"copy_attempt", "paste_attempt", "menu_attempt", "fullscreen_enter"}


# ------------------------------------------------------------------ helpers
def get_form_by_code(code):
    row = get_db().execute("SELECT * FROM forms WHERE code=?", (code.lower(),)).fetchone()
    if row is None:
        abort(404)
    return row


def is_owner(form):
    if g.user is None:
        return False
    return g.user["role"] == "admin" or (g.user["role"] == "teacher" and form["teacher_id"] == g.user["id"])


def form_state(form):
    if form["status"] == "draft":
        return "draft"
    if form["status"] == "closed":
        return "closed"
    stamp = now()
    if form["opens_at"] and stamp < form["opens_at"]:
        return "not_open"
    if form["closes_at"] and stamp > form["closes_at"]:
        return "ended"
    return "open"


def has_access(form):
    """Returns None when allowed, otherwise a translation key explaining why not."""
    if is_owner(form):
        return None
    if g.user is not None and g.user["role"] == "teacher":
        return "access_teacher"
    if form["require_login"] and g.user is None:
        return "login"
    db = get_db()
    assigned = db.execute(
        "SELECT (SELECT COUNT(*) FROM form_classes WHERE form_id=?) + (SELECT COUNT(*) FROM form_students WHERE form_id=?) c",
        (form["id"], form["id"]),
    ).fetchone()["c"]
    if assigned and g.user is not None:
        member = db.execute(
            """SELECT 1 FROM form_classes fc JOIN class_members m ON m.class_id=fc.class_id
               WHERE fc.form_id=? AND m.student_id=?
               UNION SELECT 1 FROM form_students WHERE form_id=? AND student_id=?""",
            (form["id"], g.user["id"], form["id"], g.user["id"]),
        ).fetchone()
        if not member:
            return "access_class"
    if assigned and g.user is None:
        return "login"
    return None


def deadline_for(form, started, preview):
    candidates = []
    if form["time_limit_min"] > 0:
        candidates.append(started + form["time_limit_min"] * 60)
    if form["closes_at"] and not preview:
        candidates.append(form["closes_at"])
    return min(candidates) if candidates else None


def guest_attempts():
    return session.get("guest_attempts", [])


def get_attempt_or_404(aid):
    row = get_db().execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
    if row is None:
        abort(404)
    form = get_db().execute("SELECT * FROM forms WHERE id=?", (row["form_id"],)).fetchone()
    owner = g.user is not None and (row["user_id"] == g.user["id"] or is_owner(form))
    guest = row["user_id"] is None and aid in guest_attempts()
    if not (owner or guest):
        abort(404)
    return row, form


def remaining_seconds(attempt):
    if not attempt["deadline_at"]:
        return None
    return attempt["deadline_at"] - now()


def expire_if_needed(attempt):
    """Finalise an in-progress attempt whose server-side deadline has passed."""
    if attempt["status"] == "in_progress" and attempt["deadline_at"] and now() > attempt["deadline_at"]:
        finalize_attempt(get_db(), attempt, auto=True, late=False)
        return True
    return False


def store_answers(db, attempt, questions, payload):
    by_id = {q["id"]: q for q in questions}
    for key, value in (payload or {}).items():
        try:
            qid = int(key)
        except (TypeError, ValueError):
            continue
        q = by_id.get(qid)
        if q is None or q["type"] in ("file", "draw"):
            continue
        value = _clean_value(q, value)
        db.execute(
            """INSERT INTO answers(attempt_id, question_id, value_json) VALUES(?,?,?)
               ON CONFLICT(attempt_id, question_id) DO UPDATE SET value_json=excluded.value_json""",
            (attempt["id"], qid, jd(value) if value is not None else None),
        )


def _clean_value(q, value):
    kind = q["type"]
    if is_empty(value):
        return None
    if kind in ("mcq", "dropdown"):
        try:
            index = int(value)
        except (TypeError, ValueError):
            return None
        return index if 0 <= index < len(q["options"] or []) else None
    if kind == "checkbox":
        if not isinstance(value, list):
            return None
        size = len(q["options"] or [])
        picked = sorted({int(i) for i in value if str(i).lstrip("-").isdigit() and 0 <= int(i) < size})
        return picked or None
    if kind == "truefalse":
        return str(value) if str(value) in ("true", "false") else None
    if kind == "scale":
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if 1 <= number <= int((q["options"] or {}).get("max", 5)) else None
    if kind == "date":
        text = str(value)
        return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None
    if kind in ("match", "fill"):
        if not isinstance(value, list):
            return None
        size = len(match_pairs(q)) if kind == "match" else len(fill_blanks(q))
        cleaned = [str(v).strip()[:300] if v is not None else "" for v in value[:size]]
        cleaned += [""] * (size - len(cleaned))
        if kind == "match":
            allowed = set(match_choices(q))
            cleaned = [v if v in allowed else "" for v in cleaned]
        return None if all(v == "" for v in cleaned) else cleaned
    if kind == "section":
        return None
    return str(value)[:10000]


def missing_required(db, attempt, questions):
    saved = {
        r["question_id"]: r
        for r in db.execute("SELECT * FROM answers WHERE attempt_id=?", (attempt["id"],))
    }
    missing = []
    for q in questions:
        if not q["required"]:
            continue
        row = saved.get(q["id"])
        if q["type"] in ("file", "draw"):
            ok = bool(row and row["file_path"])
        else:
            ok = bool(row) and not is_empty(jl(row["value_json"], None))
        if not ok:
            missing.append(q["id"])
    return missing


@bp.get("/media/<path:name>")
def media(name):
    """Question images uploaded by teachers (random file names)."""
    from flask import send_file

    from . import storage

    data, mime = storage.load("media", name)
    if data is None:
        abort(404)
    response = send_file(io.BytesIO(data), mimetype=mime, max_age=60 * 60 * 24 * 30)
    response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
    return response


# ------------------------------------------------------- student dashboard
@bp.get("/student")
@login_required("student")
def student_dashboard():
    db = get_db()
    uid = g.user["id"]
    classes = db.execute(
        """SELECT c.*, u.name AS teacher_name FROM classes c JOIN class_members m ON m.class_id=c.id
           JOIN users u ON u.id=c.teacher_id WHERE m.student_id=? ORDER BY c.name""",
        (uid,),
    ).fetchall()
    q = (request.args.get("q") or "").strip()
    sql = """SELECT f.*, u.name AS teacher_name,
           (SELECT COUNT(*) FROM questions q WHERE q.form_id=f.id AND q.type!='section') AS qcount,
           (SELECT COUNT(*) FROM attempts a WHERE a.form_id=f.id AND a.user_id=? AND a.is_preview=0 AND a.status!='in_progress') AS used,
           (SELECT id FROM attempts a WHERE a.form_id=f.id AND a.user_id=? AND a.status='in_progress' LIMIT 1) AS running_id,
           (SELECT extra FROM extra_attempts e WHERE e.form_id=f.id AND e.user_id=?) AS extra
           FROM forms f JOIN users u ON u.id=f.teacher_id
           WHERE f.status IN ('published','closed') AND f.id IN (
             SELECT fc.form_id FROM form_classes fc JOIN class_members m ON m.class_id=fc.class_id WHERE m.student_id=?
             UNION SELECT form_id FROM form_students WHERE student_id=?)"""
    args = [uid, uid, uid, uid, uid]
    if q:
        sql += " AND (f.title LIKE ? OR f.subject LIKE ? OR f.grade LIKE ? OR u.name LIKE ? OR f.code LIKE ?)"
        args += [f"%{q}%"] * 5
    forms = db.execute(sql + " ORDER BY f.updated_at DESC", args).fetchall()
    cards = []
    for f in forms:
        allowed = (f["max_attempts"] + (f["extra"] or 0)) if f["max_attempts"] else 0
        state = form_state(f)
        cards.append({
            "form": f, "state": state, "allowed": allowed,
            "can_start": state == "open" and (not allowed or f["used"] < allowed),
            "todo": state == "open" and not f["used"] and not f["running_id"],
        })
    cards.sort(key=lambda c: (not c["form"]["running_id"], not c["can_start"], c["state"] != "open"))
    results = db.execute(
        """SELECT a.*, f.title, f.show_results, f.pass_percent FROM attempts a JOIN forms f ON f.id=a.form_id
           WHERE a.user_id=? AND a.is_preview=0 AND a.status!='in_progress' ORDER BY a.submitted_at DESC LIMIT 20""",
        (uid,),
    ).fetchall()
    return render_template("student/dashboard.html", classes=classes, cards=cards, results=results, q=q)


@bp.post("/student/join")
@login_required("student")
def join_class():
    from .settings import flag

    if not flag("allow_student_signup"):
        flash(t("flash_forbidden"), "error")
        return redirect(url_for("exam.student_dashboard"))
    code = request.form.get("join_code", "").strip().lower()
    db = get_db()
    classroom = db.execute("SELECT * FROM classes WHERE join_code=?", (code,)).fetchone()
    if classroom is None:
        flash(t("err_class_code"), "error")
    else:
        db.execute(
            "INSERT OR IGNORE INTO class_members(class_id, student_id) VALUES(?,?)",
            (classroom["id"], g.user["id"]),
        )
        db.commit()
        flash(t("flash_joined", name=classroom["name"]), "success")
    return redirect(url_for("exam.student_dashboard"))


# -------------------------------------------------------------- exam landing
@bp.get("/f/<code>")
def landing(code):
    form = get_form_by_code(code)
    db = get_db()
    owner = is_owner(form)
    state = form_state(form)
    reason = has_access(form)
    questions = [q for q in load_questions(db, form["id"]) if q["type"] != "section"]
    total_points = sum(eff_points(q) for q in questions)
    attempts = []
    running = None
    if g.user is not None:
        attempts = db.execute(
            "SELECT * FROM attempts WHERE form_id=? AND user_id=? AND is_preview=? ORDER BY id DESC",
            (form["id"], g.user["id"], 1 if owner else 0),
        ).fetchall()
        running = next((a for a in attempts if a["status"] == "in_progress"), None)
    elif guest_attempts():
        running = db.execute(
            "SELECT * FROM attempts WHERE form_id=? AND status='in_progress' AND id IN (%s)"
            % ",".join("?" * len(guest_attempts())),
            [form["id"], *guest_attempts()],
        ).fetchone()
    used = sum(1 for a in attempts if a["status"] != "in_progress" and not a["is_preview"])
    allowed = allowed_attempts(db, form, g.user["id"]) if g.user is not None else form["max_attempts"]
    exhausted = bool(allowed) and used >= allowed and not owner
    return render_template(
        "exam/landing.html",
        form=form,
        state=state,
        reason=reason,
        owner=owner,
        questions=questions,
        total_points=total_points,
        attempts=attempts,
        running=running,
        used=used,
        exhausted=exhausted,
        allowed=allowed,
        teacher=db.execute("SELECT name FROM users WHERE id=?", (form["teacher_id"],)).fetchone(),
    )


@bp.post("/f/<code>/start")
def start(code):
    form = get_form_by_code(code)
    db = get_db()
    owner = is_owner(form)
    back = url_for("exam.landing", code=form["code"])
    if not owner:
        if form_state(form) != "open":
            flash(t("exam_unavailable"), "error")
            return redirect(back)
        if has_access(form):
            return redirect(back)
    user_id = g.user["id"] if g.user else None
    if g.user:
        existing = db.execute(
            "SELECT * FROM attempts WHERE form_id=? AND user_id=? AND status='in_progress' AND is_preview=?",
            (form["id"], user_id, 1 if owner else 0),
        ).fetchone()
        used = db.execute(
            "SELECT COUNT(*) c FROM attempts WHERE form_id=? AND user_id=? AND is_preview=0 AND status!='in_progress'",
            (form["id"], user_id),
        ).fetchone()["c"]
        name = g.user["name"]
    else:
        existing, used = None, 0
        name = request.form.get("taker_name", "").strip()[:100]
        if not name:
            flash(t("err_name_required"), "error")
            return redirect(back)
        ids = guest_attempts()
        if ids:
            existing = db.execute(
                "SELECT * FROM attempts WHERE form_id=? AND status='in_progress' AND id IN (%s)"
                % ",".join("?" * len(ids)),
                [form["id"], *ids],
            ).fetchone()
        used = (
            db.execute(
                "SELECT COUNT(*) c FROM attempts WHERE form_id=? AND id IN (%s) AND status!='in_progress'"
                % ",".join("?" * len(ids)),
                [form["id"], *ids],
            ).fetchone()["c"]
            if ids
            else 0
        )
    if existing:
        return redirect(url_for("exam.take", aid=existing["id"]))
    limit = allowed_attempts(db, form, user_id) if user_id else form["max_attempts"]
    if not owner and limit and used >= limit:
        flash(t("no_attempts_left"), "error")
        return redirect(back)
    count = db.execute("SELECT COUNT(*) c FROM questions WHERE form_id=? AND type!='section'", (form["id"],)).fetchone()["c"]
    if count == 0:
        flash(t("exam_unavailable"), "error")
        return redirect(back)
    started = now()
    cur = db.execute(
        """INSERT INTO attempts(form_id, user_id, taker_name, attempt_no, started_at, deadline_at, is_preview, seed)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            form["id"], user_id, name, used + 1, started,
            deadline_for(form, started, owner), 1 if owner else 0, random.randint(1, 2**30),
        ),
    )
    db.commit()
    if not g.user:
        session["guest_attempts"] = guest_attempts() + [cur.lastrowid]
    return redirect(url_for("exam.take", aid=cur.lastrowid))


# --------------------------------------------------------------- taking exam
@bp.get("/attempt/<int:aid>")
def take(aid):
    attempt, form = get_attempt_or_404(aid)
    if expire_if_needed(attempt) or attempt["status"] != "in_progress":
        return redirect(url_for("exam.result", aid=aid))
    db = get_db()
    questions = ordered_questions(load_questions(db, form["id"]), attempt, form)
    saved = {}
    files = {}
    for row in db.execute("SELECT * FROM answers WHERE attempt_id=?", (aid,)):
        saved[row["question_id"]] = jl(row["value_json"], None)
        if row["file_name"]:
            files[row["question_id"]] = row["file_name"]
    number = 0
    for q in questions:
        q["order"] = option_order(q, attempt, form) if isinstance(q["options"], list) else []
        if q["type"] != "section":
            number += 1
            q["number"] = number
        rng = random.Random(attempt["seed"] * 31 + q["id"])
        if q["type"] == "match":
            q["pairs"] = match_pairs(q)
            choices = match_choices(q)
            rng.shuffle(choices)
            q["choices"] = choices
        elif q["type"] == "fill":
            q["parts"] = fill_parts(q)
            q["bank"] = fill_bank(q)
            q["blank_count"] = len(fill_blanks(q))
        elif q["type"] == "order":
            chunks = list(enumerate(order_chunks(q)))
            for _ in range(5):
                rng.shuffle(chunks)
                if len(chunks) < 2 or [c[0] for c in chunks] != sorted(c[0] for c in chunks):
                    break
            q["chunks"] = [c[1] for c in chunks]
            q["dir"] = "rtl" if re.search("[\u0600-\u06FF]", " ".join(q["chunks"])) else "ltr"
        if q["type"] == "fill":
            q["dir"] = "rtl" if re.search("[\u0600-\u06FF]", (q["options"] or {}).get("template", "")) else "ltr"
    config = {
        "saveUrl": url_for("exam.save", aid=aid),
        "submitUrl": url_for("exam.submit", aid=aid),
        "eventUrl": url_for("exam.event", aid=aid),
        "uploadUrl": url_for("exam.upload", aid=aid, qid=0),
        "fileUrl": url_for("exam.attempt_file", aid=aid, qid=0),
        "resultUrl": url_for("exam.result", aid=aid),
        "remaining": remaining_seconds(attempt),
        "detectTabs": bool(form["detect_tabs"]) and not attempt["is_preview"],
        "blockCopy": bool(form["block_copy"]) and not attempt["is_preview"],
        "fullscreen": bool(form["require_fullscreen"]) and not attempt["is_preview"],
        "maxViolations": form["max_violations"],
        "violations": attempt["violations"],
        "preview": bool(attempt["is_preview"]),
        "total": number,
    }
    return render_template(
        "exam/take.html",
        form=form,
        attempt=attempt,
        questions=questions,
        saved=saved,
        files=files,
        config=config,
    )


def _active_attempt(aid):
    attempt, form = get_attempt_or_404(aid)
    if attempt["status"] != "in_progress":
        return attempt, form, jsonify(ok=False, done=True, redirect=url_for("exam.result", aid=aid))
    if expire_if_needed(attempt):
        return attempt, form, jsonify(ok=False, done=True, redirect=url_for("exam.result", aid=aid))
    return attempt, form, None


@bp.post("/attempt/<int:aid>/save")
def save(aid):
    attempt, form, done = _active_attempt(aid)
    if done:
        return done
    db = get_db()
    payload = request.get_json(silent=True) or {}
    store_answers(db, attempt, load_questions(db, form["id"]), payload.get("answers"))
    db.commit()
    return jsonify(ok=True, remaining=remaining_seconds(attempt))


@bp.post("/attempt/<int:aid>/submit")
def submit(aid):
    attempt, form = get_attempt_or_404(aid)
    if attempt["status"] != "in_progress":
        return jsonify(ok=True, redirect=url_for("exam.result", aid=aid))
    db = get_db()
    payload = request.get_json(silent=True) or {}
    questions = load_questions(db, form["id"])
    stamp = now()
    late = bool(attempt["deadline_at"]) and stamp > attempt["deadline_at"]
    within_grace = not attempt["deadline_at"] or stamp <= attempt["deadline_at"] + GRACE_SECONDS
    auto = bool(payload.get("auto")) or late
    if within_grace:
        store_answers(db, attempt, questions, payload.get("answers"))
        db.commit()
    if not auto:
        missing = missing_required(db, attempt, questions)
        if missing:
            return jsonify(ok=False, missing=missing, error=t("err_required_missing")), 400
    finalize_attempt(db, attempt, auto=auto, late=late and not within_grace)
    return jsonify(ok=True, redirect=url_for("exam.result", aid=aid))


@bp.post("/attempt/<int:aid>/event")
def event(aid):
    attempt, form, done = _active_attempt(aid)
    if done:
        return done
    if attempt["is_preview"]:
        return jsonify(ok=True, violations=0)
    payload = request.get_json(silent=True) or {}
    kind = payload.get("type")
    if kind not in ALL_EVENTS:
        return jsonify(ok=False), 400
    db = get_db()
    db.execute(
        "INSERT INTO events(attempt_id, type, detail, at) VALUES(?,?,?,?)",
        (aid, kind, str(payload.get("detail") or "")[:200], now()),
    )
    violations = attempt["violations"]
    if kind in COUNTED_EVENTS and form["detect_tabs"]:
        violations += 1
        db.execute("UPDATE attempts SET violations=? WHERE id=?", (violations, aid))
    db.commit()
    terminated = bool(form["max_violations"]) and violations >= form["max_violations"] and form["detect_tabs"]
    if terminated:
        fresh = db.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
        finalize_attempt(db, fresh, auto=True)
    return jsonify(
        ok=True,
        violations=violations,
        terminated=terminated,
        redirect=url_for("exam.result", aid=aid) if terminated else None,
    )


@bp.post("/attempt/<int:aid>/upload/<int:qid>")
def upload(aid, qid):
    attempt, form, done = _active_attempt(aid)
    if done:
        return done
    from . import storage

    db = get_db()
    question = db.execute(
        "SELECT * FROM questions WHERE id=? AND form_id=? AND type IN ('file','draw')", (qid, form["id"])
    ).fetchone()
    file = request.files.get("file")
    if question is None or file is None or not file.filename:
        return jsonify(ok=False, error=t("err_upload")), 400
    original = os.path.basename(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if question["type"] == "draw":
        original, ext = "handwriting.png", "png"
        if request.form.get("clear") == "1":
            old = db.execute("SELECT file_path FROM answers WHERE attempt_id=? AND question_id=?", (aid, qid)).fetchone()
            if old and old["file_path"]:
                storage.delete("answers", old["file_path"])
            db.execute("UPDATE answers SET file_path=NULL, file_name=NULL, value_json=NULL WHERE attempt_id=? AND question_id=?", (aid, qid))
            db.commit()
            return jsonify(ok=True, name="")
    if ext not in ALLOWED_EXT:
        return jsonify(ok=False, error=t("err_file_type", types=", ".join(sorted(ALLOWED_EXT)))), 400
    data = file.read()
    if len(data) > current_app.config["MAX_UPLOAD_BYTES"]:
        return jsonify(ok=False, error=t("err_file_too_large")), 413
    stored = f"{aid}_{qid}_{uuid.uuid4().hex}.{ext}"
    old = db.execute(
        "SELECT file_path FROM answers WHERE attempt_id=? AND question_id=?", (aid, qid)
    ).fetchone()
    if old and old["file_path"]:
        storage.delete("answers", old["file_path"])
    storage.save("answers", stored, data, "image/png" if ext == "png" else None)
    db.execute(
        """INSERT INTO answers(attempt_id, question_id, value_json, file_path, file_name) VALUES(?,?,?,?,?)
           ON CONFLICT(attempt_id, question_id) DO UPDATE SET
           value_json=excluded.value_json, file_path=excluded.file_path, file_name=excluded.file_name""",
        (aid, qid, jd("uploaded"), stored, original[:200]),
    )
    db.commit()
    return jsonify(ok=True, name=original[:200])


@bp.get("/attempt/<int:aid>/file/<int:qid>")
def attempt_file(aid, qid):
    """The student's own uploaded file / handwriting (also visible to the exam's teacher)."""
    attempt, _form = get_attempt_or_404(aid)
    row = get_db().execute(
        "SELECT * FROM answers WHERE attempt_id=? AND question_id=? AND file_path IS NOT NULL", (aid, qid)
    ).fetchone()
    if row is None:
        abort(404)
    from flask import send_file

    from . import storage

    data, mime = storage.load("answers", row["file_path"])
    if data is None:
        abort(404)
    inline = row["file_path"].rsplit(".", 1)[-1].lower() in ("png", "jpg", "jpeg", "gif", "webp")
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=not inline, download_name=row["file_name"] or "file", max_age=0)


# -------------------------------------------------------------------- result
@bp.get("/attempt/<int:aid>/result")
def result(aid):
    attempt, form = get_attempt_or_404(aid)
    if expire_if_needed(attempt):
        attempt, form = get_attempt_or_404(aid)
    if attempt["status"] == "in_progress":
        return redirect(url_for("exam.take", aid=aid))
    db = get_db()
    viewer_is_teacher = g.user is not None and g.user["role"] == "teacher"
    show_score = viewer_is_teacher or form["show_results"] == "immediate" or (
        form["show_results"] == "after_grading" and attempt["status"] == "graded"
    )
    show_review = show_score and bool(form["show_answers"] or viewer_is_teacher)
    items = []
    if show_review:
        answers = {r["question_id"]: r for r in db.execute("SELECT * FROM answers WHERE attempt_id=?", (aid,))}
        for q in ordered_questions(load_questions(db, form["id"]), attempt, form):
            if q["type"] == "section":
                continue
            row = answers.get(q["id"])
            items.append(
                {
                    "q": q,
                    "value": jl(row["value_json"], None) if row else None,
                    "answer": row,
                    "max": eff_points(q),
                    "info": q["type"] in INFO,
                }
            )
    attempts_used = db.execute(
        "SELECT COUNT(*) c FROM attempts WHERE form_id=? AND user_id IS ? AND is_preview=0 AND status!='in_progress'",
        (form["id"], attempt["user_id"]),
    ).fetchone()["c"]
    limit = allowed_attempts(db, form, attempt["user_id"]) if attempt["user_id"] else form["max_attempts"]
    can_retry = (
        attempt["user_id"] is not None
        and form_state(form) == "open"
        and (not limit or attempts_used < limit)
    ) or bool(attempt["is_preview"])
    return render_template(
        "exam/result.html",
        form=form,
        attempt=attempt,
        show_score=show_score,
        show_review=show_review,
        items=items,
        can_retry=can_retry,
    )
