"""3-column BC parsers (Avenir, Omnipharm) — noise-tolerant quantity."""

from __future__ import annotations

import re
from typing import List, Optional

from ocr_line_clean import clean_designation_noise, normalize_code_token, pre_clean_ocr_line
from schema_v2 import SimpleBCLineItemV2

CODE_START_RE = re.compile(
    r"^([A-Z]{2,4}\d{2,14}|\d{4,7})\b",
    re.IGNORECASE,
)

_QTY_SCAN = re.compile(r"\b(\d{1,5})\b")


def _first_plausible_qty_after(text: str, start: int, max_qty: int = 8000) -> Optional[tuple]:
    for m in _QTY_SCAN.finditer(text, start):
        q = int(m.group(1))
        if 0 < q <= max_qty:
            if re.match(r"^0+\d", m.group(1)) and len(m.group(1)) > 3:
                continue
            return m.start(), m.end(), str(q)
    return None


def parse_simple_bc_line(raw_line: str) -> Optional[SimpleBCLineItemV2]:
    line = pre_clean_ocr_line(raw_line)
    if len(line) < 5:
        return None
    m = CODE_START_RE.match(line)
    if not m:
        return None
    raw_code = m.group(1)
    code = normalize_code_token(raw_code)
    if not code or len(code) < 4:
        return None
    rest = line[m.end() :].strip()
    if len(rest) < 2:
        return None
    qty_hit = _first_plausible_qty_after(rest, 0)
    if not qty_hit:
        return SimpleBCLineItemV2(
            code=code,
            quantite="",
            designation=clean_designation_noise(rest),
            line_confidence=0.42,
            raw_line=raw_line.strip(),
        )
    _, end, qty_s = qty_hit
    designation = clean_designation_noise(rest[end:].strip())
    if not designation or len(designation) < 2:
        return None
    conf = 0.72 if qty_s else 0.45
    return SimpleBCLineItemV2(
        code=code,
        quantite=qty_s,
        designation=designation,
        line_confidence=round(conf, 3),
        raw_line=raw_line.strip(),
    )


def parse_simple_bc_lines(body_text: str) -> List[dict]:
    seen = set()
    out: List[dict] = []
    for raw in (body_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parsed = parse_simple_bc_line(line)
        if not parsed:
            continue
        key = (parsed.code, parsed.raw_line[:100])
        if key in seen:
            continue
        seen.add(key)
        out.append(parsed.model_dump(exclude_none=True))
    return out
