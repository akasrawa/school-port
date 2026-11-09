import json
import random
import re
import statistics

from .i18n import t
from .utils import jl, now, pct

AUTO = {"mcq", "dropdown", "truefalse", "checkbox", "short", "number", "match", "fill", "order"}
MANUAL = {"paragraph", "file", "draw"}
INFO = {"scale", "date", "section"}
TYPES = AUTO | MANUAL | INFO
CHOICE_TYPES = {"mcq", "dropdown", "checkbox"}

_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_digits(text):
    return str(text).translate(_DIGITS)


def normalize(text):
    text = normalize_digits(text).strip().lower()
    text = _DIACRITICS.sub("", text)
    text = re.sub("[أإآ]", "ا", text)
    text = text.replace("ى", "ي")
    return re.sub(r"\s+", " ", text)


_PUNCT = re.compile(r"[.?!,;:\u060C\u061B\u061F\"'()\u2019\u2018\u201C\u201D]")
BLANK_RE = re.compile(r"\[([^\[\]\n]+)\]")


def loose(text):
    """Normalise and also ignore punctuation – used for sentences typed or built by students."""
    text = normalize(text).replace("\u2019", "'")
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def fill_blanks(q):
    """Accepted answers for each [blank] of a fill-in question."""
    template = (q.get("options") or {}).get("template", "") if isinstance(q.get("options"), dict) else ""
    return [[alt.strip() for alt in m.split("|") if alt.strip()] for m in BLANK_RE.findall(template)]


def blank_weights(q, count):
    """Per-blank points set by the teacher (options.blank_points); equal weights for older questions."""
    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
    raw = opts.get("blank_points")
    if isinstance(raw, list) and len(raw) == count:
        try:
            weights = [max(0.0, float(x)) for x in raw]
            if sum(weights) > 0:
                return weights
        except (TypeError, ValueError):
            pass
    return [1.0] * count


def fill_parts(q):
    """Template split into text and blank pieces for rendering."""
    template = (q.get("options") or {}).get("template", "") if isinstance(q.get("options"), dict) else ""
    parts, last, index = [], 0, 0
    for m in BLANK_RE.finditer(template):
        if m.start() > last:
            parts.append({"text": template[last:m.start()]})
        parts.append({"blank": index})
        index += 1
        last = m.end()
    if last < len(template):
        parts.append({"text": template[last:]})
    return parts


def fill_bank(q):
    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
    if not opts.get("bank"):
        return []
    words = [alts[0] for alts in fill_blanks(q) if alts]
    words += [w for w in (opts.get("distractors") or []) if w]
    seen, out = set(), []
    for w in words:
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return sorted(out, key=lambda w: w.lower())


def match_pairs(q):
    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
    return [p for p in (opts.get("pairs") or []) if isinstance(p, list) and len(p) == 2]


def match_choices(q):
    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
    seen, out = set(), []
    for item in [p[1] for p in match_pairs(q)] + list(opts.get("distractors") or []):
        key = normalize(item)
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def order_chunks(q):
    answers = q.get("correct") or []
    if not answers:
        return []
    first = answers[0]
    if "/" in first:
        return [c.strip() for c in first.split("/") if c.strip()]
    return first.split()


def order_accepted(q):
    out = []
    for answer in q.get("correct") or []:
        out.append(loose(" ".join(c.strip() for c in answer.split("/"))))
    return out


def load_questions(db, form_id, include_incomplete=False):
    """Questions of an exam. Unfinished drafts (extra.incomplete) are only returned to the builder."""
    rows = db.execute(
        "SELECT * FROM questions WHERE form_id=? ORDER BY position, id", (form_id,)
    ).fetchall()
    out = []
    for row in rows:
        q = dict(row)
        q["options"] = jl(row["options_json"], None)
        q["correct"] = jl(row["correct_json"], None)
        extra = jl(row["extra_json"], None) if "extra_json" in row.keys() else None
        q["extra"] = extra if isinstance(extra, dict) else {}
        if q["extra"].get("incomplete") and not include_incomplete:
            continue
        out.append(q)
    return out


