"""Pharmasud 6-column date-anchored parser."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ocr_line_clean import (
    clean_designation_noise,
    collapse_whitespace,
    normalize_code_token,
    repair_date_ocr_fragment,
)
from schema_v2 import PharmasudLineItemV2

CODE_PCT = re.compile(r"^([A-Z]{2,4}\d{2,12}|\d{4,7})\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def _find_date_span(line: str) -> Optional[Tuple[int, int, str]]:
    work = repair_date_ocr_fragment(line)
    m = DATE_RE.search(work)
    if not m:
        return None
    return m.start(), m.end(), m.group(1)


def _validate_date_parts(s: str) -> str:
    parts = s.split("/")
    if len(parts) != 3:
        return s
    try:
        d, m_, y = int(parts[0]), int(parts[1]), int(parts[2])
        if 1 <= d <= 31 and 1 <= m_ <= 12 and 1990 <= y <= 2100:
            return f"{d:02d}/{m_:02d}/{y}"
    except ValueError:
        pass
    return s


def parse_pharmasud_line(raw_line: str) -> Optional[PharmasudLineItemV2]:
    line = collapse_whitespace(raw_line)
    if len(line) < 8:
        return None
    dm = _find_date_span(line)
    if not dm:
        return None
    d_start, d_end, date_raw = dm
    date_peremption = _validate_date_parts(date_raw)

    left = line[:d_start].strip()
    right = line[d_end:].strip()

    m_code = CODE_PCT.match(left)
    if not m_code:
        return None
    code_pct = normalize_code_token(m_code.group(1))
    after_code = left[m_code.end() :].strip()
    nums_left = re.findall(r"\b\d{1,5}\b", after_code)
    right_nums = re.findall(r"\b\d{1,5}\b", right)

    quantite_commande = ""
    nb_cartons = ""
    unite_carton = ""

    if len(nums_left) >= 2:
        quantite_commande = nums_left[0]
        nb_cartons = nums_left[1]
    elif len(nums_left) == 1:
        quantite_commande = nums_left[0]
    if right_nums:
        unite_carton = right_nums[-1]

    desig_src = after_code
    for n in nums_left:
        desig_src = desig_src.replace(n, " ", 1)
    designation = clean_designation_noise(re.sub(r"\s+", " ", desig_src))

    conf = 0.55
    if quantite_commande and date_peremption:
        conf = 0.78
    if code_pct and designation:
        conf = min(1.0, conf + 0.1)

    return PharmasudLineItemV2(
        code_pct=code_pct,
        designation=designation,
        quantite_commande=quantite_commande,
        nb_cartons=nb_cartons,
        unite_carton=unite_carton,
        date_peremption=date_peremption,
        line_confidence=round(conf, 3),
        raw_line=raw_line.strip(),
    )


def parse_pharmasud_lines(body_text: str) -> List[dict]:
    seen = set()
    out: List[dict] = []
    for raw in (body_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parsed = parse_pharmasud_line(line)
        if not parsed:
            continue
        key = (parsed.code_pct, parsed.date_peremption, parsed.raw_line[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(parsed.model_dump(exclude_none=True))
    return out
