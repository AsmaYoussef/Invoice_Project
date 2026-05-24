"""Gemini Vision pass to clean OCR line items (pen marks, noisy designations)."""

from __future__ import annotations

import json
from typing import Any

import cv2
import numpy as np

from ai.gemini_client import generate_vision_json, is_vision_enabled
from ocr_line_clean import (
    sanitize_pharma_designation,
    sanitize_product_code,
)

MAX_CANDIDATES = 120
MAX_IMAGE_PX = 2048

GEMINI_LINE_CLEAN_SYSTEM_PROMPT = """You are a pharmaceutical invoice line-item cleaning engine.

You receive:
1) One or more scanned invoice page images.
2) Raw OCR body text from those pages.
3) A JSON list of candidate product rows extracted by Tesseract (may contain pen noise).

Your job: return cleaned rows in strict JSON only.

RULES — IGNORE HANDWRITING AND INK ARTIFACTS:
- Completely ignore handwritten pen marks, checkmarks, circles, vertical/horizontal pen lines, stamps, and header notes (e.g. "BC 23-1394").
- Use only printed table cell content visible in the image and supported by OCR text.

RULES — DESIGNATION (designation field):
- ONLY the official drug commercial name, dosage, and pharmaceutical form.
- MUST start with an uppercase letter A–Z.
- MUST end with a digit OR the word COMP (e.g. "B/30 COMP", "B/14COMP").
- Strip ALL leading/trailing noise: stray numbers from pen strokes, punctuation (>. , " ¢ ~), random prefixes like "7 ", "ae ", "20 gS ".
- NEVER include the Qté column quantity inside designation. Quantities like "24", "72" belong ONLY in quantite.
- Do NOT absorb dosage numbers that are part of the product name (e.g. "10 MG", "200 MG") — those stay in designation.

RULES — QUANTITE:
- Integer from the Qté / quantity column only (NOT dosage: 10 MG, 200 MG stay in designation).
- Avenir / MEDIS bon de commande: 6-digit MP code then Qté in the next column (e.g. "301475 30 X MEDISIUM...").
- If unclear from image, keep the candidate value if plausible (1–8000); otherwise empty string.

RULES — CODE:
- Numeric MP code: exactly 6 digits when possible (e.g. 302970).
- PF article code: PF followed by alphanumeric (e.g. PF003900003).
- No extra characters or pen strokes in codes.

OUTPUT JSON schema:
{
  "lines": [
    {
      "i": <same index as candidate>,
      "code": "<primary code>",
      "code_pct": "<6-digit MP or empty>",
      "code_article": "<PF code or empty>",
      "quantite": "<integer string or empty>",
      "designation": "<cleaned designation>",
      "clean_confidence": <0.0-1.0>
    }
  ]
}

Return one output row per input candidate index. If a row is not a real product line, still return it with clean_confidence <= 0.3.
"""


