"""Gemini Vision structural audit: realign columns, header metadata, and line math."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import cv2
import numpy as np

try:
    from pipeline.ai.gemini_client import generate_vision_json, is_vision_enabled
    from pipeline.ocr_line_clean import (
        lock_quantite,
        quantite_is_locked,
        sanitize_pharma_designation,
        sanitize_product_code,
    )
    from pipeline.parsers import FAMILY_BC_AVENIR, FAMILY_BC_OMNIPHARM, FAMILY_PROFORMA
except ImportError:
    from ai.gemini_client import generate_vision_json, is_vision_enabled
    from ocr_line_clean import (
        lock_quantite,
        quantite_is_locked,
        sanitize_pharma_designation,
        sanitize_product_code,
    )
    from parsers import FAMILY_BC_AVENIR, FAMILY_BC_OMNIPHARM, FAMILY_PROFORMA

MAX_CANDIDATES = 120
MAX_IMAGE_PX = 2048
MATH_TOLERANCE = 0.02
GATE_CONFIDENCE_THRESHOLD = 0.5

STRUCTURAL_AUDIT_SYSTEM_PROMPT = """You are an expert Structural Data Auditing Agent. You are provided with a locally parsed JSON dictionary object array containing invoice line items, alongside the raw visual page image of that document. Your goal is to cross-examine the JSON keys against the spatial reality of the columns visible in the image to correct any layout or alignment errors.

Enforce these correction rules:
1. Header Metadata Alignment: Locate the explicit supplier identity in the image. Ensure 'fournisseur_nom' resolves to the correct enterprise name (e.g., 'Laboratoires Médis', 'Omnipharm', 'Avicenne') rather than capturing layout noise or document numbers.
2. Index Anchoring: Scan the entire document page area for line items. Start extraction from the first real product entry row, even if it is preceded by structural placeholders or categories like 'DIVERS'.
3. Column Isolation & Math Balance: Ensure that data fields do not bleed across boundaries. Verify the balance equation for every row: Quantité × Prix Unitaire = Montant. If the formula fails due to space-collapses or text shifting, use the visual column layout to realign the values into their true keys.
4. Active Molecule Preservation: Never allow active drug strength indicators (such as '200000 UI', '10 MG', '40 MG') to overwrite or populate the stock 'quantite' field. Isolate the numeric values from the document's true quantity column.
5. Structural Consistency: Retain valid 'code_pct' and 'code_article' values. Never let descriptions bleed into numerical fields.

Return strict JSON only with this exact schema:
{
  "document_metadata": { "fournisseur_nom": "", "type": "", "numero": "", "date": "" },
  "line_items": [
    {
      "code_pct": "",
      "code_article": "",
      "designation_article": "",
      "quantite": 0,
      "prix_unitaire": 0,
      "montant": 0
    }
  ]
}