def has_key(q):
    kind, correct = q["type"], q["correct"]
    if kind in ("mcq", "dropdown"):
        return isinstance(correct, int) and not isinstance(correct, bool)
    if kind == "checkbox":
        return bool(correct)
    if kind == "truefalse":
        return correct in ("true", "false")
    if kind == "short":
        return bool(correct)
    if kind == "number":
        return isinstance(correct, dict) and correct.get("value") is not None
    if kind == "match":
        return bool(match_pairs(q))
    if kind == "fill":
        blanks = fill_blanks(q)
        return bool(blanks) and all(blanks)  # every blank needs its answer (an empty [ ] is for manual grading)
    if kind == "order":
        return bool(correct)
    return False


def is_manual(q):
    """Graded by hand: essay/file/drawing, or any question the teacher switched to manual grading."""
    return q["type"] in MANUAL or (q["type"] in AUTO and bool(q.get("manual_grade")))


def eff_points(q):
    kind = q["type"]
    if kind in INFO:
        return 0.0
    if kind in AUTO and not has_key(q) and not q.get("manual_grade"):
        return 0.0
    return float(q["points"] or 0)


def is_empty(value):
    if isinstance(value, list):
        return all(v is None or str(v).strip() == "" for v in value)
    return value is None or value == ""


def grade_auto(q, value):
    points = eff_points(q)
    if points == 0 or is_empty(value):
        return 0.0
    kind = q["type"]
    try:
        if kind in ("mcq", "dropdown"):
            return points if int(value) == q["correct"] else 0.0
        if kind == "truefalse":
            return points if str(value) == q["correct"] else 0.0
        if kind == "checkbox":
            chosen = {int(x) for x in value}
            correct = set(q["correct"])
            if chosen == correct:
                return points
            if q.get("partial"):
                deduct = (q.get("extra") or {}).get("cb_deduct", True)  # older questions: wrong ticks take marks away
                ratio = (len(chosen & correct) - (len(chosen - correct) if deduct else 0)) / len(correct)
                return round(max(0.0, ratio) * points, 2)
            return 0.0
        if kind == "short":
            given = loose(value)
            return points if any(given == loose(a) for a in q["correct"]) else 0.0
        if kind == "order":
            return points if loose(value) in order_accepted(q) else 0.0
        if kind == "match":
            pairs = match_pairs(q)
            values = list(value) + [None] * len(pairs)
            right = sum(1 for i, p in enumerate(pairs) if values[i] and normalize(values[i]) == normalize(p[1]))
            return round(points * right / len(pairs), 2)
        if kind == "fill":
            blanks = fill_blanks(q)
            values = list(value) + [None] * len(blanks)
            weights = blank_weights(q, len(blanks))
            right = sum(
                weights[i] for i, alts in enumerate(blanks)
                if values[i] and any(loose(values[i]) == loose(a) for a in alts)
            )
            return round(points * right / (sum(weights) or 1), 2)
        if kind == "number":
            number = float(normalize_digits(value).replace(",", "."))
            tolerance = float(q["correct"].get("tolerance") or 0)
            return points if abs(number - float(q["correct"]["value"])) <= tolerance + 1e-9 else 0.0
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def recalc_attempt(db, attempt_id):
    """Grade every auto question, keep manual overrides, refresh totals/status."""
    attempt = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    if attempt is None:
        return
    questions = load_questions(db, attempt["form_id"])
    for q in questions:
        db.execute(
            "INSERT OR IGNORE INTO answers(attempt_id, question_id) VALUES(?,?)",
            (attempt_id, q["id"]),
        )
    answers = {
        r["question_id"]: r
        for r in db.execute("SELECT * FROM answers WHERE attempt_id=?", (attempt_id,))
    }
    total = maximum = 0.0
    pending = 0
    for q in questions:
        row = answers[q["id"]]
        value = jl(row["value_json"], None)
        points = eff_points(q)
        maximum += points
        if points == 0:
            awarded = 0.0
        elif row["manual"]:
            awarded = row["points"]
        elif q["type"] in AUTO and not q.get("manual_grade"):
            awarded = grade_auto(q, value)
        else:
            awarded = 0.0 if is_empty(value) else None
        if awarded is None:
            pending += 1
        else:
            total += awarded
        db.execute("UPDATE answers SET points=? WHERE id=?", (awarded, row["id"]))
    status = "graded" if pending == 0 else "submitted"
    db.execute(
        "UPDATE attempts SET total_score=?, max_score=?, pending=?, status=? WHERE id=?",
        (round(total, 2), maximum, pending, status, attempt_id),
    )