def _resize_image_rgb(img_rgb: np.ndarray, max_px: int = MAX_IMAGE_PX) -> np.ndarray:
    h, w = img_rgb.shape[:2]
    if max(h, w) <= max_px:
        return img_rgb
    scale = max_px / float(max(h, w))
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(img_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _encode_page_jpeg(img_rgb: np.ndarray) -> bytes:
    resized = _resize_image_rgb(img_rgb)
    bgr = cv2.cvtColor(resized, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise ValueError("Failed to encode page image")
    return buf.tobytes()


def _build_candidates_payload(
    lines: list[dict[str, Any]],
    *,
    doc_type: str = "",
    invoice_family: str = "",
) -> dict[str, Any]:
    candidates = []
    for i, item in enumerate(lines[:MAX_CANDIDATES]):
        code = str(
            item.get("code")
            or item.get("code_pct")
            or item.get("code_article")
            or ""
        ).strip()
        candidates.append(
            {
                "i": i,
                "code": code,
                "code_pct": str(item.get("code_pct") or "").strip(),
                "code_article": str(item.get("code_article") or "").strip(),
                "quantite": str(item.get("quantite") if item.get("quantite") not in (None, "") else ""),
                "designation": str(item.get("designation") or "").strip(),
            }
        )
    return {
        "document_type": doc_type or "",
        "invoice_family": invoice_family or "",
        "candidates": candidates,
    }


def _sanitize_line_fields(row: dict[str, Any]) -> dict[str, Any]:
    qty = str(row.get("quantite") or "").strip()
    desig = sanitize_pharma_designation(str(row.get("designation") or ""), quantite=qty)
    code = sanitize_product_code(str(row.get("code") or ""))
    code_pct = sanitize_product_code(str(row.get("code_pct") or ""))
    code_article = sanitize_product_code(str(row.get("code_article") or ""))
    if code_article and code_article.startswith("PF"):
        pass
    elif code.startswith("PF"):
        code_article = code_article or code
    elif code and code.isdigit():
        code_pct = code_pct or code
    out = {
        "code": code or code_pct or code_article,
        "code_pct": code_pct if code_pct and code_pct.isdigit() else "",
        "code_article": code_article if code_article.startswith("PF") else "",
        "quantite": qty,
        "designation": desig,
        "clean_confidence": float(row.get("clean_confidence") or 0.5),
    }
    if out["code_pct"] and not out["code"]:
        out["code"] = out["code_pct"]
    elif out["code_article"] and not out["code"]:
        out["code"] = out["code_article"]
    return out


def _merge_cleaned_into_lines(
    original: list[dict[str, Any]],
    cleaned_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not cleaned_rows:
        return original

    by_index: dict[int, dict[str, Any]] = {}
    by_code: dict[str, dict[str, Any]] = {}
    for row in cleaned_rows:
        try:
            idx = int(row.get("i", -1))
        except (TypeError, ValueError):
            idx = -1
        sanitized = _sanitize_line_fields(row)
        if idx >= 0:
            by_index[idx] = sanitized
        code_key = (sanitized.get("code") or "").strip().upper()
        if code_key:
            by_code[code_key] = sanitized

    merged: list[dict[str, Any]] = []
    for i, item in enumerate(original):
        out = dict(item)
        clean = by_index.get(i)
        if not clean:
            code_key = str(
                out.get("code") or out.get("code_pct") or out.get("code_article") or ""
            ).strip().upper()
            clean = by_code.get(code_key)
        if not clean:
            merged.append(out)
            continue

        conf = float(clean.get("clean_confidence") or 0.0)
        prev_conf = float(
            (out.get("_field_confidence") or {}).get("designation") or 0.0
        )
        if conf >= prev_conf or conf >= 0.5:
            for field in ("code", "code_pct", "code_article", "quantite", "designation"):
                val = clean.get(field)
                if val not in ("", None):
                    out[field] = val
            src = dict(out.get("_field_source") or {})
            fconf = dict(out.get("_field_confidence") or {})
            src["designation"] = "gemini_vision"
            fconf["designation"] = conf
            if clean.get("code"):
                src["code"] = "gemini_vision"
                fconf["code"] = conf
            if clean.get("quantite"):
                src["quantite"] = "gemini_vision"
                fconf["quantite"] = conf
            out["_field_source"] = src
            out["_field_confidence"] = fconf
            out["line_confidence"] = min(
                float(out.get("line_confidence") or 1.0),
                conf,
            ) if out.get("line_confidence") is not None else conf
        merged.append(out)
    return merged


def apply_gemini_line_cleanup(
    lines: list[dict[str, Any]],
    page_assets: list[dict[str, Any]],
    *,
    doc_type: str = "",
    invoice_family: str = "",
) -> list[dict[str, Any]]:
    """
    Vision + OCR text cleanup. No-op if disabled, no API key, or no lines.
    page_assets: [{"image_rgb": ndarray, "body_text": str}, ...]
    """
    if not lines or not is_vision_enabled():
        return lines
    if not page_assets:
        return lines

    payload = _build_candidates_payload(
        lines, doc_type=doc_type, invoice_family=invoice_family
    )
    if not payload.get("candidates"):
        return lines

    image_bytes_list: list[bytes] = []
    for page in page_assets:
        img = page.get("image_rgb")
        if img is None:
            continue
        try:
            image_bytes_list.append(_encode_page_jpeg(np.asarray(img)))
        except Exception:
            continue
    if not image_bytes_list:
        return lines

    body_parts = [str(p.get("body_text") or "")[:8000] for p in page_assets]
    user_text = (
        "Clean the candidate product rows using the page images and OCR text.\n\n"
        f"OCR body text (per page):\n{chr(10).join(body_parts)}\n\n"
        f"Candidates JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    result = generate_vision_json(
        system_instruction=GEMINI_LINE_CLEAN_SYSTEM_PROMPT,
        user_text=user_text,
        image_bytes_list=image_bytes_list,
        mime_type="image/jpeg",
        retries=1,
        timeout_s=60,
    )
    if not result.get("ok"):
        return lines

    parsed = result.get("parsed_json") or {}
    cleaned_rows = parsed.get("lines") if isinstance(parsed, dict) else None
    if not isinstance(cleaned_rows, list):
        return lines

    return _merge_cleaned_into_lines(lines, cleaned_rows)
