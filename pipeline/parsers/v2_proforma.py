"""Proforma 7-column outside-in line parser."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

try:
    from pipeline.ocr_line_clean import (
        _ocr_normalize_numeric_token,
        clean_designation_noise,
        is_pf_like,
        is_proforma_pct_token,
        normalize_code_token,
        parse_french_money_token,
        pre_clean_ocr_line,
        split_tokens_respecting_numbers,
    )
except ImportError:
    from ocr_line_clean import (
        _ocr_normalize_numeric_token,
        clean_designation_noise,
        is_pf_like,
        is_proforma_pct_token,
        normalize_code_token,
        parse_french_money_token,
        pre_clean_ocr_line,
        split_tokens_respecting_numbers,
    )
try:
    from pipeline.schema_v2 import ProformaLineItemV2
except ImportError:
    from schema_v2 import ProformaLineItemV2

_UNITS = {"B", "FL", "UI", "MG", "G", "ML", "L", "CP", "SER", "PCS", "BOITE", "BT"}


def _merge_french_amount_tokens(tokens: List[str]) -> List[str]:
    """Join split OCR fragments: small head + comma-decimal, or grouped thousands."""
    if not tokens:
        return tokens
    out: List[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt_tok = tokens[i + 1] if i + 1 < len(tokens) else ""
        if i + 1 < len(tokens) and re.match(r"^\d{1,2}$", t) and re.match(r"^\d{3},\d{2,3}$", nxt_tok):
            out.append(f"{t} {nxt_tok}")
            i += 2
            continue
        if i + 1 < len(tokens) and re.match(r"^\d{3}$", t) and re.match(r"^\d{3},\d{2,3}$", nxt_tok):
            out.append(f"{t} {nxt_tok}")
            i += 2
            continue
        if i + 1 < len(tokens) and re.match(r"^\d{1,3}$", t) and re.match(r"^\d{3}\s+\d{3},\d{2,3}$", nxt_tok):
            out.append(f"{t} {nxt_tok}")
            i += 2
            continue
        out.append(t)
        i += 1
    return out


_MONEY_FRAGMENT_RE = re.compile(
    r"(?:\d{1,3}(?:\s\d{3})+[,.]\d{1,3}|\d{1,7}[,.]\d{1,3})"
)


def _regex_trailer_qty_pu_montant(raw: str) -> Optional[Tuple[str, str, str, str]]:
    """
    When token triplet matching fails (OCR uses dots, odd spacing), recover
    qty + PU + montant from the line tail. Returns (qty, pu, montant, code_segment).
    """
    line = pre_clean_ocr_line(raw)
    hits = list(_MONEY_FRAGMENT_RE.finditer(line))
    if len(hits) < 2:
        return None
    pu_s = hits[-2].group(0).strip().replace(" ", "")
    mt_s = hits[-1].group(0).strip().replace(" ", "")
    seg = line[: hits[-2].start()].rstrip()
    toks = seg.split()
    if toks:
        raw_qty = toks[-1]
        qn = _ocr_normalize_numeric_token(raw_qty).replace(" ", "")
        if re.match(r"^\d{1,5}$", qn) and not parse_french_money_token(raw_qty)[0]:
            code_seg = " ".join(toks[:-1]).strip()
            return qn, pu_s, mt_s, code_seg
    if len(hits) >= 3:
        q_raw = hits[-3].group(0).strip()
        if parse_french_money_token(q_raw)[0]:
            code_seg = line[: hits[-3].start()].rstrip()
            return q_raw.replace(" ", ""), pu_s, mt_s, code_seg
    return None


def _token_trailer_score(t: str) -> float:
    is_m, v = parse_french_money_token(t)
    if is_m and v is not None:
        return 1.0
    if re.match(r"^\d{1,5}$", t.replace(" ", "")):
        return 0.55
    return 0.0


def _find_trailing_money_triplet(tokens: List[str]) -> Tuple[Optional[int], List[str], float]:
    """Rightmost qty + PU + montant: last two tokens must be French money."""
    n = len(tokens)
    for start in range(n - 3, -1, -1):
        chunk = tokens[start : start + 3]
        a, b, c = chunk
        b_ok, b_v = parse_french_money_token(b)
        c_ok, c_v = parse_french_money_token(c)
        if not (b_ok and b_v and c_ok and c_v):
            continue
        a_score = _token_trailer_score(a)
        if a_score < 0.5:
            continue
        ssum = a_score + 1.0 + 1.0
        conf = min(1.0, 0.55 + 0.14 * ssum)
        return start, list(chunk), conf
    return None, [], 0.25


def parse_proforma_line(raw_line: str) -> Optional[ProformaLineItemV2]:
    line = pre_clean_ocr_line(raw_line)
    if len(line) < 8:
        return None
    tokens = _merge_french_amount_tokens(split_tokens_respecting_numbers(line))
    if len(tokens) < 2:
        return None

    idx_money, money_vals, conf = _find_trailing_money_triplet(tokens)
    head_tokens: List[str] = []
    qty_s = ""
    pu_s = ""
    mt_s = ""
    conf_used = 0.72

    if idx_money is not None and len(money_vals) >= 3:
        quantite_t, pu_t, montant_t = money_vals[0], money_vals[1], money_vals[2]
        qty_s = str(quantite_t).replace(" ", "")
        pu_s = str(pu_t).replace(" ", "")
        mt_s = str(montant_t).replace(" ", "")
        head_tokens = tokens[:idx_money]
        conf_used = conf
    else:
        rx = _regex_trailer_qty_pu_montant(raw_line)
        if not rx:
            return None
        qty_s, pu_s, mt_s, code_seg = rx
        head_tokens = _merge_french_amount_tokens(split_tokens_respecting_numbers(code_seg)) if code_seg else []
        conf_used = 0.58

    if not head_tokens:
        return None

    code_pct = ""
    code_article = ""
    ip = 0
    while ip < len(head_tokens) and not is_proforma_pct_token(head_tokens[ip]):
        ip += 1
    if ip < len(head_tokens) and is_proforma_pct_token(head_tokens[ip]):
        code_pct = re.sub(r"\D", "", head_tokens[ip])[:7]
        ip += 1
    while ip < len(head_tokens) and not is_pf_like(head_tokens[ip]):
        ip += 1
    if ip < len(head_tokens) and is_pf_like(head_tokens[ip]):
        code_article = normalize_code_token(head_tokens[ip])
        ip += 1

    middle = head_tokens[ip:]
    unite_mesure = None
    if middle and str(middle[-1]).upper().rstrip(".") in _UNITS:
        unite_mesure = str(middle[-1]).upper().rstrip(".")
        middle = middle[:-1]
    designation_article = clean_designation_noise(" ".join(middle))
    if not designation_article or len(designation_article) < 2:
        return None

    if code_pct and code_article:
        conf_used = min(1.0, conf_used + 0.12)
    return ProformaLineItemV2(
        code_pct=code_pct,
        code_article=code_article,
        designation_article=designation_article,
        unite_mesure=unite_mesure,
        quantite=qty_s,
        prix_unitaire=pu_s,
        montant=mt_s,
        line_confidence=round(conf_used, 3),
        raw_line=raw_line.strip(),
    )


def salvage_proforma_line(raw_line: str) -> Optional[ProformaLineItemV2]:
    """When strict triplet parsing fails, keep the line as a low-confidence partial row."""
    line = pre_clean_ocr_line(raw_line.strip())
    if len(line) < 10:
        return None
    tokens = _merge_french_amount_tokens(split_tokens_respecting_numbers(line))
    if len(tokens) < 2:
        return None
    code_pct = ""
    code_article = ""
    for t in tokens:
        if is_proforma_pct_token(t) and not code_pct:
            code_pct = re.sub(r"\D", "", t)[:7]
    for t in tokens:
        if is_pf_like(t) and not code_article:
            code_article = normalize_code_token(t)
    if not code_article or not is_pf_like(code_article):
        return None
    skip = set()
    for t in tokens:
        m_ok, _ = parse_french_money_token(t)
        if m_ok:
            skip.add(t)
            continue
        if is_proforma_pct_token(t) or is_pf_like(t):
            skip.add(t)
    middle = [t for t in tokens if t not in skip]
    designation_article = clean_designation_noise(" ".join(middle))
    if not designation_article or len(designation_article) < 2:
        designation_article = clean_designation_noise(line)
    if not designation_article or len(designation_article) < 2:
        return None
    qx = px = mx = ""
    trip = _regex_trailer_qty_pu_montant(raw_line)
    if trip:
        qx, px, mx, _ = trip
    conf_salv = 0.38 if (qx or px or mx) else 0.28
    return ProformaLineItemV2(
        code_pct=code_pct,
        code_article=code_article,
        designation_article=designation_article,
        unite_mesure=None,
        quantite=qx,
        prix_unitaire=px,
        montant=mx,
        line_confidence=conf_salv,
        raw_line=raw_line.strip(),
    )


def parse_proforma_lines(body_text: str) -> List[dict]:
    seen = set()
    out: List[dict] = []
    for raw in (body_text or "").splitlines():
        line = raw.strip()
        if not line or len(line) < 10:
            continue
        parsed = parse_proforma_line(line)
        if not parsed:
            parsed = salvage_proforma_line(raw)
            if not parsed:
                continue
        key = (parsed.code_pct, parsed.code_article, parsed.montant, parsed.raw_line[:120], parsed.quantite, parsed.prix_unitaire)
        if key in seen:
            continue
        seen.add(key)
        out.append(parsed.model_dump(exclude_none=True))
    return out
