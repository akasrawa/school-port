"""Repair Arabic text copied from PDFs.

Many PDFs store Arabic as "presentation form" glyphs (U+FB50-U+FDFF, U+FE70-U+FEFF) in visual
(left-to-right) order. Pasted as-is the letters show disconnected and reversed. This converts such
text back to normal Arabic letters in logical order. The same logic lives in public/static/js/common.js.
"""
import re
import unicodedata

_KEEP = {"ﷺ": "", "ﷻ": ""}  # ﷺ ﷻ stay as one sign
_PRES = re.compile("[ﭐ-﷿ﹰ-﻾]")
_LTR = re.compile(r"[0-9A-Za-z٠-٩۰-۹]+(?:[.,:/\-][0-9A-Za-z٠-٩۰-۹]+)*")
_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")
_WORD = re.compile("[ء-ي]{3,}")


def _normalize(text):
    return _PRES.sub(lambda m: m.group() if m.group() in _KEEP else unicodedata.normalize("NFKC", m.group()), text)


def _looks_reversed(text):
    words = _WORD.findall(text)
    starts = sum(1 for w in words if re.match("^[وفبك]?ال", w))
    ends = sum(1 for w in words if re.search("لا[وفبك]?$", w))
    return ends > starts


def _reverse_line(line):
    out = line[::-1]
    out = _LTR.sub(lambda m: m.group()[::-1], out)
    return out.translate(_MIRROR)


def fix_pdf_arabic(text):
    if not text or not _PRES.search(text):
        return text
    text = text.replace("﻿", "")
    if _looks_reversed(_normalize(text)):
        text = "\n".join(_reverse_line(line) for line in text.split("\n"))
    return _normalize(text)


def fix_pdf_strings(value):
    """Apply fix_pdf_arabic to every string inside JSON-like data."""
    if isinstance(value, str):
        return fix_pdf_arabic(value)
    if isinstance(value, list):
        return [fix_pdf_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: fix_pdf_strings(v) for k, v in value.items()}
    return value
