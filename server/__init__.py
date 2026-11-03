import hmac
import os
import secrets
from datetime import datetime, timezone

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from flask.sessions import SecureCookieSessionInterface
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

from .db import close_db, get_db, init_db
from .grading import answer_text, correct_text
from .i18n import current_lang, t
from .utils import fmt_num, jl, pct, safe_next

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("SERVERLESS"))


def _secret_key_from_db():
    """No SECRET_KEY variable on a cloud install: keep one in the database so sessions survive restarts."""
    from .db import connect

    conn = connect()
    row = conn.execute("SELECT value FROM settings WHERE key='_secret'").fetchone()
    if row:
        key = row[0]
    else:
        key = secrets.token_hex(32)
        conn.execute("INSERT INTO settings(key, value) VALUES('_secret', ?) ON CONFLICT(key) DO NOTHING", (key,))
        conn.commit()
        key = conn.execute("SELECT value FROM settings WHERE key='_secret'").fetchone()[0]
    conn.close()
    return key


def _secret_key(instance_path):
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    if SERVERLESS:
        return None
    path = os.path.join(instance_path, "secret_key")
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(key)
    return key


class AdaptiveSessionInterface(SecureCookieSessionInterface):
    """Secure + SameSite=None cookies over HTTPS (works inside embedded previews),
    plain Lax cookies over HTTP so phones and iPads on the school Wi-Fi can log in."""

    def get_cookie_secure(self, app):
        mode = app.config.get("COOKIE_SECURE_MODE", "auto")
        if mode == "always":
            return True
        if mode == "never":
            return False
        return request.is_secure

    def get_cookie_samesite(self, app):
        return "None" if self.get_cookie_secure(app) else "Lax"


