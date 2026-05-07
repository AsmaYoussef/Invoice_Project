"""Format-specific v2 line parsers."""

from __future__ import annotations

from typing import List

from .v2_pharmasud import parse_pharmasud_lines
from .v2_proforma import parse_proforma_lines
from .v2_simple_bc import CODE_START_RE, parse_simple_bc_lines
from schema_v2 import UnknownFamilyLineItemV2

FAMILY_PROFORMA = "proforma_modele"
FAMILY_BC_AVENIR = "bc_avenir"
FAMILY_BC_OMNIPHARM = "bc_omnipharm"
FAMILY_BC_PHARMASUD = "bc_pharmasud"
FAMILY_UNKNOWN = "unknown"


def parse_body_lines_v2(family: str, body_text: str) -> List[dict]:
    if family == FAMILY_PROFORMA:
        return parse_proforma_lines(body_text)
    if family == FAMILY_BC_PHARMASUD:
        return parse_pharmasud_lines(body_text)
    if family in (FAMILY_BC_AVENIR, FAMILY_BC_OMNIPHARM):
        return parse_simple_bc_lines(body_text)
    return _parse_unknown_lines(body_text)


def _parse_unknown_lines(body_text: str) -> List[dict]:
    out: List[dict] = []
    for raw in (body_text or "").splitlines():
        line = raw.strip()
        if len(line) < 5:
            continue
        m = CODE_START_RE.match(line)
        if not m:
            continue
        code = m.group(1).strip().upper()
        if len(code) < 4:
            continue
        out.append(UnknownFamilyLineItemV2(code=code, raw_line=line, line_confidence=0.35).model_dump(exclude_none=True))
    return out
