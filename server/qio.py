"""Import questions from an Excel file (download template → fill → upload)."""
import io
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .access import is_admin, own_form
from .db import get_db
from .grading import regrade_form
from .i18n import current_lang, t
from .settings import flag
from .teacher import clean_question, insert_question, search_forms
from .utils import jd, login_required, now

bp = Blueprint("qio", __name__, url_prefix="/questions-excel")

TYPE_CODES = ["mcq", "checkbox", "dropdown", "truefalse", "short", "number", "paragraph", "match", "fill", "order", "section", "file", "draw"]
TYPE_ALIASES = {
    "اختيار من متعدد": "mcq", "اختيار": "mcq", "مربعات": "checkbox", "قائمة": "dropdown", "صح وخطأ": "truefalse",
    "صح/خطأ": "truefalse", "قصير": "short", "إجابة قصيرة": "short", "رقم": "number", "مقالي": "paragraph",
    "توصيل": "match", "مطابقة": "match", "فراغات": "fill", "أكمل": "fill", "ترتيب": "order", "قسم": "section",
    "نص قراءة": "section", "رسم": "draw", "كتابة باليد": "draw", "handwriting": "draw", "true/false": "truefalse", "tf": "truefalse", "essay": "paragraph", "matching": "match",
}
YES = {"yes", "y", "1", "true", "نعم", "x", "✓"}
LETTERS = "ABCDEF"
N_OPTIONS = 6

EXAMPLES = [
    ["section", "Question 1: Look and circle. (4 marks)", "", "", "", "", "", "", "", "", 0, "", ""],
    ["mcq", "How often ____ she walk in the park?", "", "do", "does", "are", "", "", "", "B", 1, "yes", ""],
    ["checkbox", "Choose the sea animals", "", "shark", "camel", "dolphin", "", "", "", "A,C", 2, "yes", ""],
    ["truefalse", "Aisha and the writer are cousins.", "", "", "", "", "", "", "", "True", 1, "yes", ""],
    ["short", "Write the opposite of: lucky", "", "", "", "", "", "", "", "unlucky", 1, "yes", ""],
    ["number", "7 × 8 = ?", "", "", "", "", "", "", "", "56", 1, "yes", ""],
    ["match", "Match the question with the answer.", "", "Where do you live? = I live in Jeddah.", "How old are you? = I'm eleven years old.", "What's your name? = My name's Hashim.", "", "", "", "", 3, "yes", ""],
    ["fill", "Complete with a word from the box.", "A: What's your [name]?\nB: My name's Hashim.\nA: How [old] are you?", "from", "", "", "", "", "", "yes", 2, "yes", ""],
    ["order", "Reorder the words.", "", "", "", "", "", "", "", "I think / sharks / are / scary", 1, "yes", ""],
    ["paragraph", "Write two sentences about your dream bedroom.", "", "", "", "", "", "", "", "", 2, "yes", ""],
]


def _allowed():
    return is_admin() or (g.user is not None and g.user["role"] == "teacher" and flag("teachers_excel_import"))


@bp.before_request
def guard():
    if g.user is None:
        return redirect(url_for("auth.login", next=request.path))
    if not _allowed():
        flash(t("err_excel_admin_only"), "error")
        return redirect(url_for("teacher.dashboard") if g.user["role"] != "student" else url_for("exam.student_dashboard"))
    return None


def _headers():
    return [t("xl_type"), t("xl_question"), t("xl_text")] + [t("xl_option", n=i + 1) for i in range(N_OPTIONS)] + [
        t("xl_correct"), t("xl_points"), t("xl_required"), t("xl_explanation")]


