"""Gemini Vision gap-filling: append missing table rows without touching healthy Tesseract rows."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any, Callable

import cv2
import numpy as np

try:
    from pipeline.ai.gemini_client import generate_vision_json, is_vision_enabled
    from pipeline.ocr_line_clean import (
        extract_and_lock_quantite_only,
        line_has_quantite,
        normalize_code_token,
        quantite_is_locked,
        sanitize_pharma_designation,
    )
except ImportError:
    from ai.gemini_client import generate_vision_json, is_vision_enabled
    from ocr_line_clean import (
        extract_and_lock_quantite_only,
        line_has_quantite,
        normalize_code_token,
        quantite_is_locked,
        sanitize_pharma_designation,
    )

MAX_VISION_ROWS = 200
MAX_IMAGE_PX = 2048

GAP_FILL_VISION_SYSTEM_PROMPT = """You are a pharmaceutical invoice table extraction agent.
Study the printed product table grid in the document image.

Rules:
1. Read ONLY the printed table structure (Code, Qté, Désignation columns).
2. Ignore handwritten ink marks, checkmarks, stamps, and margin noise.
3. Return EVERY visible product row in the table body, including rows that may have irregular spacing.
4. Use the numeric product code exactly as printed (6-digit MP codes or PF article codes).
5. Put the order quantity in quantite (integer when whole).
6. Put the commercial drug designation in designation (no code prefix, no quantity prefix).

