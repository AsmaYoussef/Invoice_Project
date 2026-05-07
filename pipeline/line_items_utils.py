"""Shared helpers for legacy line-item deduplication and merge (importable without Streamlit)."""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def legacy_line_merge_key(item: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    """
    Stable row identity for table vs OCR merge and intra-table dedup.
    Distinguishes multiple articles sharing the same Code PCT.
    """
    pct = str(item.get("code_pct") or "").strip().upper()
    art = str(item.get("code_article") or "").strip().upper()
    co = str(item.get("code") or "").strip().upper()
    if not pct and co:
        if re.fullmatch(r"\d{4,8}", co):
            pct = co
        elif re.match(r"^PF", co) or re.match(r"^[A-Z]{2,4}\d{5,12}$", co):
            art = art or co
    mt = item.get("montant")
    mt_s = ""
    if mt is not None and str(mt).strip() != "":
        try:
            mt_s = f"{float(mt):.4f}"
        except (TypeError, ValueError):
            mt_s = str(mt).strip()[:24]
    des = str(item.get("designation") or "").strip()[:120]
    row_snip = str(item.get("_row_txt") or "").strip()[:140]
    return (pct, art, mt_s, des, row_snip)