@bp.get("/template.xlsx")
@login_required("staff")
def template():
    wb = Workbook()
    ws = wb.active
    ws.title = "Questions"
    ws.append(_headers())
    for row in EXAMPLES:
        ws.append(row)
    head_fill = PatternFill("solid", fgColor="1D4ED8")
    for cell in ws[1]:
        cell.fill, cell.font = head_fill, Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = [12, 42, 38] + [24] * N_OPTIONS + [22, 9, 10, 30]
    for idx, width in enumerate(widths):
        ws.column_dimensions[chr(65 + idx)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    dv = DataValidation(type="list", formula1='"' + ",".join(TYPE_CODES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("A2:A1000")
    dv2 = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
    ws.add_data_validation(dv2)
    dv2.add("L2:L1000")

    help_ws = wb.create_sheet("Help - شرح")
    help_ws.sheet_view.rightToLeft = current_lang() == "ar"
    help_ws.append([t("xl_type"), t("xl_help_col")])
    for cell in help_ws[1]:
        cell.fill, cell.font = head_fill, Font(bold=True, color="FFFFFF")
    for code in TYPE_CODES:
        help_ws.append([code, t("xl_help_" + code)])
    help_ws.append([])
    help_ws.append(["", t("xl_help_general")])
    help_ws.column_dimensions["A"].width = 14
    help_ws.column_dimensions["B"].width = 120
    for row in help_ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer, as_attachment=True, download_name="questions-template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _letter_index(token, options):
    token = token.strip()
    if len(token) == 1 and token.upper() in LETTERS and LETTERS.index(token.upper()) < len(options):
        return LETTERS.index(token.upper())
    if token.isdigit() and 1 <= int(token) <= len(options):
        return int(token) - 1
    for i, opt in enumerate(options):
        if opt.strip().lower() == token.lower():
            return i
    return None


def row_to_question(cells):
    kind = _cell(cells[0]).lower()
    kind = TYPE_ALIASES.get(kind, kind)
    text = _cell(cells[1])
    body = _cell(cells[2])
    options = [_cell(c) for c in cells[3:3 + N_OPTIONS]]
    options = [o for o in options if o]
    correct_raw = _cell(cells[3 + N_OPTIONS])
    points_raw = _cell(cells[4 + N_OPTIONS])
    required_raw = _cell(cells[5 + N_OPTIONS]).lower()
    explanation = _cell(cells[6 + N_OPTIONS])
    try:
        points = float(points_raw.replace(",", ".")) if points_raw else 1.0
    except ValueError:
        points = 1.0
    raw = {
        "type": kind, "text": text, "description": body, "points": points,
        "required": required_raw not in ("no", "n", "0", "false", "لا"), "explanation": explanation,
        "options": None, "correct": None, "partial": True,
    }
    if kind in ("mcq", "dropdown"):
        raw["options"] = options
        raw["correct"] = _letter_index(correct_raw, options) if correct_raw else None
    elif kind == "checkbox":
        raw["options"] = options
        picks = [_letter_index(tok, options) for tok in re.split(r"[,،;|]", correct_raw) if tok.strip()]
        raw["correct"] = [p for p in picks if p is not None] or None
    elif kind == "truefalse":
        low = correct_raw.lower()
        raw["correct"] = "true" if low in ("true", "t", "صح", "صحيح", "✓", "yes") else ("false" if low else None)
        if low in ("false", "f", "خطأ", "خطا", "✗", "x", "no"):
            raw["correct"] = "false"
    elif kind == "short":
        raw["correct"] = [a.strip() for a in correct_raw.split("|") if a.strip()] + options
    elif kind == "number":
        match = re.match(r"^\s*(-?[\d.]+)\s*(?:(?:±|\+/-|\|)\s*([\d.]+))?\s*$", correct_raw)
        raw["correct"] = {"value": match.group(1), "tolerance": match.group(2) or 0} if match else None
    elif kind == "match":
        pairs, distractors = [], []
        for opt in options:
            if "=" in opt:
                left, right = opt.split("=", 1)
                pairs.append([left.strip(), right.strip()])
            else:
                distractors.append(opt)
        raw["options"] = {"pairs": pairs, "distractors": distractors}
    elif kind == "fill":
        raw["options"] = {"template": body, "bank": correct_raw.lower() in YES, "distractors": options}
        raw["description"] = ""
    elif kind == "order":
        raw["correct"] = [correct_raw] + options if correct_raw else None
    elif kind == "section":
        raw["required"] = False
    return raw


@bp.route("/import", methods=["GET", "POST"])
@login_required("staff")
def import_page():
    db = get_db()
    fid = request.values.get("fid", type=int)
    if request.method == "POST":
        file = request.files.get("file")
        if file is None or not file.filename.lower().endswith((".xlsx", ".xlsm")):
            flash(t("err_excel_file"), "error")
            return redirect(url_for("qio.import_page", fid=fid))
        try:
            wb = load_workbook(file, data_only=True, read_only=True)
        except Exception:
            flash(t("err_excel_file"), "error")
            return redirect(url_for("qio.import_page", fid=fid))
        ws = wb.worksheets[0]
        cleaned, errors = [], []
        for number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            cells = list(row) + [None] * (7 + N_OPTIONS)
            if not any(_cell(c) for c in cells[: 7 + N_OPTIONS]):
                continue
            try:
                cleaned.append(clean_question(row_to_question(cells)))
            except ValueError as exc:
                errors.append(t("xl_row_error", n=number, msg=str(exc)))
        if errors and request.form.get("skip_errors") != "1":
            for err in errors[:25]:
                flash(err, "error")
            flash(t("xl_nothing_imported"), "error")
            return redirect(url_for("qio.import_page", fid=fid))
        if not cleaned:
            flash(t("xl_empty"), "error")
            return redirect(url_for("qio.import_page", fid=fid))
        stamp = now()
        if fid:
            form = own_form(fid)
        else:
            from .teacher import _new_unique_code

            title = (request.form.get("title") or "").strip()[:200] or file.filename.rsplit(".", 1)[0][:200]
            owner = g.user["id"]
            if is_admin() and request.form.get("teacher_id", type=int):
                owner = request.form.get("teacher_id", type=int)
            fid = db.execute(
                """INSERT INTO forms(teacher_id, code, title, description, show_results, show_answers, max_attempts, created_at, updated_at)
                   VALUES(?,?,?,?, 'after_grading', 1, 1, ?,?)""",
                (owner, _new_unique_code(db), title, "", stamp, stamp),
            ).lastrowid
            form = db.execute("SELECT * FROM forms WHERE id=?", (fid,)).fetchone()
        start = db.execute("SELECT COALESCE(MAX(position), -1) + 1 p FROM questions WHERE form_id=?", (fid,)).fetchone()["p"]
        for offset, q in enumerate(cleaned):
            insert_question(db, fid, start + offset, q)
        db.execute("UPDATE forms SET updated_at=? WHERE id=?", (stamp, fid))
        regrade_form(db, fid)
        db.commit()
        flash(t("xl_imported", n=len(cleaned), title=form["title"]), "success")
        for err in errors[:25]:
            flash(err, "error")
        return redirect(url_for("teacher.edit_form", fid=fid))
    forms = search_forms(db, limit=1000)
    teachers = db.execute("SELECT id, name FROM users WHERE role IN ('teacher','admin') AND active=1 ORDER BY name").fetchall() if is_admin() else []
    if fid:
        own_form(fid)
    return render_template("admin/excel_import.html", forms=forms, fid=fid, teachers=teachers, n_options=N_OPTIONS)


@bp.app_template_global()
def excel_import_allowed():
    return g.get("user") is not None and _allowed()


_ = abort