def create_app():
    instance = os.environ.get("INSTANCE_DIR") or ("/tmp/exam-instance" if SERVERLESS else os.path.join(ROOT, "instance"))
    app = Flask(__name__, instance_path=instance)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.session_interface = AdaptiveSessionInterface()
    os.makedirs(os.path.join(app.instance_path, "uploads"), exist_ok=True)
    app.config.update(
        SECRET_KEY=_secret_key(app.instance_path),
        DATABASE=os.path.join(app.instance_path, "exams.sqlite3"),
        UPLOAD_DIR=os.path.join(app.instance_path, "uploads"),
        # Vercel accepts request bodies up to 4.5 MB.
        MAX_CONTENT_LENGTH=int(float(os.environ.get("MAX_UPLOAD_MB", "4.4" if SERVERLESS else "200")) * 1024 * 1024),
        BACKUP_DIR=os.path.join(app.instance_path, "backups"),
        MAX_UPLOAD_BYTES=int(float(os.environ.get("MAX_FILE_MB", "4" if SERVERLESS else "5")) * 1024 * 1024),
        SESSION_COOKIE_HTTPONLY=True,
        COOKIE_SECURE_MODE=os.environ.get("SECURE_COOKIES", "auto"),
        PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
        TEACHER_SIGNUP_CODE=os.environ.get("TEACHER_SIGNUP_CODE", ""),
        EXPORT_UTC_OFFSET_HOURS=float(os.environ.get("EXPORT_UTC_OFFSET_HOURS", "3")),
        TEMPLATES_AUTO_RELOAD=not SERVERLESS,
        SEND_FILE_MAX_AGE_DEFAULT=60 * 60 * 24,
    )
    init_db(app.config["DATABASE"])
    if not app.config["SECRET_KEY"]:
        with app.app_context():
            app.config["SECRET_KEY"] = _secret_key_from_db()
    app.teardown_appcontext(close_db)

    from . import admin, auth, exam, qio, teacher, users

    app.register_blueprint(auth.bp)
    app.register_blueprint(teacher.bp)
    app.register_blueprint(exam.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(qio.bp)

    @app.before_request
    def load_user_and_check_csrf():
        g.user = None
        uid = session.get("uid")
        if uid:
            g.user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if g.user is None or not g.user["active"] or session.get("av", 0) != g.user["auth_version"]:
                # deleted, disabled, or password was reset -> must log in again
                g.user = None
                lang = session.get("lang")
                session.clear()
                if lang:
                    session["lang"] = lang
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf", "")
            if not expected or not hmac.compare_digest(str(sent), expected):
                abort(400, description="csrf")

    @app.after_request
    def security_headers(response):
        if response.status_code < 400 and request.endpoint not in (None, "static", "exam.media"):
            from .backup import maybe_auto_backup

            maybe_auto_backup()
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    def _flag(key):
        from .settings import flag

        return flag(key)

    def _fill_bank_words(q):
        from .grading import fill_bank

        return fill_bank(q)

    def _fill_ok(q, index, given):
        from .grading import fill_blanks, loose

        blanks = fill_blanks(q)
        return bool(given) and index < len(blanks) and any(loose(given) == loose(a) for a in blanks[index])

    def _fill_answer(q, index):
        from .grading import fill_blanks

        blanks = fill_blanks(q)
        return blanks[index][0] if index < len(blanks) and blanks[index] else ""

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    app.jinja_env.globals.update(
        t=t, fmt_num=fmt_num, pct=pct, answer_text=answer_text, correct_text=correct_text, csrf_token=csrf_token,
        media_url=lambda name: url_for("exam.media", name=name) if name else "",
        setting_flag=_flag,
        fill_bank_words=_fill_bank_words, fill_ok=_fill_ok, fill_answer=_fill_answer,
    )

    @app.context_processor
    def inject():
        lang = current_lang()
        return {
            "t": t,
            "lang": lang,
            "dir": "rtl" if lang == "ar" else "ltr",
            "csrf_token": csrf_token,
            "user": g.get("user"),
            "is_admin": bool(g.get("user")) and g.user["role"] == "admin",
            "is_staff": bool(g.get("user")) and g.user["role"] in ("admin", "teacher"),
            "setting_flag": _flag,
            "media_url": lambda name: url_for("exam.media", name=name) if name else "",
            "answer_text": answer_text,
            "correct_text": correct_text,
            "fmt_num": fmt_num,
            "pct": pct,
        }

    @app.template_filter("local_time")
    def local_time(ts, fmt="dt"):
        if not ts:
            return "-"
        stamp = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return Markup(f'<time data-ts="{int(ts)}" data-fmt="{escape(fmt)}">{stamp}</time>')

    @app.template_filter("rich")
    def rich(text):
        """Escape, then allow two simple marks used in exams: __underline__ and **bold**."""
        import re as _re

        if not text:
            return ""
        html = str(escape(text))
        html = _re.sub(r"__([^_\s](?:[^\n]*?[^_\s])?)__", r"<u>\1</u>", html)
        html = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
        return Markup(html)

    @app.template_filter("plain")
    def plain(text):
        import re as _re

        return _re.sub(r"__(.+?)__|\*\*(.+?)\*\*", lambda m: m.group(1) or m.group(2), str(text or ""))

    @app.template_filter("duration")
    def duration(seconds):
        if seconds is None:
            return "-"
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    @app.template_filter("fromjson")
    def fromjson(raw):
        return jl(raw, None)

    @app.errorhandler(400)
    def bad_request(err):
        if request.is_json or request.path.startswith("/api") or "/attempt/" in request.path:
            return {"ok": False, "error": t("err_csrf")}, 400
        return render_template("error.html", code=400, message=t("err_csrf")), 400

    @app.errorhandler(403)
    def forbidden(_err):
        return render_template("error.html", code=403, message=t("err_forbidden")), 403

    @app.errorhandler(404)
    def not_found(_err):
        return render_template("error.html", code=404, message=t("err_not_found")), 404

    @app.errorhandler(413)
    def too_large(_err):
        if request.is_json or "/upload/" in request.path or "/api/" in request.path:
            return {"ok": False, "error": t("err_file_too_large")}, 413
        return render_template("error.html", code=413, message=t("err_file_too_large")), 413

    @app.get("/lang/<code>")
    def set_lang(code):
        if code in ("ar", "en"):
            session["lang"] = code
        target = safe_next(request.args.get("next"), url_for("auth.index"))
        return redirect(target)

    # Production by default: an empty school. Set DEMO_SEED=1 to load the demo accounts and exams.
    if os.environ.get("DEMO_SEED", "0") == "1":
        with app.app_context():
            from .seed import seed_demo

            seed_demo(get_db())

    return app