def finalize_attempt(db, attempt, auto=False, late=False):
    submitted = now()
    if attempt["deadline_at"]:
        submitted = min(submitted, attempt["deadline_at"])
    db.execute(
        "UPDATE attempts SET submitted_at=?, status='submitted', auto_submitted=?, late=? WHERE id=?",
        (submitted, 1 if auto else 0, 1 if late else 0, attempt["id"]),
    )
    recalc_attempt(db, attempt["id"])
    db.commit()


def regrade_form(db, form_id):
    ids = [
        r["id"]
        for r in db.execute(
            "SELECT id FROM attempts WHERE form_id=? AND status!='in_progress'", (form_id,)
        )
    ]
    for attempt_id in ids:
        recalc_attempt(db, attempt_id)


def ordered_questions(questions, attempt, form):
    """Shuffle questions when asked, but keep each section (reading text / heading) with its own questions."""
    items = list(questions)
    if not form["shuffle_questions"]:
        return items
    rng = random.Random(attempt["seed"])
    out, group = [], []
    for q in items:
        if q["type"] == "section":
            rng.shuffle(group)
            out += group
            group = []
            out.append(q)
        else:
            group.append(q)
    rng.shuffle(group)
    return out + group


def option_order(q, attempt, form):
    count = len(q["options"] or [])
    order = list(range(count))
    if form["shuffle_options"] and q["type"] in ("mcq", "checkbox"):
        random.Random(attempt["seed"] * 7919 + q["id"]).shuffle(order)
    return order


def answer_text(q, value):
    """Human readable version of a stored answer value."""
    if is_empty(value):
        return ""
    kind = q["type"]
    options = q["options"] or []
    try:
        if kind in ("mcq", "dropdown"):
            return options[int(value)]
        if kind == "checkbox":
            return "، ".join(options[int(i)] for i in value)
        if kind == "truefalse":
            return t("true") if str(value) == "true" else t("false")
        if kind == "match":
            pairs = match_pairs(q)
            return "\n".join(
                f"{p[0]} → {value[i] if i < len(value) and value[i] else '—'}" for i, p in enumerate(pairs)
            )
        if kind == "fill":
            return " | ".join((v or "—") for v in value)
    except (IndexError, ValueError, TypeError):
        return str(value)
    return str(value)


def answer_images(q, value):
    """Pictures of the options a student picked (choice questions with option pictures)."""
    images = (q.get("extra") or {}).get("option_images") or []
    if not images or is_empty(value) or q["type"] not in ("mcq", "checkbox"):
        return []
    try:
        picked = [int(v) for v in value] if isinstance(value, list) else [int(value)]
    except (TypeError, ValueError):
        return []
    return [images[i] for i in picked if 0 <= i < len(images) and images[i]]


def match_choice_image(q, text):
    right = (q.get("extra") or {}).get("right_images") or []
    for i, p in enumerate(match_pairs(q)):
        if i < len(right) and right[i] and normalize(p[1]) == normalize(text or ""):
            return right[i]
    return ""


def match_rows(q, value):
    """Matching answer as rows with pictures: left item → the student's choice."""
    extra = q.get("extra") or {}
    left, right = extra.get("left_images") or [], extra.get("right_images") or []
    pairs = match_pairs(q)
    by_text = {normalize(p[1]): (right[i] if i < len(right) else "") for i, p in enumerate(pairs)}
    values = list(value or []) + [None] * len(pairs)
    rows = []
    for i, p in enumerate(pairs):
        given = values[i] or ""
        rows.append({
            "left": p[0].replace("\u2063", ""), "left_img": left[i] if i < len(left) else "",
            "given": str(given).replace("\u2063", ""), "given_img": by_text.get(normalize(given), "") if given else "",
            "answered": bool(given),
        })
    return rows


