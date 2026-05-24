"""Shared OCR noise normalization for v2 line parsers."""

from __future__ import annotations

import re
from typing import Any, Tuple


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
    t = re.sub(r"^[\-\*\!\~\=\+\#\|£/\\]+\s*", "", t).strip()
    t = re.sub(r"[\!\~\=\*\#\|£/\\~]+$", "", t).strip()
    t = re.sub(r"\s{2,}", " ", t)
    return t


def extract_pharma_designation_core(raw: str) -> str:
    """
    Extract the pharmaceutical product span from noisy Tesseract text.
    Anchors on first 4+ letter drug token; ends at COMP, B/NN, or dosage/pack.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    upper = text.upper()
    best: tuple[int, int] | None = None
    for m in re.finditer(r"\b[A-Z]{4,}", upper):
        start = m.start()
        rest = upper[start:]
        end_m = _PHARMA_PRODUCT_SPAN.match(rest)
        if not end_m:
            end_m = _PHARMA_DESIGNATION_CORE.search(rest)
        if not end_m:
            pack = re.search(r"B/\s*\d+\s*(?:COMP|CP)\b", rest)
            if pack:
                end_m = pack
        if not end_m:
            pack2 = re.search(
                r"(?:\d+\s*MG\.?B/\d+\s*(?:COMP|CP)|\d+MG/?B/\d+\s*(?:COMP|CP))\b",
                rest,
            )
            if pack2:
                end_m = pack2
        if end_m:
            span = (start, start + end_m.end())
            if best is None or (span[1] - span[0]) > (best[1] - best[0]):
                best = span
    if best:
        return text[best[0] : best[1]].strip()
    return ""


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


_PHARMA_DESIGNATION_CORE = re.compile(
    r"([A-Z][A-Z0-9\s\./\-]*?(?:\d|COMP))\s*$",
    re.IGNORECASE,
)

_PHARMA_PRODUCT_SPAN = re.compile(
    r"^[A-Z0-9][A-Z0-9\s./\-]*?(?:"
    r"B/\s*\d+\s*(?:COMP|CP)|"
    r"\d+\s*MG\.?\s*B/\s*\d+\s*(?:COMP|CP)|"
    r"\d+MG/?B/\d+\s*(?:COMP|CP)|"
    r"\d+\s*MG(?:\s+B/\s*\d+\s*(?:COMP|CP))?|"
    r"(?:FL|SOL|GEL|INJ|AMP|CP|BT)[A-Z0-9/\s.]*|"
    r"\d+\s*(?:ML|MG)|"
    r"COMP"
    r")\s*",
    re.IGNORECASE,
)

_LEADING_JUNK = re.compile(
    r"^[\s\"'£#/\\<>.,;:!?¢~`\-]+|"
    r"^\d{1,5}\s+|"
    r"^[a-z]{1,3}\s+|"
    r"^\d+\"\s*|"
    r'^[^A-Z]*',
    re.IGNORECASE,
)

_TRAILING_JUNK = re.compile(
    r"[\s\"'£#/\\<>.,;:!?¢~`\-\~—]+$"
)

_QTY_OCR_ALIASES: dict[str, str] = {
    "BO": "80",
}
_QTY_ARTIFACT_MIN_DIGITS = 5
_PUNCT_ONLY_TOKEN = re.compile(r"^[\=\—\-_\|\.\"\'\s]+$")


_MAX_ORDER_QTY = 8000

_DOSAGE_FOLLOW = re.compile(
    r"^\s*(?:MG|ML|G|UI|µG|MCG|GR|%|CP|FL|BT|AMP|INJ|SOL|GEL)\b",
    re.IGNORECASE,
)


def is_plausible_column_qty(
    num_str: str,
    *,
    following: str = "",
    preceding: str = "",
) -> bool:
    """
    True when integer looks like Qté / Quantité column value, not dosage (10 MG) or pack (B/30).
    """
    if not re.fullmatch(r"\d{1,5}", str(num_str or "").strip()):
        return False
    n = int(num_str)
    if n <= 0 or n > _MAX_ORDER_QTY:
        return False
    if 1900 <= n <= 2100:
        return False
    fol = (following or "").lstrip()
    pre = (preceding or "").rstrip()
    if _DOSAGE_FOLLOW.match(fol) or re.match(r"^\d+\s*MG\b", f"{num_str} {fol}", re.I):
        return False
    if re.search(r"B/\s*$", pre, re.I):
        return False
    if re.search(r"\d+\s*MG\s*$", pre, re.I):
        return False
    if fol and re.match(r"^[A-Z]{3,}", fol, re.I):
        return True
    if pre and re.search(r"(?:COMP|CP|FL|ML|MG|INJ|GEL|SOL)\s*$", pre, re.I):
        return True
    if not fol and not pre:
        return True
    return False


def _parsed_qty_positive(raw: Any) -> bool:
    """True when quantite parses to a positive number (incl. comma decimals)."""
    if raw in (None, "", 0, 0.0):
        return False
    if isinstance(raw, (int, float)):
        return float(raw) > 0
    text = str(raw).strip().replace(" ", "").replace(",", ".")
    parts = text.split(".")
    if len(parts) > 2:
        text = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(text) > 0
    except ValueError:
        return False


def line_has_quantite(item: dict[str, Any]) -> bool:
    """True when row has a positive quantite value (incl. comma decimals)."""
    return _parsed_qty_positive(item.get("quantite"))


def quantite_is_locked(item: dict[str, Any]) -> bool:
    """True only when qty was explicitly locked by extract/merge (not merely present)."""
    return bool(item.get("_quantite_locked"))


def _strip_leading_junk(text: str, *, quantite_locked: bool = False) -> str:
    """Strip OCR punctuation junk; skip digit-stripping when qty is already locked."""
    t = str(text or "").strip()
    if not t:
        return t
    punct = re.compile(
        r'^[\s"\'£#/\\<>.,;:!?¢~`\-]+|'
        r'^[a-z]{1,3}\s+|'
        r'^\d+"\s*|'
        r"^[^A-Z]*",
        re.IGNORECASE,
    )
    while True:
        prev = t
        t = punct.sub("", t).strip()
        if not quantite_locked:
            t = re.sub(r"^\d{1,5}\s+", "", t).strip()
        else:
            t = re.sub(r"^[\s—\-]+", "", t).strip()
            t = re.sub(r"^\d\s+(?=[A-Z])", "", t, count=1).strip()
        if t == prev:
            break
    return t


def resolve_raw_row_text(row: dict[str, Any]) -> str:
    """Best available uncleaned OCR line for qty extraction."""
    raw = str(row.get("_row_txt") or row.get("raw_line") or "").strip()
    if raw:
        return raw
    code = str(row.get("code") or row.get("code_pct") or row.get("code_article") or "").strip()
    desig = str(row.get("designation") or "").strip()
    if code and desig:
        return f"{code} {desig}".strip()
    return desig or code


def _row_txt_has_qty_after_code(raw_line: str, code: str) -> bool:
    """True when raw line has a plausible Qté token immediately after the product code."""
    if not raw_line or not code:
        return False
    after = _text_after_code(raw_line, code)
    if not after:
        return False
    qty, _, _ = _extract_qty_positional_from_tokens(_split_positional_tokens(after))
    return bool(qty)


def _find_body_line_for_code(combined_body: str, code: str) -> str:
    """Find the richest body OCR line starting with this product code."""
    code_u = str(code or "").strip().upper()
    if not code_u or not combined_body:
        return ""
    best = ""
    for raw in combined_body.splitlines():
        line = raw.strip()
        if not line:
            continue
        hay = line.upper()
        if not (hay.startswith(code_u) or re.search(rf'^\s*["\']?{re.escape(code_u)}\b', hay)):
            continue
        if len(line) > len(best):
            best = line
    return best


def extract_mp_code_qty_from_raw(
    raw_line: str,
    code: str,
) -> tuple[str | None, str, str]:
    """
    Avenir/MEDIS BC fast path: 6-digit MP code then integer Qté token.
    e.g. '302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP'
    """
    raw = str(raw_line or "").strip()
    code_u = str(code or "").strip().upper()
    digits = re.sub(r"\D", "", code_u)
    if len(digits) != 6:
        return None, "", ""
    m = re.search(
        rf'^\s*["\']?{re.escape(code_u)}\b\s+(\d{{1,5}})\b',
        raw,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(
            rf'\b{re.escape(digits)}\b\s+(\d{{1,5}})\b',
            raw,
        )
    if not m:
        return None, "", ""
    qty_s = m.group(1)
    if not is_plausible_positional_prefix_qty(qty_s, following=raw[m.end() :].strip()):
        return None, "", ""
    remain = raw[m.end() :].strip()
    remain = re.sub(r"^(?:[Xx×]\s*)?", "", remain).strip()
    return qty_s, remain, "mp_code_prefix"


def _text_after_code(raw_line: str, code: str) -> str:
    """Return uncleaned text after the product code token."""
    raw = str(raw_line or "").strip()
    code_u = str(code or "").strip().upper()
    if not raw:
        return raw
    if not code_u:
        return raw
    hay = raw.upper()
    idx = hay.find(code_u)
    if idx < 0:
        stripped = re.sub(r'^[\s"\']+', "", raw)
        idx = stripped.upper().find(code_u)
        if idx >= 0:
            raw = stripped
            hay = raw.upper()
    if idx < 0:
        return raw
    after = raw[idx + len(code_u) :].strip()
    return re.sub(r"^[\|\.'\"()\[\]\-_\s]+", "", after).strip()


def _token_has_qty_signal(tok: str) -> bool:
    t = str(tok or "").strip()
    if not t:
        return False
    if re.search(r"\d", t):
        return True
    letters = re.sub(r"[^A-Za-z]", "", t).upper()
    return letters in _QTY_OCR_ALIASES


def _isolate_qty_digits(tok: str) -> str:
    """Strip punctuation/OCR noise from a Qté column token to recover integer digits."""
    t = str(tok or "").strip()
    if not t:
        return ""
    letters = re.sub(r"[^A-Za-z]", "", t).upper()
    if len(letters) == 2 and letters in _QTY_OCR_ALIASES:
        return _QTY_OCR_ALIASES[letters]
    normalized = _ocr_normalize_numeric_token(t)
    return re.sub(r"\D", "", normalized)


def is_plausible_positional_prefix_qty(
    num_str: str,
    *,
    following: str = "",
) -> bool:
    """Relaxed plausibility for Qté in column position 1–2 after product code."""
    if not re.fullmatch(r"\d{1,5}", str(num_str or "").strip()):
        return False
    n = int(num_str)
    if n <= 0 or n > _MAX_ORDER_QTY:
        return False
    if 1900 <= n <= 2100:
        return False
    fol = (following or "").lstrip()
    if not fol:
        return True
    if re.match(r"^\d+\s*MG\b", fol, re.I):
        return False
    if _DOSAGE_FOLLOW.match(fol):
        return False
    first = fol.split()[0] if fol.split() else ""
    if first and re.match(r"^\d{1,2}[a-z]?$", first, re.I) and len(first) <= 3:
        return True
    if re.match(r"^[A-Z]{3,}", fol, re.I):
        return True
    if re.match(r"^[\—\-]", fol):
        return True
    return True


def _parse_qty_from_token(
    tok: str,
    *,
    following: str = "",
    preceding: str = "",
    prefix_column: bool = False,
) -> str | None:
    digits = _isolate_qty_digits(tok)
    if not digits:
        return None
    if len(digits) >= _QTY_ARTIFACT_MIN_DIGITS:
        return None
    if prefix_column and len(digits) == 3 and following:
        alt = digits[:2]
        if (
            alt.isdigit()
            and int(alt) > 0
            and digits[2] == digits[1]
            and is_plausible_positional_prefix_qty(alt, following=following)
        ):
            digits = alt
    if prefix_column:
        if not is_plausible_positional_prefix_qty(digits, following=following):
            return None
    elif not is_plausible_column_qty(digits, following=following, preceding=preceding):
        return None
    return digits


def _split_positional_tokens(after_code: str) -> list[str]:
    """Whitespace tokens after code; light cleanup only (preserve noisy Qté tokens)."""
    t = remove_currency_noise(str(after_code or ""))
    t = collapse_whitespace(t)
    return [p for p in t.split() if p]


def _remainder_tokens(tokens: list[str], consumed: set[int]) -> str:
    return " ".join(t for i, t in enumerate(tokens) if i not in consumed).strip()


def _extract_qty_positional_from_tokens(
    tokens: list[str],
) -> tuple[str | None, str, str]:
    """Positional scan: Qté is token 1–2 after code, else trailing suffix."""
    if not tokens:
        return None, "", ""

    prefix_attempts: list[tuple[int, set[int]]] = []
    if len(tokens) >= 1:
        prefix_attempts.append((0, {0}))
    if len(tokens) >= 2:
        t0 = tokens[0].strip()
        if _PUNCT_ONLY_TOKEN.match(t0) or t0 in ("=",):
            prefix_attempts.append((1, {0, 1}))
        elif _token_has_qty_signal(tokens[1]):
            prefix_attempts.append((1, {1}))

    seen: set[tuple[int, ...]] = set()
    for qty_idx, consumed in prefix_attempts:
        key = tuple(sorted(consumed))
        if key in seen:
            continue
        seen.add(key)
        tok = tokens[qty_idx]
        if not _token_has_qty_signal(tok):
            continue
        following = " ".join(tokens[j] for j in range(len(tokens)) if j > qty_idx)
        qty = _parse_qty_from_token(tok, following=following, prefix_column=True)
        if qty:
            return qty, _remainder_tokens(tokens, consumed), "qty_positional_prefix"

    for back in (1, 2):
        if len(tokens) < back:
            continue
        qty_idx = len(tokens) - back
        tok = tokens[qty_idx]
        if not _token_has_qty_signal(tok):
            continue
        preceding = " ".join(tokens[:qty_idx])
        qty = _parse_qty_from_token(tok, preceding=preceding, prefix_column=False)
        if not qty:
            continue
        if len(preceding.strip()) < 4 or not re.search(r"[A-Z]{3,}", preceding, re.I):
            continue
        return qty, preceding.strip(), "qty_positional_suffix"

    return None, " ".join(tokens), ""


def extract_qty_from_raw_line(
    raw_line: str,
    code: str,
) -> tuple[str | None, str, str]:
    """
    Extract Qté via positional tokenization after product code.
    Returns (qty_str, designation_raw_remainder, source_tag).
    """
    after = _text_after_code(raw_line, code)
    if not after:
        return None, "", ""
    tokens = _split_positional_tokens(after)
    return _extract_qty_positional_from_tokens(tokens)


def lock_quantite(
    row: dict[str, Any],
    qty: Any,
    *,
    source: str = "qty_locked",
    confidence: float = 0.86,
) -> dict[str, Any]:
    """Persist quantite on the row and mark it immutable for later sanitize passes."""
    try:
        qf = float(qty)
    except (TypeError, ValueError):
        return row
    if qf <= 0:
        return row
    q_out: int | float = int(qf) if qf == int(qf) else qf
    row["quantite"] = q_out
    row["qty"] = q_out
    row["_quantite_locked"] = True
    src = dict(row.get("_field_source") or {})
    fconf = dict(row.get("_field_confidence") or {})
    src["quantite"] = source
    fconf["quantite"] = confidence
    row["_field_source"] = src
    row["_field_confidence"] = fconf
    return row


def extract_and_lock_quantite_only(item: dict[str, Any]) -> dict[str, Any]:
    """Step 1–2: extract qty from raw uncleaned line and lock (no designation sanitize)."""
    row = dict(item)
    if quantite_is_locked(row):
        return row

    code = str(
        row.get("code") or row.get("code_pct") or row.get("code_article") or ""
    ).strip()
    raw_line = resolve_raw_row_text(row)
    if raw_line and not str(row.get("_row_txt") or "").strip():
        row["_row_txt"] = raw_line

    qty_s = None
    remain = ""
    source = ""
    conf = 0.86

    if raw_line and code:
        qty_s, remain, source = extract_mp_code_qty_from_raw(raw_line, code)
        if not qty_s:
            qty_s, remain, source = extract_qty_from_raw_line(raw_line, code)
        conf = 0.89 if source == "mp_code_prefix" else (
            0.88 if source in ("qty_positional_suffix", "qty_pattern_b") else 0.86
        )

    if qty_s:
        row = lock_quantite(row, qty_s, source=source or "qty_locked", confidence=conf)
        if remain:
            row["designation"] = remain
    return row


def process_line_extract_then_clean(item: dict[str, Any]) -> dict[str, Any]:
    """Canonical per-row pipeline: Extract qty from raw line → lock → sanitize designation."""
    row = extract_and_lock_quantite_only(dict(item))
    locked_qty = row.get("quantite")
    code = str(row.get("code") or row.get("code_pct") or row.get("code_article") or "")
    desig_raw = str(row.get("designation") or "").strip()
    if desig_raw:
        cleaned = sanitize_pharma_designation(
            desig_raw,
            locked_qty,
            quantite_locked=quantite_is_locked(row),
            code=code,
        )
        if cleaned:
            row["designation"] = cleaned
            src = dict(row.get("_field_source") or {})
            fconf = dict(row.get("_field_confidence") or {})
            if src.get("designation") not in ("gemini_vision",):
                src["designation"] = "local_sanitize"
                fconf["designation"] = max(float(fconf.get("designation") or 0), 0.78)
                row["_field_source"] = src
                row["_field_confidence"] = fconf
    return row


def extract_qty_from_text_segment(text: str) -> tuple[str | None, str]:
    """Split Qté from a post-code fragment using the same positional tokenizer."""
    t = str(text or "").strip()
    if not t:
        return None, t
    tokens = _split_positional_tokens(t)
    qty, remain, _src = _extract_qty_positional_from_tokens(tokens)
    if qty:
        return qty, remain
    return None, t


def recover_line_quantity(item: dict[str, Any]) -> dict[str, Any]:
    """Recover missing quantite — prefers raw _row_txt before sanitized designation."""
    row = dict(item)
    if quantite_is_locked(row):
        return row

    raw_line = str(row.get("_row_txt") or "").strip()
    code = str(row.get("code") or row.get("code_pct") or row.get("code_article") or "")

    if raw_line and code:
        qty_s, remain, source = extract_qty_from_raw_line(raw_line, code)
        if qty_s:
            conf = 0.88 if source in ("qty_positional_suffix", "qty_pattern_b") else 0.86
            row = lock_quantite(row, qty_s, source=source, confidence=conf)
            if remain:
                row["designation"] = remain
            return row

    after = _text_after_code(raw_line, code) if raw_line and code else ""
    if not after:
        after = str(row.get("designation") or "").strip()
    qty_s, remain = extract_qty_from_text_segment(after)
    if qty_s:
        row = lock_quantite(row, qty_s, source="qty_recovered_row", confidence=0.84)
        if remain:
            row["designation"] = remain
    return row


def _strip_locked_row_prefix(
    text: str,
    *,
    code: str = "",
    quantite: Any = None,
) -> str:
    """
    When qty is locked, strip code + locked qty + rogue checkmark digits from designation.
    e.g. '302970 24 7 AMLODIPINE...' -> 'AMLODIPINE...'
    """
    t = str(text or "").strip()
    if not t:
        return t
    code_u = str(code or "").strip().upper()
    code_digits = re.sub(r"\D", "", code_u) if code_u else ""
    q_raw = str(quantite or "").strip()
    q_digits = re.sub(r"\D", "", q_raw.split(".")[0]) if q_raw else ""

    # One-pass: CODE QTY [single-digit ink artifact] before drug name
    if code_u and q_digits:
        combo = (
            rf'^\s*["\']?{re.escape(code_u)}\s+{re.escape(q_digits)}\s+'
            rf"(?:\d\s+)?(?=[A-Z])"
        )
        if re.match(combo, t, re.IGNORECASE):
            t = re.sub(combo, "", t, count=1, flags=re.IGNORECASE).strip()
    if code_digits and q_digits and code_digits != code_u:
        combo_digits = (
            rf'^\s*["\']?{re.escape(code_digits)}\s+{re.escape(q_digits)}\s+'
            rf"(?:\d\s+)?(?=[A-Z])"
        )
        if re.match(combo_digits, t, re.IGNORECASE):
            t = re.sub(combo_digits, "", t, count=1, flags=re.IGNORECASE).strip()

    if code_u:
        t = re.sub(
            rf'^\s*["\']?{re.escape(code_u)}\b\s*',
            "",
            t,
            flags=re.IGNORECASE,
        ).strip()
        if code_digits and code_digits != code_u:
            t = re.sub(
                rf"^\s*['\"]?{re.escape(code_digits)}\b\s*",
                "",
                t,
                flags=re.IGNORECASE,
            ).strip()
    return strip_qty_from_designation(t, quantite)


def strip_qty_from_designation(designation: str, quantite: Any = None) -> str:
    """Remove leading quantity bleed when it matches the Qté column value."""
    t = str(designation or "").strip()
    if not t:
        return t
    q_raw = str(quantite or "").strip()
    q_digits = re.sub(r"\D", "", q_raw.split(".")[0]) if q_raw else ""
    if q_digits:
        m = re.match(r"^\s*(\d{1,5})(?:[,.]\d+)?\s+(.+)$", t)
        if m and re.sub(r"\D", "", m.group(1)) == q_digits:
            t = m.group(2).strip()
        m2 = re.match(rf"^\s*{re.escape(q_digits)}\s*[\W_]+\s*(.+)$", t)
        if m2:
            t = m2.group(1).strip()
    m = re.match(r"^\s*(\d{1,5})\s+([A-Z].+)$", t, re.IGNORECASE)
    if m and not re.match(r"^\d+\s*MG\b", t, re.I):
        t = m.group(2).strip()
    if q_digits:
        m3 = re.match(r"^\s*(\d)\s+([A-Z].+)$", t, re.IGNORECASE)
        if m3 and m3.group(1) != q_digits and not re.match(r"^\d+\s*MG\b", t, re.I):
            t = m3.group(2).strip()
    return t


def sanitize_pharma_designation(
    s: str,
    quantite: Any = None,
    *,
    quantite_locked: bool = False,
    code: str = "",
) -> str:
    """
    Trim designation to commercial name + dosage + form.
    Starts with uppercase letter; ends with digit or COMP.
    """
    locked = quantite_locked or bool(str(quantite or "").strip())
    t = clean_designation_noise(str(s or ""))
    if quantite_locked and (code or quantite):
        t = _strip_locked_row_prefix(t, code=code, quantite=quantite)
    elif locked:
        t = strip_qty_from_designation(t, quantite)
    else:
        t = strip_qty_from_designation(t, quantite)
    while True:
        prev = t
        t = _strip_leading_junk(t, quantite_locked=locked)
        t = _TRAILING_JUNK.sub("", t).strip()
        if t == prev:
            break
    core = extract_pharma_designation_core(t)
    if core:
        t = core
    else:
        m = _PHARMA_DESIGNATION_CORE.search(t)
        if m:
            t = m.group(1).strip()
        else:
            m2 = re.search(r"[A-Z][A-Z0-9\s\./\-]{2,}", t, re.IGNORECASE)
            if m2:
                t = m2.group(0).strip()
    t = re.sub(r"\s*([.,;:!?¢~`>\-]+)\s*$", "", t).strip()
    t = re.sub(r"^(op|ae|gS)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if t.upper().endswith(" COMP"):
        t = t[:-5] + " COMP"
    if t and not re.match(r"^[A-Z]", t, re.I):
        m3 = re.search(r"[A-Z][A-Z0-9\s\./\-]+", t)
        if m3:
            t = m3.group(0).strip()
    return t


def apply_extract_and_lock_quantite(lines: list[dict]) -> list[dict]:
    """Step 1–2 only: extract qty from raw line and lock (no designation sanitize)."""
    return [extract_and_lock_quantite_only(dict(item)) for item in lines]


def apply_designation_cleanup_only(lines: list[dict]) -> list[dict]:
    """Step 3 only: extract+lock first if needed, then sanitize designation."""
    out = []
    for item in lines:
        row = dict(item)
        if not quantite_is_locked(row):
            row = extract_and_lock_quantite_only(row)
        locked_qty = row.get("quantite")
        code = str(row.get("code") or row.get("code_pct") or row.get("code_article") or "")
        desig_raw = str(row.get("designation") or "").strip()
        if quantite_is_locked(row) and code and desig_raw.upper().startswith(code.upper()):
            row_txt = str(row.get("_row_txt") or "").strip()
            if row_txt:
                desig_raw = row_txt
        if desig_raw:
            cleaned = sanitize_pharma_designation(
                desig_raw,
                locked_qty,
                quantite_locked=quantite_is_locked(row),
                code=code,
            )
            if cleaned:
                row["designation"] = cleaned
                src = dict(row.get("_field_source") or {})
                fconf = dict(row.get("_field_confidence") or {})
                if src.get("designation") not in ("gemini_vision",):
                    src["designation"] = "local_sanitize"
                    fconf["designation"] = max(float(fconf.get("designation") or 0), 0.78)
                    row["_field_source"] = src
                    row["_field_confidence"] = fconf
        out.append(row)
    return out


def apply_local_designation_cleanup(lines: list[dict]) -> list[dict]:
    """Extract → lock quantite → clean designation (canonical wrapper)."""
    return apply_designation_cleanup_only(apply_extract_and_lock_quantite(lines))


def recover_lines_quantites_from_raw(
    lines: list[dict],
    *,
    combined_body: str = "",
) -> list[dict]:
    """
    Re-scan _row_txt for Qté when table/Gemini left quantite empty.
    Avenir MEDIS BC: 6-digit code then quantity (e.g. 301475 30 X MEDISIUM...).
    """
    out: list[dict] = []
    for item in lines or []:
        row = dict(item)
        if quantite_is_locked(row) and line_has_quantite(row):
            out.append(row)
            continue

        code = str(row.get("code") or row.get("code_pct") or row.get("code_article") or "")
        raw = str(row.get("_row_txt") or "").strip()
        if combined_body and code and (not raw or not _row_txt_has_qty_after_code(raw, code)):
            body_line = _find_body_line_for_code(combined_body, code)
            if body_line and (
                not raw or len(body_line) > len(raw) or _row_txt_has_qty_after_code(body_line, code)
            ):
                row["_row_txt"] = body_line

        out.append(extract_and_lock_quantite_only(row))
    return out


def sanitize_product_code(token: str) -> str:
    """Normalize MP (6-digit preferred) or PF article codes."""
    code = normalize_code_token(token)
    if not code:
        return ""
    if code.startswith("PF"):
        if len(code) >= 11:
            return code[:11]
        return code
    digits = re.sub(r"\D", "", code)
    if 5 <= len(digits) <= 7:
        if len(digits) < 6:
            return digits.zfill(6)
        return digits[:6] if len(digits) == 6 else digits
    if len(digits) > 7:
        return digits[:6]
    return digits if digits else code
