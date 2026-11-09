import functools
import json
import secrets
import time

from flask import abort, flash, g, redirect, request, url_for

from .i18n import t

CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def now():
    return int(time.time())


def jl(raw, default=None):
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def jd(obj):
    return json.dumps(obj, ensure_ascii=False)


def gen_code(length=8):
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def safe_next(url, fallback=None):
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return fallback


def home_for(user):
    if user is None:
        return url_for("auth.index")
    if user["role"] == "admin":
        return url_for("admin.dashboard")
    if user["role"] == "teacher":
        return url_for("teacher.dashboard")
    return url_for("exam.student_dashboard")


def login_required(role=None):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash(t("flash_login_required"), "error")
                target = request.full_path.rstrip("?")
                return redirect(url_for("auth.login", next=target))
            allowed = ("admin", "teacher") if role == "staff" else ((role,) if isinstance(role, str) else role)
            if role and g.user["role"] not in allowed:
                flash(t("flash_forbidden"), "error")
                return redirect(home_for(g.user))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def fmt_num(value):
    if value is None:
        return "-"
    value = round(float(value), 2)
    if value == int(value):
        return str(int(value))
    return ("%.2f" % value).rstrip("0").rstrip(".")


def pct(score, maximum):
    if not maximum:
        return 0.0
    return round(float(score) / float(maximum) * 100, 1)


def get_or_404(row):
    if row is None:
        abort(404)
    return row


def gen_password(length=6):
    """Easy-to-type password for young students (digits + lowercase, no look-alikes)."""
    return "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(length))


_DIGITS_IN = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def latin_digits(value):
    """Arabic-Indic digits and the Arabic decimal mark → 0-9 and "." (number fields follow the interface's digits)."""
    return str(value or "").translate(_DIGITS_IN).replace("٫", ".").replace(",", ".")


def clean_username(value):
    # usernames are stored with 0-9 digits; phones with an Arabic keyboard may type ٠-٩
    return " ".join(str(value or "").translate(_DIGITS_IN).split())[:80]


_AR_ONES = ["صفر", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة",
            "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_AR_TENS = {20: "عشرون", 30: "ثلاثون", 40: "أربعون", 50: "خمسون", 60: "ستون", 70: "سبعون", 80: "ثمانون", 90: "تسعون"}
_AR_HUNDREDS = {100: "مائة", 200: "مائتان", 300: "ثلاثمائة", 400: "أربعمائة", 500: "خمسمائة", 600: "ستمائة",
                700: "سبعمائة", 800: "ثمانمائة", 900: "تسعمائة"}
_EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
            "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


def _ar_int(n):
    if n < 20:
        return _AR_ONES[n]
    if n < 100:
        tens, ones = n - n % 10, n % 10
        return _AR_TENS[tens] if not ones else f"{_AR_ONES[ones]} و{_AR_TENS[tens]}"
    if n < 1000:
        hundreds, rest = n - n % 100, n % 100
        return _AR_HUNDREDS[hundreds] if not rest else f"{_AR_HUNDREDS[hundreds]} و{_ar_int(rest)}"
    return str(n)


def _en_int(n):
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        tens, ones = n - n % 10, n % 10
        return _EN_TENS[tens] if not ones else f"{_EN_TENS[tens]}-{_EN_ONES[ones]}"
    if n < 1000:
        rest = n % 100
        return f"{_EN_ONES[n // 100]} hundred" + (f" and {_en_int(rest)}" if rest else "")
    return str(n)


def number_words(value, lang="ar"):
    """Grade written in words, e.g. 17.5 -> 'سبعة عشر ونصف' (as on Saudi score sheets)."""
    if value is None:
        return ""
    value = round(float(value) * 4) / 4
    whole = int(value)
    frac = round(value - whole, 2)
    if lang == "ar":
        names = {0.25: "ربع", 0.5: "نصف", 0.75: "ثلاثة أرباع"}
        if whole == 0 and frac:
            return names[frac]
        return _ar_int(whole) + (f" و{names[frac]}" if frac else "")
    names = {0.25: "a quarter", 0.5: "a half", 0.75: "three quarters"}
    if whole == 0 and frac:
        return names[frac]
    return _en_int(whole) + (f" and {names[frac]}" if frac else "")
