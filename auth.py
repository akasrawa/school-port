import re
import secrets
import time

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .i18n import t
from .settings import flag
from .utils import clean_username, home_for, login_required, now, safe_next

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_failures = {}
MAX_FAILS, WINDOW = 8, 300
MIN_PASSWORD = 4


def _blocked(key):
    entries = [ts for ts in _failures.get(key, []) if time.time() - ts < WINDOW]
    _failures[key] = entries
    return len(entries) >= MAX_FAILS


def _log_in(user_id):
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    session["uid"] = user_id
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    db = get_db()
    row = db.execute("SELECT auth_version FROM users WHERE id=?", (user_id,)).fetchone()
    session["av"] = row["auth_version"] if row else 0
    db.execute("UPDATE users SET last_login=? WHERE id=?", (now(), user_id))
    db.commit()


def find_user(db, login):
    login = clean_username(login)
    if not login:
        return None
    return db.execute(
        "SELECT * FROM users WHERE username=? OR (email IS NOT NULL AND email!='' AND email=?) ORDER BY id LIMIT 1",
        (login, login),
    ).fetchone()


def username_taken(db, username, exclude_id=None):
    row = db.execute(
        "SELECT id FROM users WHERE (username=? OR (email IS NOT NULL AND email!='' AND email=?)) AND id IS NOT ?",
        (username, username, exclude_id),
    ).fetchone()
    return row is not None


def email_taken(db, email, exclude_id=None):
    if not email:
        return False
    row = db.execute(
        "SELECT id FROM users WHERE (email=? OR username=?) AND id IS NOT ?", (email, email, exclude_id)
    ).fetchone()
    return row is not None


def validate_account(db, name, username, email, password, exclude_id=None, password_required=True):
    """Shared validation for every place that creates or edits a user. Returns an error string or None."""
    if not name:
        return t("err_name_required")
    if not username:
        return t("err_username_required")
    if email and not EMAIL_RE.match(email):
        return t("err_email_invalid")
    if username_taken(db, username, exclude_id):
        return t("err_username_taken", username=username)
    if email and email_taken(db, email, exclude_id):
        return t("err_email_taken")
    if (password_required or password) and len(password or "") < MIN_PASSWORD:
        return t("err_password_short")
    return None


def create_user(db, name, username, password, role, email=None, created_by=None):
    return db.execute(
        """INSERT INTO users(name, username, email, password_hash, role, created_by, created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (name[:100], username, email or None, generate_password_hash(password), role, created_by, now()),
    ).lastrowid


def admin_exists(db):
    return db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone() is not None


@bp.route("/")
def index():
    db = get_db()
    if g.user:
        return redirect(home_for(g.user))
    if not admin_exists(db) and not db.execute("SELECT 1 FROM users").fetchone():
        return redirect(url_for("auth.setup"))
    demo = db.execute("SELECT COUNT(*) c FROM users WHERE username='admin' AND email='admin@school.test'").fetchone()
    return render_template("index.html", demo=bool(demo["c"]), signup=flag("allow_student_signup") or flag("allow_teacher_signup"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))
    db = get_db()
    nxt = safe_next(request.values.get("next"))
    if request.method == "POST":
        login_value = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        key = f"{request.remote_addr}|{login_value.lower()}"
        if _blocked(key):
            flash(t("flash_too_many_logins"), "error")
        else:
            row = find_user(db, login_value)
            if row and check_password_hash(row["password_hash"], password):
                if not row["active"]:
                    flash(t("flash_account_disabled"), "error")
                else:
                    _failures.pop(key, None)
                    _log_in(row["id"])
                    return redirect(nxt or home_for(row))
            else:
                _failures.setdefault(key, []).append(time.time())
                flash(t("flash_bad_login"), "error")
    demo = db.execute("SELECT COUNT(*) c FROM users WHERE username='admin' AND email='admin@school.test'").fetchone()
    return render_template(
        "auth/login.html",
        next=nxt,
        demo=bool(demo["c"]),
        signup=flag("allow_student_signup") or flag("allow_teacher_signup"),
    )


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(home_for(g.user))
    db = get_db()
    allowed = [r for r in ("student", "teacher") if flag(f"allow_{r}_signup")]
    if not allowed:
        flash(t("signup_closed"), "info")
        return redirect(url_for("auth.login"))
    role = request.values.get("role", allowed[0])
    role = role if role in allowed else allowed[0]
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        username = clean_username(request.form.get("username"))
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        join_code = request.form.get("join_code", "").strip().lower()
        error = validate_account(db, name, username, email, password)
        classroom = None
        if not error and role == "student" and join_code:
            classroom = db.execute("SELECT * FROM classes WHERE join_code=?", (join_code,)).fetchone()
            if classroom is None:
                error = t("err_class_code")
        if error:
            flash(error, "error")
        else:
            uid = create_user(db, name, username, password, role, email)
            if classroom:
                db.execute("INSERT OR IGNORE INTO class_members(class_id, student_id) VALUES(?,?)", (classroom["id"], uid))
            db.commit()
            _log_in(uid)
            flash(t("flash_welcome", name=name), "success")
            return redirect(safe_next(request.form.get("next")) or home_for({"role": role}))
    return render_template("auth/register.html", role=role, allowed=allowed, next=safe_next(request.values.get("next")))


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """First-run: create the principal (admin) account. Only possible while no admin exists."""
    db = get_db()
    if admin_exists(db):
        abort(404)
    has_users = db.execute("SELECT 1 FROM users").fetchone() is not None
    if has_users and (g.user is None or g.user["role"] != "teacher"):
        flash(t("setup_login_teacher"), "info")
        return redirect(url_for("auth.login", next=url_for("auth.setup")))
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        username = clean_username(request.form.get("username"))
        password = request.form.get("password", "")
        error = validate_account(db, name, username, "", password)
        if not error and len(password) < 6:
            error = t("err_password_short_admin")
        if error:
            flash(error, "error")
        else:
            uid = create_user(db, name, username, password, "admin")
            db.commit()
            _log_in(uid)
            flash(t("flash_welcome", name=name), "success")
            return redirect(url_for("admin.dashboard"))
    return render_template("auth/setup.html")


@bp.post("/logout")
def logout():
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    return redirect(url_for("auth.index"))


@bp.route("/account", methods=["GET", "POST"])
@login_required()
def account():
    if request.method == "POST":
        db = get_db()
        name = request.form.get("name", "").strip()[:100]
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        if not name:
            flash(t("err_name_required"), "error")
        elif new and not check_password_hash(g.user["password_hash"], current):
            flash(t("err_current_password"), "error")
        elif new and len(new) < MIN_PASSWORD:
            flash(t("err_password_short"), "error")
        else:
            if new:
                db.execute(
                    "UPDATE users SET name=?, password_hash=?, auth_version=auth_version+1 WHERE id=?",
                    (name, generate_password_hash(new), g.user["id"]),
                )
                session["av"] = g.user["auth_version"] + 1  # stay logged in here, sign out other devices
            else:
                db.execute("UPDATE users SET name=? WHERE id=?", (name, g.user["id"]))
            db.commit()
            flash(t("flash_saved"), "success")
            return redirect(url_for("auth.account"))
    return render_template("auth/account.html")