Return strict JSON only:
{
  "line_items": [
    { "code": "302970", "quantite": 24, "designation": "AMLODIPINE MEDIS 10 MG B/30 COMP" }
  ]
}
Use numbers for quantite when known; omit rows you cannot read confidently.
"""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def is_gap_filler_enabled() -> bool:
    if not is_vision_enabled():
        return False
    return _env_bool("GEMINI_GAP_FILLER_ENABLED", default=False)


def _resize_image_rgb(img_rgb: np.ndarray) -> np.ndarray:
    h, w = img_rgb.shape[:2]
    max_px = MAX_IMAGE_PX
    if max(h, w) <= max_px:
        return img_rgb
    scale = max_px / float(max(h, w))
    return cv2.resize(
        img_rgb,
        (int(w * scale), int(h * scale)),
        interpolation=cv2.INTER_AREA,
    )


def _encode_page_jpeg(img_rgb: np.ndarray) -> bytes:
    resized = _resize_image_rgb(img_rgb)
    bgr = cv2.cvtColor(resized, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise ValueError("Failed to encode page image")
    return buf.tobytes()


def _row_code_keys(item: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("code", "code_pct", "code_article"):
        raw = str(item.get(field) or "").strip()
        if not raw:
            continue
        keys.add(raw.upper())
        norm = normalize_code_token(raw)
        if norm:
            keys.add(norm.upper())
    return keys


def _vision_code_keys(code: str) -> set[str]:
    raw = str(code or "").strip()
    if not raw:
        return set()
    return {raw.upper(), normalize_code_token(raw).upper()}


def _is_tesseract_row_broken(row: dict[str, Any]) -> bool:
    """True when Tesseract row lacks usable designation or quantity."""
    desig = str(row.get("designation") or "").strip()
    if len(desig) < 3:
        return True
    if not line_has_quantite(row):
        return True
    code = str(row.get("code") or row.get("code_pct") or row.get("code_article") or "").strip()
    if not code:
        return True
    return False


def _parse_vision_qty(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    try:
        qf = float(str(raw).replace(",", ".").replace(" ", ""))
        if qf <= 0:
            return None
        return int(qf) if qf == int(qf) else qf
    except (TypeError, ValueError):
        return None


def _sanitize_vision_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    code = normalize_code_token(str(row.get("code") or "").strip())
    if not code or len(code) < 4:
        return None
    desig = str(row.get("designation") or "").strip()
    qty = _parse_vision_qty(row.get("quantite"))
    if not desig and qty is None:
        return None
    return {"code": code, "quantite": qty, "designation": desig}


def _build_existing_code_index(lines: list[dict[str, Any]]) -> dict[str, int]:
    """Map normalized code variants to first row index."""
    index: dict[str, int] = {}
    for i, row in enumerate(lines):
        for key in _row_code_keys(row):
            index.setdefault(key, i)
    return index


def _finalize_gap_row(row: dict[str, Any], *, source: str = "gemini_gap_fill") -> dict[str, Any]:
    """Lock quantity keys then sanitize designation for UI parity with Tesseract rows."""
    out = extract_and_lock_quantite_only(dict(row))
    code = str(out.get("code") or out.get("code_pct") or out.get("code_article") or "")
    locked_qty = out.get("quantite")
    desig_raw = str(out.get("designation") or "").strip()
    if desig_raw:
        cleaned = sanitize_pharma_designation(
            desig_raw,
            locked_qty,
            quantite_locked=quantite_is_locked(out),
            code=code,
        )
        if cleaned:
            out["designation"] = cleaned
            src = dict(out.get("_field_source") or {})
            fconf = dict(out.get("_field_confidence") or {})
            if src.get("designation") != "gemini_vision":
                src["designation"] = source
                fconf["designation"] = max(float(fconf.get("designation") or 0), 0.78)
            out["_field_source"] = src
            out["_field_confidence"] = fconf
    return out


def _vision_row_to_legacy_row(vision_row: dict[str, Any]) -> dict[str, Any]:
    code = vision_row["code"]
    desig = str(vision_row.get("designation") or "").strip()
    qty = vision_row.get("quantite")
    qty_s = str(qty) if qty is not None else ""
    row_txt = " ".join(p for p in (code, qty_s, desig) if p).strip()
    row: dict[str, Any] = {
        "code": code,
        "designation": desig,
        "_row_txt": row_txt,
        "_field_source": {
            "code": "gemini_gap_fill",
            "quantite": "gemini_gap_fill",
            "designation": "gemini_gap_fill",
        },
        "_field_confidence": {
            "code": 0.82,
            "quantite": 0.80,
            "designation": 0.78,
        },
    }
    if qty is not None:
        row["quantite"] = qty
    if re.fullmatch(r"\d{4,8}", code):
        row["code_pct"] = code
    elif code.upper().startswith("PF"):
        row["code_article"] = code
    return row


def _enrich_broken_row(existing: dict[str, Any], vision_row: dict[str, Any]) -> dict[str, Any]:
    """Safely overwrite broken fields on an existing Tesseract row from Vision data."""
    out = deepcopy(existing)
    code = vision_row["code"]
    out["code"] = str(out.get("code") or code).strip() or code
    if re.fullmatch(r"\d{4,8}", code):
        out["code_pct"] = out.get("code_pct") or code
    elif code.upper().startswith("PF"):
        out["code_article"] = out.get("code_article") or code

    vision_desig = str(vision_row.get("designation") or "").strip()
    if vision_desig and len(vision_desig) >= 3:
        out["designation"] = vision_desig
        src = dict(out.get("_field_source") or {})
        fconf = dict(out.get("_field_confidence") or {})
        src["designation"] = "gemini_gap_fill"
        fconf["designation"] = max(float(fconf.get("designation") or 0), 0.80)
        out["_field_source"] = src
        out["_field_confidence"] = fconf

    vision_qty = vision_row.get("quantite")
    if vision_qty is not None and not line_has_quantite(out):
        out["quantite"] = vision_qty
        src = dict(out.get("_field_source") or {})
        fconf = dict(out.get("_field_confidence") or {})
        src["quantite"] = "gemini_gap_fill"
        fconf["quantite"] = max(float(fconf.get("quantite") or 0), 0.80)
        out["_field_source"] = src
        out["_field_confidence"] = fconf

    qty_s = str(out.get("quantite") or vision_qty or "").strip()
    desig = str(out.get("designation") or "").strip()
    out["_row_txt"] = " ".join(p for p in (code, qty_s, desig) if p).strip()
    return _finalize_gap_row(out, source="gemini_gap_fill")


def merge_vision_gaps(
    existing_lines: list[dict[str, Any]],
    vision_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Append missing Vision rows; enrich broken Tesseract matches; discard healthy duplicates.
    Tesseract is master authority when the existing row is healthy.
    """
    audit: dict[str, Any] = {
        "ok": True,
        "status": "merged",
        "vision_row_count": 0,
        "rows_backfilled": 0,
        "rows_enriched": 0,
        "rows_discarded": 0,
        "rows_skipped_invalid": 0,
        "error": "",
    }

    out = [deepcopy(r) for r in (existing_lines or [])]
    code_index = _build_existing_code_index(out)

    for raw in vision_rows or []:
        vision = _sanitize_vision_row(raw)
        if not vision:
            audit["rows_skipped_invalid"] += 1
            continue
        audit["vision_row_count"] += 1

        vkeys = _vision_code_keys(vision["code"])
        match_idx: int | None = None
        for vk in vkeys:
            if vk in code_index:
                match_idx = code_index[vk]
                break

        if match_idx is not None:
            existing = out[match_idx]
            if _is_tesseract_row_broken(existing):
                out[match_idx] = _enrich_broken_row(existing, vision)
                audit["rows_enriched"] += 1
            else:
                audit["rows_discarded"] += 1
            continue

        new_row = _vision_row_to_legacy_row(vision)
        finalized = _finalize_gap_row(new_row, source="gemini_gap_fill")
        out.append(finalized)
        audit["rows_backfilled"] += 1
        new_idx = len(out) - 1
        for vk in _vision_code_keys(vision["code"]):
            code_index.setdefault(vk, new_idx)

    if audit["vision_row_count"] == 0:
        audit["status"] = "no_vision_rows"
    elif audit["rows_backfilled"] == 0 and audit["rows_enriched"] == 0:
        audit["status"] = "no_gaps"
    return out, audit