Use numbers (not strings) for quantite, prix_unitaire, montant when known; use 0 when absent.
Return one line_items row per input candidate index in the same order.
"""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def is_structural_gate_enabled() -> bool:
    if not is_vision_enabled():
        return False
    return _env_bool("GEMINI_STRUCTURAL_GATE_ENABLED", default=True)


def _parse_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        v = float(val)
        return v if v > 0 else None
    text = str(val).strip().replace(" ", "").replace(",", ".")
    if not text or text in ("—", "-", "ND"):
        return None
    parts = text.split(".")
    if len(parts) > 2:
        text = "".join(parts[:-1]) + "." + parts[-1]
    try:
        v = float(text)
        if v <= 0 or v > 999_999_999:
            return None
        return v
    except ValueError:
        return None


def _is_supplier_name_plausible(name: str) -> bool:
    s = str(name or "").strip()
    if len(s) < 3:
        return False
    low = s.lower()
    if re.search(r"https?://|www\.|stat\s+ventes|statistiques", low):
        return False
    if re.search(r"proforma\s*n[°o]|mdn-pre|mdn-prf|bon\s+de\s+commande\s+n", low, re.I):
        return False
    if re.search(r"^\s*(page|cer)\s", low):
        return False
    letters = sum(1 for c in s if c.isalpha())
    if letters < max(3, len(s) * 0.25):
        return False
    return True


def _qty_matches_dosage_in_designation(qty: float, designation: str) -> bool:
    des = str(designation or "").upper()
    if not des or qty <= 0:
        return False
    q_int = int(qty) if qty == int(qty) else None
    q_str = str(int(qty)) if q_int is not None else str(qty)
    if re.search(rf"\b{re.escape(q_str)}\s*(?:UI|IU|MG|MCG|G|ML)\b", des):
        return True
    if qty >= 1000 and re.search(rf"\b{re.escape(q_str)}\b", des):
        strength = re.search(
            r"\b(\d{3,7})\s*(?:UI|IU|MG|MCG)\b",
            des,
        )
        if strength and abs(float(strength.group(1)) - qty) < 1:
            return True
    return False


def _is_qty_plausible_local(
    qty: float | None,
    designation: str = "",
    *,
    doc_type: str = "",
) -> bool:
    if qty is None or qty <= 0 or qty > 500_000:
        return False
    if 1900 <= qty <= 2100:
        return False
    soft_cap = 10_000.0 if "proforma" in str(doc_type or "").lower() else 6_000.0
    if qty > soft_cap:
        return False
    if _qty_matches_dosage_in_designation(qty, designation):
        return False
    d = str(designation or "").lower()
    if d and re.search(r"(total|montant|ttc|ht)\b", d):
        return False
    return True


def _math_balance_ok(qty: float, pu: float, montant: float) -> bool:
    if qty <= 0 or pu <= 0 or montant <= 0:
        return True
    expected = qty * pu
    denom = max(montant, 1.0)
    return abs(expected - montant) / denom < MATH_TOLERANCE


def _resize_image_rgb(img_rgb: np.ndarray, max_px: int = MAX_IMAGE_PX) -> np.ndarray:
    h, w = img_rgb.shape[:2]
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


def lines_to_unified_payload(
    lines: list[dict[str, Any]],
    document_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = {
        "fournisseur_nom": str((document_metadata or {}).get("fournisseur_nom") or ""),
        "type": str((document_metadata or {}).get("type") or ""),
        "numero": str((document_metadata or {}).get("numero") or ""),
        "date": str((document_metadata or {}).get("date") or ""),
    }
    unified_items: list[dict[str, Any]] = []
    for i, item in enumerate(lines[:MAX_CANDIDATES]):
        code = str(
            item.get("code")
            or item.get("code_pct")
            or item.get("code_article")
            or ""
        ).strip()
        code_pct = str(item.get("code_pct") or "").strip()
        code_article = str(item.get("code_article") or "").strip()
        if not code_pct and code and code.isdigit() and len(code) >= 5:
            code_pct = code
        if not code_article and code.upper().startswith("PF"):
            code_article = code
        desig = str(
            item.get("designation_article")
            or item.get("designation")
            or ""
        ).strip()
        qty = _parse_float(item.get("quantite")) or 0.0
        pu = _parse_float(item.get("prix_unitaire")) or 0.0
        mt = _parse_float(item.get("montant")) or 0.0
        unified_items.append(
            {
                "i": i,
                "code_pct": code_pct,
                "code_article": code_article,
                "designation_article": desig,
                "quantite": qty,
                "prix_unitaire": pu,
                "montant": mt,
            }
        )
    return {"document_metadata": meta, "line_items": unified_items}


def _sanitize_gate_row(row: dict[str, Any], *, doc_type: str = "") -> dict[str, Any]:
    desig = sanitize_pharma_designation(
        str(row.get("designation_article") or ""),
        quantite=str(row.get("quantite") or ""),
    )
    code_pct = sanitize_product_code(str(row.get("code_pct") or ""))
    code_article = sanitize_product_code(str(row.get("code_article") or ""))
    if code_article and not code_article.upper().startswith("PF"):
        if code_article.isdigit():
            code_pct = code_pct or code_article
            code_article = ""
    qty = _parse_float(row.get("quantite"))
    pu = _parse_float(row.get("prix_unitaire"))
    mt = _parse_float(row.get("montant"))
    if qty is not None and not _is_qty_plausible_local(qty, desig, doc_type=doc_type):
        qty = None
    if pu and mt and qty and not _math_balance_ok(qty, pu, mt):
        pu = None
        mt = None
    return {
        "code_pct": code_pct if code_pct and (code_pct.isdigit() or len(code_pct) >= 5) else "",
        "code_article": code_article if code_article.upper().startswith("PF") else "",
        "designation_article": desig,
        "quantite": qty,
        "prix_unitaire": pu,
        "montant": mt,
        "gate_confidence": float(row.get("gate_confidence") or 0.85),
    }


def validate_structural_response(
    parsed: dict[str, Any] | None,
    *,
    doc_type: str = "",
) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    meta_in = parsed.get("document_metadata") or {}
    meta_out = {
        "fournisseur_nom": str(meta_in.get("fournisseur_nom") or "").strip(),
        "type": str(meta_in.get("type") or "").strip(),
        "numero": str(meta_in.get("numero") or "").strip(),
        "date": str(meta_in.get("date") or "").strip(),
    }
    if meta_out["fournisseur_nom"] and not _is_supplier_name_plausible(
        meta_out["fournisseur_nom"]
    ):
        meta_out["fournisseur_nom"] = ""

    items_out: list[dict[str, Any]] = []
    raw_items = parsed.get("line_items")
    if not isinstance(raw_items, list):
        return None
    for row in raw_items[:MAX_CANDIDATES]:
        if not isinstance(row, dict):
            continue
        sanitized = _sanitize_gate_row(row, doc_type=doc_type)
        items_out.append(sanitized)
    return {"document_metadata": meta_out, "line_items": items_out}


def _merge_gate_into_lines(
    original: list[dict[str, Any]],
    snapshot: dict[str, Any],
    *,
    doc_type: str = "",
) -> tuple[list[dict[str, Any]], int]:
    gate_items = list(snapshot.get("line_items") or [])
    if not gate_items:
        return original, 0

    corrected = 0
    merged: list[dict[str, Any]] = []
    for i, item in enumerate(original):
        out = dict(item)
        gate_row = gate_items[i] if i < len(gate_items) else None
        if not gate_row:
            merged.append(out)
            continue

        conf = float(gate_row.get("gate_confidence") or 0.85)
        src = dict(out.get("_field_source") or {})
        fconf = dict(out.get("_field_confidence") or {})

        desig = gate_row.get("designation_article") or ""
        if desig:
            out["designation"] = desig
            src["designation"] = "gemini_structural_gate"
            fconf["designation"] = conf

        code_pct = gate_row.get("code_pct") or ""
        code_article = gate_row.get("code_article") or ""
        if code_pct:
            out["code_pct"] = code_pct
            out["code"] = out.get("code") or code_pct
            src["code_pct"] = "gemini_structural_gate"
            fconf["code_pct"] = conf
        if code_article:
            out["code_article"] = code_article
            if not out.get("code"):
                out["code"] = code_article
            src["code_article"] = "gemini_structural_gate"
            fconf["code_article"] = conf

        qty = gate_row.get("quantite")
        if qty is not None and not out.get("_quantite_locked"):
            try:
                qf = float(qty)
            except (TypeError, ValueError):
                qf = 0.0
            if qf > 0 and _is_qty_plausible_local(qf, desig, doc_type=doc_type):
                out = lock_quantite(
                    out,
                    qty,
                    source="gemini_structural_gate",
                    confidence=conf,
                )
                corrected += 1

        pu = gate_row.get("prix_unitaire")
        if pu is not None:
            out["prix_unitaire"] = pu
            src["prix_unitaire"] = "gemini_structural_gate"
            fconf["prix_unitaire"] = conf
        mt = gate_row.get("montant")
        if mt is not None:
            out["montant"] = mt
            src["montant"] = "gemini_structural_gate"
            fconf["montant"] = conf

        out["_field_source"] = src
        out["_field_confidence"] = fconf
        prev_lc = out.get("line_confidence")
        try:
            out["line_confidence"] = max(float(prev_lc or 0), conf)
        except (TypeError, ValueError):
            out["line_confidence"] = conf
        merged.append(out)
    return merged, corrected


def snapshot_to_v2_line_items(
    snapshot: dict[str, Any],
    original_lines: list[dict[str, Any]],
    *,
    invoice_family: str = "",
) -> list[dict[str, Any]]:
    """Convert validated gate snapshot into v2 export line_items."""
    gate_items = list(snapshot.get("line_items") or [])
    out: list[dict[str, Any]] = []
    is_proforma = invoice_family == FAMILY_PROFORMA
    is_bc = invoice_family in (FAMILY_BC_AVENIR, FAMILY_BC_OMNIPHARM)

    for i, gate_row in enumerate(gate_items):
        orig = original_lines[i] if i < len(original_lines) else {}
        raw_line = str(orig.get("raw_line") or orig.get("_row_txt") or "").strip()
        desig = str(gate_row.get("designation_article") or "").strip()
        code_pct = str(gate_row.get("code_pct") or "").strip()
        code_article = str(gate_row.get("code_article") or "").strip()
        qty = gate_row.get("quantite")
        qty_str = ""
        if qty is not None:
            try:
                qf = float(qty)
                qty_str = str(int(qf)) if qf == int(qf) else str(qf)
            except (TypeError, ValueError):
                qty_str = str(qty)

        if is_proforma:
            row = {
                "code_pct": code_pct,
                "code_article": code_article,
                "designation_article": desig,
                "quantite": qty_str,
                "qty": qty_str,
                "prix_unitaire": _format_money(gate_row.get("prix_unitaire")),
                "montant": _format_money(gate_row.get("montant")),
                "line_confidence": float(gate_row.get("gate_confidence") or 0.88),
                "raw_line": raw_line,
            }
        elif is_bc:
            primary = code_pct or code_article or ""
            row = {
                "code": primary,
                "quantite": qty_str,
                "qty": qty_str,
                "designation": desig,
                "line_confidence": float(gate_row.get("gate_confidence") or 0.88),
                "raw_line": raw_line,
            }
        else:
            primary = code_pct or code_article or str(orig.get("code") or "")
            row = {
                "code": primary,
                "quantite": qty_str,
                "qty": qty_str,
                "designation": desig,
                "line_confidence": float(gate_row.get("gate_confidence") or 0.35),
                "raw_line": raw_line,
            }
            if code_pct:
                row["code_pct"] = code_pct
            if code_article:
                row["code_article"] = code_article
        out.append(row)
    return out


def _format_money(val: Any) -> str:
    f = _parse_float(val)
    if f is None:
        return ""
    if f == int(f):
        return str(int(f))
    return f"{f:.5f}".rstrip("0").rstrip(".")


def apply_structural_snapshot_to_v2_payload(
    v2_payload: dict[str, Any],
    snapshot: dict[str, Any] | None,
    original_lines: list[dict[str, Any]],
) -> dict[str, Any]:
    if not snapshot or not snapshot.get("line_items"):
        return v2_payload
    out = dict(v2_payload)
    gate_meta = snapshot.get("document_metadata") or {}
    existing_meta = dict(out.get("document_metadata") or {})
    for key in ("fournisseur_nom", "type", "numero", "date"):
        val = str(gate_meta.get(key) or "").strip()
        if val:
            existing_meta[key] = val
    out["document_metadata"] = existing_meta
    family = str(out.get("invoice_family") or "")
    parser_items = list(v2_payload.get("line_items") or [])
    gate_items = snapshot_to_v2_line_items(
        snapshot,
        original_lines,
        invoice_family=family,
    )
    merged_items: list[dict[str, Any]] = []
    for i, gate_row in enumerate(gate_items):
        row = dict(gate_row)
        orig = original_lines[i] if i < len(original_lines) else {}
        parser_row = parser_items[i] if i < len(parser_items) else {}
        gate_qty = row.get("quantite")
        parser_qty = parser_row.get("quantite") or parser_row.get("qty")
        orig_qty = orig.get("quantite") or orig.get("qty")
        try:
            gate_qf = float(str(gate_qty).replace(",", ".")) if gate_qty not in (None, "") else 0.0
        except (TypeError, ValueError):
            gate_qf = 0.0
        if gate_qf <= 0:
            keep = parser_qty if parser_qty not in (None, "") else orig_qty
            if keep not in (None, ""):
                try:
                    kf = float(str(keep).replace(",", "."))
                    if kf > 0:
                        q_out: int | float = int(kf) if kf == int(kf) else kf
                        row["quantite"] = q_out
                        row["qty"] = q_out
                except (TypeError, ValueError):
                    row["quantite"] = keep
                    row["qty"] = keep
        elif row.get("quantite") not in (None, ""):
            row["qty"] = row.get("qty", row.get("quantite"))
        merged_items.append(row)
    out["line_items"] = merged_items
    return out


def apply_structural_realignment_gate(
    lines: list[dict[str, Any]],
    page_assets: list[dict[str, Any]],
    *,
    document_metadata: dict[str, Any] | None = None,
    doc_type: str = "",
    invoice_family: str = "",
    header_text: str = "",
    body_text: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    """
    Vision structural audit. Returns (merged_lines, audit_dict, unified_snapshot).
    page_assets: [{"image_rgb": ndarray, "body_text": str}, ...]
    """
    audit: dict[str, Any] = {
        "ok": False,
        "status": "skipped",
        "rows_corrected": 0,
        "metadata_corrected": False,
        "error": "",
    }
    if not lines:
        audit["status"] = "skipped_no_lines"
        return lines, audit, None
    if not is_structural_gate_enabled():
        audit["status"] = "skipped_disabled"
        return lines, audit, None
    if not page_assets:
        audit["status"] = "skipped_no_images"
        return lines, audit, None

    candidate = lines_to_unified_payload(lines, document_metadata)
    if not candidate.get("line_items"):
        audit["status"] = "skipped_no_candidates"
        return lines, audit, None

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
        audit["status"] = "skipped_encode_failed"
        return lines, audit, None

    header_snip = str(header_text or "")[:4000]
    body_snip = str(body_text or "")[:8000]
    if not body_snip:
        body_parts = [str(p.get("body_text") or "")[:8000] for p in page_assets]
        body_snip = "\n".join(body_parts)[:8000]

    user_text = (
        "Cross-examine the candidate JSON against the invoice page images.\n\n"
        f"Document type: {doc_type or ''}\n"
        f"Invoice family: {invoice_family or ''}\n\n"
        f"OCR header text:\n{header_snip}\n\n"
        f"OCR body text:\n{body_snip}\n\n"
        f"Candidate JSON:\n{json.dumps(candidate, ensure_ascii=False)}"
    )

    result = generate_vision_json(
        system_instruction=STRUCTURAL_AUDIT_SYSTEM_PROMPT,
        user_text=user_text,
        image_bytes_list=image_bytes_list,
        mime_type="image/jpeg",
        retries=1,
        timeout_s=90,
    )

    if not result.get("ok"):
        audit["status"] = "vision_failed"
        audit["error"] = str(result.get("error") or "json_parse_failed")
        return lines, audit, None

    snapshot = validate_structural_response(
        result.get("parsed_json"),
        doc_type=doc_type,
    )
    if not snapshot:
        audit["status"] = "validation_failed"
        audit["error"] = "invalid_gate_response"
        return lines, audit, None

    merged, rows_corrected = _merge_gate_into_lines(
        lines,
        snapshot,
        doc_type=doc_type,
    )
    meta = snapshot.get("document_metadata") or {}
    metadata_corrected = bool(meta.get("fournisseur_nom"))

    audit["ok"] = True
    audit["status"] = "applied"
    audit["rows_corrected"] = rows_corrected
    audit["metadata_corrected"] = metadata_corrected
    audit["line_count"] = len(snapshot.get("line_items") or [])
    audit["fournisseur_nom"] = meta.get("fournisseur_nom", "")

    return merged, audit, snapshot


try:
    from pipeline.ocr_line_clean import recover_lines_quantites_from_raw
except ImportError:
    from ocr_line_clean import recover_lines_quantites_from_raw  # type: ignore