def correct_text(q):
    """Readable answer key. Manually graded questions have no key to show."""
    if is_manual(q) or not has_key(q):
        return ""
    kind, correct = q["type"], q["correct"]
    options = q["options"] or []
    if kind in ("mcq", "dropdown"):
        return options[correct] if 0 <= correct < len(options) else ""
    if kind == "checkbox":
        return "، ".join(options[i] for i in correct if 0 <= i < len(options))
    if kind == "truefalse":
        return t("true") if correct == "true" else t("false")
    if kind == "short":
        return " / ".join(correct)
    if kind == "order":
        return " / ".join(" ".join(c.strip() for c in a.split("/")) for a in correct)
    if kind == "match":
        return "\n".join(f"{p[0]} → {p[1]}" for p in match_pairs(q))
    if kind == "fill":
        return " | ".join(" / ".join(alts) for alts in fill_blanks(q))
    if kind == "number":
        text = str(correct["value"])
        if correct.get("tolerance"):
            text += " ± " + str(correct["tolerance"])
        return text
    return ""


def form_analytics(db, form, questions):
    attempts = db.execute(
        "SELECT * FROM attempts WHERE form_id=? AND is_preview=0 AND status!='in_progress'",
        (form["id"],),
    ).fetchall()
    percents = [pct(a["total_score"], a["max_score"]) for a in attempts if a["max_score"]]
    durations = [
        a["submitted_at"] - a["started_at"] for a in attempts if a["submitted_at"]
    ]
    buckets = [0] * 10
    for p in percents:
        buckets[min(int(p // 10), 9)] += 1
    passed = sum(1 for p in percents if p >= form["pass_percent"])
    summary = {
        "count": len(attempts),
        "average": round(statistics.mean(percents), 1) if percents else 0,
        "median": round(statistics.median(percents), 1) if percents else 0,
        "highest": round(max(percents), 1) if percents else 0,
        "lowest": round(min(percents), 1) if percents else 0,
        "pass_rate": round(passed / len(percents) * 100, 1) if percents else 0,
        "passed": passed,
        "failed": len(percents) - passed,
        "avg_minutes": round(statistics.mean(durations) / 60, 1) if durations else 0,
        "pending": sum(1 for a in attempts if a["pending"]),
        "violations": sum(a["violations"] for a in attempts),
    }
    attempt_ids = [a["id"] for a in attempts]
    answers_by_q = {q["id"]: [] for q in questions}
    if attempt_ids:
        marks = ",".join("?" * len(attempt_ids))
        for row in db.execute(
            f"SELECT * FROM answers WHERE attempt_id IN ({marks})", attempt_ids
        ):
            if row["question_id"] in answers_by_q:
                answers_by_q[row["question_id"]].append(row)
    per_question = []
    for q in questions:
        rows = answers_by_q[q["id"]]
        points = eff_points(q)
        answered = 0
        correct = 0
        earned = 0.0
        counts = {}
        for row in rows:
            value = jl(row["value_json"], None)
            if not is_empty(value) or row["file_path"]:
                answered += 1
            if row["points"] is not None:
                earned += row["points"]
                if points and row["points"] >= points - 1e-9:
                    correct += 1
            if q["type"] in ("mcq", "dropdown") and not is_empty(value):
                counts[str(value)] = counts.get(str(value), 0) + 1
            elif q["type"] == "checkbox" and isinstance(value, list):
                for item in value:
                    counts[str(item)] = counts.get(str(item), 0) + 1
            elif q["type"] == "truefalse" and not is_empty(value):
                counts[str(value)] = counts.get(str(value), 0) + 1
        choices = []
        if q["type"] in CHOICE_TYPES:
            for i, label in enumerate(q["options"] or []):
                is_right = (
                    q["correct"] == i
                    if q["type"] != "checkbox"
                    else i in (q["correct"] or [])
                )
                choices.append({"label": label, "count": counts.get(str(i), 0), "correct": is_right})
        elif q["type"] == "truefalse":
            for key in ("true", "false"):
                choices.append(
                    {"label": t(key), "count": counts.get(key, 0), "correct": q["correct"] == key}
                )
        total = len(rows)
        per_question.append(
            {
                "q": q,
                "points": points,
                "answered": answered,
                "skipped": total - answered,
                "correct": correct,
                "correct_rate": round(correct / total * 100, 1) if total and points else None,
                "avg_points": round(earned / total, 2) if total and points else None,
                "choices": choices,
                "total": total,
            }
        )
    return {"summary": summary, "buckets": buckets, "questions": per_question}