def parse_vision_gap_response(parsed_json: Any) -> list[dict[str, Any]]:
    if not isinstance(parsed_json, dict):
        return []
    items = parsed_json.get("line_items")
    if not isinstance(items, list):
        return []
    return [r for r in items if isinstance(r, dict)][:MAX_VISION_ROWS]


def fetch_vision_table_rows(
    page_assets: list[dict[str, Any]],
    *,
    doc_type: str = "",
    invoice_family: str = "",
    vision_fn: Callable[..., dict] = generate_vision_json,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    image_bytes_list: list[bytes] = []
    for page in page_assets or []:
        img = page.get("image_rgb")
        if img is None:
            continue
        try:
            image_bytes_list.append(_encode_page_jpeg(np.asarray(img)))
        except Exception:
            continue
    if not image_bytes_list:
        return [], {"ok": False, "status": "skipped_no_images", "error": "no_images"}

    body_parts = [str(p.get("body_text") or "")[:8000] for p in page_assets]
    user_text = (
        "Extract ALL product rows from the printed table in the image(s).\n"
        f"Document type: {doc_type or 'unknown'}\n"
        f"Invoice family: {invoice_family or 'unknown'}\n\n"
        f"OCR body reference (may be incomplete):\n{chr(10).join(body_parts)}"
    )

    result = vision_fn(
        system_instruction=GAP_FILL_VISION_SYSTEM_PROMPT,
        user_text=user_text,
        image_bytes_list=image_bytes_list,
        mime_type="image/jpeg",
        retries=1,
        timeout_s=60,
    )
    if not result.get("ok"):
        return [], {
            "ok": False,
            "status": "vision_failed",
            "error": str(result.get("error") or "vision_failed"),
        }

    rows = parse_vision_gap_response(result.get("parsed_json"))
    return rows, {"ok": True, "status": "vision_ok", "vision_row_count": len(rows), "error": ""}


def apply_vision_gap_fill(
    lines: list[dict[str, Any]],
    page_assets: list[dict[str, Any]],
    *,
    doc_type: str = "",
    invoice_family: str = "",
    vision_fn: Callable[..., dict] = generate_vision_json,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """End-to-end gap fill: Vision table pass then defensive merge."""
    if not lines:
        return lines, {"ok": False, "status": "skipped_no_lines", "error": ""}
    if not is_gap_filler_enabled():
        return lines, {"ok": False, "status": "skipped_disabled", "error": ""}
    if not page_assets:
        return lines, {"ok": False, "status": "skipped_no_images", "error": ""}

    vision_rows, fetch_audit = fetch_vision_table_rows(
        page_assets,
        doc_type=doc_type,
        invoice_family=invoice_family,
        vision_fn=vision_fn,
    )
    if not fetch_audit.get("ok"):
        return lines, {
            **fetch_audit,
            "rows_backfilled": 0,
            "rows_enriched": 0,
            "rows_discarded": 0,
            "rows_skipped_invalid": 0,
        }

    merged, merge_audit = merge_vision_gaps(lines, vision_rows)
    audit = {**fetch_audit, **merge_audit, "ok": True}
    return merged, audit
