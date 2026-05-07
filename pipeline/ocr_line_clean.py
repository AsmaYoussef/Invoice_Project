"""Shared OCR noise normalization for v2 line parsers."""

from __future__ import annotations

import re
from typing import Tuple


def normalize_code_token(token: str) -> str:
    t = re.sub(r"[^A-Za-z0-9]", "", str(token or "").upper())
    if not t:
        return ""
    t = t.replace("§", "5")
    if t.startswith("FF"):
        t = "PF" + t[2:]
    if t.startswith("PFO"):
        t = "PF0" + t[3:]
    if t.startswith("PF"):
        head = "PF"
        tail = t[2:]
        tail = tail.replace("O", "0").replace("I", "1").replace("S", "5").replace("B", "8")
        return head + tail
    return t


def clean_designation_noise(s: str) -> str:
    t = str(s or "").strip()
    t = re.sub(r"^[\-\*\!\~\=\+\#\|]+\s*", "", t).strip()
    t = re.sub(r"[\!\~\=\*\#\|]+$", "", t).strip()
    t = re.sub(r"\s{2,}", " ", t)
    return t


def strip_parentheses_content(s: str) -> str:
    return re.sub(r"\([^)]*\)", " ", str(s or ""))


def collapse_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def remove_currency_noise(s: str) -> str:
    t = str(s or "")
    t = t.replace("$", " ").replace("€", " ").replace("°", " ")
    return t


def repair_date_ocr_fragment(fragment: str) -> str:
    """Light repairs in date-like substrings (o→0, common OCR)."""
    t = fragment
    t = re.sub(r"(\d)[oO](\d)", r"\g<1>0\2", t)
    t = re.sub(r"(\d)[zZ](\d)", r"\g<1>2\2", t)
    return t


def pre_clean_ocr_line(line: str) -> str:
    t = remove_currency_noise(line)
    t = strip_parentheses_content(t)
    t = re.sub(r"[\[\]_]+", " ", t)
    t = collapse_whitespace(t)
    return t


def split_tokens_respecting_numbers(line: str) -> list:
    """Whitespace tokens; keep French-style grouped numbers as single tokens when comma-decimal."""
    parts = pre_clean_ocr_line(line).split()
    return [p for p in parts if p]


def _ocr_normalize_numeric_token(tok: str) -> str:
    """Common OCR confusions (O→0, l→1) inside digit-heavy tokens only."""
    t = str(tok or "").strip()
    compact = re.sub(r"\s+", "", t)
    if not compact or not re.match(r"^[\dOolI|,\.S§\-]+$", compact, re.I):
        return t
    out = []
    for ch in t:
        if ch in "Oo":
            out.append("0")
        elif ch in "lI|":
            out.append("1")
        elif ch in "S§":
            out.append("5")
        else:
            out.append(ch)
    return "".join(out)


def parse_french_money_token(tok: str) -> Tuple[bool, float | None]:
    spaced = _ocr_normalize_numeric_token(tok)
    merged = spaced.replace(" ", "")
    if re.match(r"^\d{1,6},\d{1,3}$", merged):
        try:
            return True, float(merged.replace(",", "."))
        except ValueError:
            return True, None
    if re.match(r"^\d{1,7}\.\d{1,3}$", merged):
        try:
            return True, float(merged)
        except ValueError:
            return True, None
    if re.match(r"^\d{1,3}(?:\s\d{3})+,\d{1,3}$", spaced.replace(" ", " ")):
        compact = spaced.replace(" ", "")
        if re.match(r"^\d+,\d{1,3}$", compact):
            try:
                return True, float(compact.replace(",", "."))
            except ValueError:
                return True, None
    if re.match(r"^\d{1,3}(?:\s\d{3})+\.\d{1,3}$", spaced.replace(" ", " ")):
        compact = spaced.replace(" ", "")
        if re.match(r"^\d+\.\d{1,3}$", compact):
            try:
                return True, float(compact)
            except ValueError:
                return True, None
    return False, None


def is_six_digit_like(tok: str) -> bool:
    d = re.sub(r"\D", "", tok)
    return 5 <= len(d) <= 7


def is_proforma_pct_token(tok: str) -> bool:
    """PCT-like numeric code: not French money (e.g. 123,45 must not become code_pct)."""
    if not is_six_digit_like(tok):
        return False
    is_money, _ = parse_french_money_token(tok)
    return not is_money


def is_pf_like(tok: str) -> bool:
    u = normalize_code_token(tok)
    return bool(u) and u.startswith("PF") and len(u) >= 4
