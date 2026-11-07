"""AI helpers for the question builder: generate questions from a reading passage, suggest wrong options.

Enabled when the server has an ANTHROPIC_API_KEY environment variable (Vercel → Settings → Environment
Variables). AI_MODEL can override the model. Nothing is sent anywhere when the key is missing.
"""
import json
import os
import re
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"


def _url():
    base = os.environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
    return base + "/v1/messages" if base else API_URL
DEFAULT_MODEL = "claude-sonnet-4-5"
ALLOWED_TYPES = ("mcq", "truefalse", "short", "fill", "checkbox", "paragraph")


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


class AIError(Exception):
    pass


def _call(system, prompt, max_tokens=3000):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise AIError("disabled")
    body = json.dumps({
        "model": os.environ.get("AI_MODEL", "").strip() or DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    request = urllib.request.Request(_url(), data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01",
    })
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise AIError(f"http {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise AIError("network") from exc
    text = "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
    return _json_from(text)


def _json_from(text):
    match = re.search(r"\{.*\}|\[.*\]", text, re.S)
    if not match:
        raise AIError("format")
    try:
        return json.loads(match.group(0))
    except ValueError as exc:
        raise AIError("format") from exc


SYSTEM = (
    "You write school exam questions for teachers. Answer with JSON only, no commentary. "
    "Write in the same language as the source text (Arabic text → Arabic questions)."
)


def generate_questions(passage, counts, level="medium"):
    """counts: {"mcq": 3, "truefalse": 2, ...}. Returns a list of builder-ready question dicts."""
    wanted = {k: max(0, min(10, int(v))) for k, v in (counts or {}).items() if k in ALLOWED_TYPES}
    wanted = {k: v for k, v in wanted.items() if v}
    if not wanted or not passage.strip():
        return []
    spec = ", ".join(f"{n} × {k}" for k, n in wanted.items())
    prompt = f"""Source text:
<<<
{passage.strip()[:12000]}
>>>

Write exactly these questions about the source text: {spec}. Difficulty: {level}.
Return {{"questions": [...]}} where each item is one of:
- {{"type": "mcq", "text": "...", "options": ["...", "...", "...", "..."], "correct": <index of the right option>}}
- {{"type": "checkbox", "text": "...", "options": [...], "correct": [<indexes>]}}
- {{"type": "truefalse", "text": "<a statement>", "correct": "true" or "false"}}
- {{"type": "short", "text": "...", "correct": ["<accepted answer>", "<another accepted spelling>"]}}
- {{"type": "fill", "text": "<instruction>", "template": "<sentence with each missing word written as [word]>"}}
- {{"type": "paragraph", "text": "..."}}
Wrong options must be plausible. Use only facts from the source text."""
    data = _call(SYSTEM, prompt)
    items = data.get("questions") if isinstance(data, dict) else data
    out = []
    for item in items if isinstance(items, list) else []:
        q = _to_builder(item)
        if q:
            out.append(q)
    return out


def _to_builder(item):
    if not isinstance(item, dict) or item.get("type") not in ALLOWED_TYPES:
        return None
    kind, text = item["type"], str(item.get("text") or "").strip()[:1500]
    if not text:
        return None
    q = {"type": kind, "text": text, "options": None, "correct": None, "points": 1}
    if kind in ("mcq", "checkbox"):
        options = [str(o).strip()[:300] for o in item.get("options") or [] if str(o).strip()][:8]
        if len(options) < 2:
            return None
        q["options"] = options
        correct = item.get("correct")
        if kind == "mcq":
            q["correct"] = correct if isinstance(correct, int) and 0 <= correct < len(options) else None
        else:
            q["correct"] = sorted({c for c in correct if isinstance(c, int) and 0 <= c < len(options)}) if isinstance(correct, list) else None
    elif kind == "truefalse":
        q["correct"] = item.get("correct") if item.get("correct") in ("true", "false") else None
    elif kind == "short":
        answers = item.get("correct")
        answers = answers if isinstance(answers, list) else [answers]
        q["correct"] = [str(a).strip()[:200] for a in answers if a and str(a).strip()][:10] or None
    elif kind == "fill":
        template = str(item.get("template") or "").strip()[:2000]
        if "[" not in template:
            return None
        q["options"] = {"template": template, "bank": True, "distractors": []}
        q["points"] = max(1, template.count("["))
    return q


def suggest_distractors(question, options, correct=None, count=3):
    right = ""
    if isinstance(correct, int) and 0 <= correct < len(options):
        right = options[correct]
    prompt = f"""Question: {question.strip()[:1500]}
Correct answer: {right or '(not set)'}
Existing options: {json.dumps([o for o in options if o], ensure_ascii=False)}

Suggest {count} new WRONG but convincing options for this multiple-choice question, in the question's language,
different from the existing options. Return {{"options": ["...", "..."]}}."""
    data = _call(SYSTEM, prompt, max_tokens=600)
    items = data.get("options") if isinstance(data, dict) else data
    seen = {o.strip().lower() for o in options if o}
    out = []
    for o in items if isinstance(items, list) else []:
        o = str(o).strip()[:300]
        if o and o.lower() not in seen:
            seen.add(o.lower())
            out.append(o)
    return out[:count]
