"""Assemble canonical v2 export and optional LLM gap targets."""

from __future__ import annotations

from typing import Any, Dict, List

try:
    from pipeline.parsers import (
        FAMILY_BC_AVENIR,
        FAMILY_BC_OMNIPHARM,
        FAMILY_BC_PHARMASUD,
        FAMILY_PROFORMA,
        parse_body_lines_v2,
    )
    from pipeline.schema_v2 import InvoiceV2Payload, document_metadata_from_legacy
except ImportError:
    from parsers import (
        FAMILY_BC_AVENIR,
        FAMILY_BC_OMNIPHARM,
        FAMILY_BC_PHARMASUD,
        FAMILY_PROFORMA,
        parse_body_lines_v2,
    )
    from schema_v2 import InvoiceV2Payload, document_metadata_from_legacy


def _mirror_v2_qty_fields(rows: List[dict]) -> List[dict]:
    """Ensure every v2 row exposes quantite and qty with the same normalized value."""
    out: List[dict] = []
    for row in rows or []:
        r = dict(row)
        qty = r.get("quantite")
        if qty in (None, ""):
            qty = r.get("quantite_commande") or r.get("qty")
        if qty not in (None, ""):
            try:
                qf = float(str(qty).replace(",", ".").replace(" ", ""))
                if qf > 0:
                    q_out: int | float = int(qf) if qf == int(qf) else qf
                    r["quantite"] = q_out
                    r["qty"] = q_out
            except (TypeError, ValueError):
                r["quantite"] = qty
                r["qty"] = qty
        out.append(r)
    return out


def mirror_v2_body_snapshot(v2_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pre-gate snapshot safeguard: every line_item row gets quantite and qty mirrored.
    Safe to call repeatedly (idempotent).
    """
    if not v2_payload:
        return v2_payload
    out = dict(v2_payload)
    out["line_items"] = _mirror_v2_qty_fields(list(v2_payload.get("line_items") or []))
    return out


def build_v2_payload(document_payload: dict, body_text: str, invoice_family: str) -> dict:
    rows = parse_body_lines_v2(invoice_family, body_text or "")
    rows = _mirror_v2_qty_fields(rows)
    meta = document_metadata_from_legacy(document_payload or {})
    payload = InvoiceV2Payload(
        schema_version=2,
        invoice_family=invoice_family,
        document_metadata=meta,
        line_items=rows,
    )
    return mirror_v2_body_snapshot(payload.to_export_dict())


def collect_v2_gap_line_targets(invoice_family: str, line_items: List[dict]) -> List[dict]:
    """Rows + missing v2 fields for resolver (evidence must stay on raw_line)."""
    targets: List[dict] = []
    for row in line_items or []:
        raw = str(row.get("raw_line", "") or "")
        if not raw:
            continue
        missing: List[str] = []
        if invoice_family == FAMILY_PROFORMA:
            if not str(row.get("prix_unitaire", "")).strip():
                missing.append("prix_unitaire")
            if not str(row.get("montant", "")).strip():
                missing.append("montant")
            if not str(row.get("quantite", "")).strip():
                missing.append("quantite")
            code = str(row.get("code_pct", "") or row.get("code_article", "")).strip()
        elif invoice_family in (FAMILY_BC_AVENIR, FAMILY_BC_OMNIPHARM):
            if not str(row.get("quantite", "")).strip():
                missing.append("quantite")
            code = str(row.get("code", "")).strip()
        elif invoice_family == FAMILY_BC_PHARMASUD:
            if not str(row.get("date_peremption", "")).strip():
                missing.append("date_peremption")
            if not str(row.get("quantite_commande", "")).strip():
                missing.append("quantite_commande")
            code = str(row.get("code_pct", "")).strip()
        else:
            code = str(row.get("code", "") or row.get("code_pct", "")).strip()
        if not missing:
            continue
        if not code:
            continue
        targets.append({"code": code, "raw_line": raw, "missing_fields": missing, "invoice_family": invoice_family})
    return targets[:120]


def apply_v2_line_hints(
    line_items: List[dict],
    accepted_hints: List[dict],
    invoice_family: str,
    source_text: str,
) -> List[dict]:
    """Apply resolver hints onto v2 rows; evidence substring must appear in raw_line and full text."""

    def _has(sub: str, container: str) -> bool:
        a = str(sub or "").strip().lower()
        b = str(container or "").lower()
        return bool(a) and a in b

    def _codes_for_row(row: dict) -> List[str]:
        keys = ["code_pct", "code", "code_article"]
        return [str(row.get(k, "")).strip().upper() for k in keys if str(row.get(k, "")).strip()]

    src = str(source_text or "")
    out = [dict(r) for r in line_items]
    for hint in accepted_hints or []:
        code = str(hint.get("code", "")).strip().upper()
        field = str(hint.get("field", "")).strip()
        val = hint.get("value", "")
        evidence = str(hint.get("evidence", "") or "")
        if not code or not field:
            continue
        for row in out:
            if code not in _codes_for_row(row):
                continue
            raw_line = str(row.get("raw_line", ""))
            if evidence and not _has(evidence, raw_line):
                continue
            if str(row.get(field, "")).strip():
                continue
            row[field] = val
            break
    return out


def _normalize_merge_code(code: str) -> str:
    try:
        from ocr_line_clean import normalize_code_token
    except ImportError:
        from pipeline.ocr_line_clean import normalize_code_token
    return normalize_code_token(code)


def _legacy_code_keys(item: dict) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for k in ("code", "code_pct", "code_article"):
        raw = str(item.get(k) or "").strip()
        if not raw:
            continue
        for variant in (raw.upper(), _normalize_merge_code(raw)):
            if variant and variant not in seen:
                seen.add(variant)
                keys.append(variant)
    return keys


def merge_v2_quantities_into_product_lines(
    legacy_lines: List[dict],
    v2_payload: Dict[str, Any],
) -> List[dict]:
    """
    Copy quantite / designation from v2 body parsers into legacy all_product_lines.
    v2 BC parser often finds Qté when table/pdf mapping missed it.
    """
    try:
        from ocr_line_clean import lock_quantite, line_has_quantite
    except ImportError:
        from pipeline.ocr_line_clean import lock_quantite, line_has_quantite

    v2_items = _mirror_v2_qty_fields(list(v2_payload.get("line_items") or []))
    if not v2_items:
        return legacy_lines

    by_code: dict[str, dict] = {}
    for leg in legacy_lines:
        for c in _legacy_code_keys(leg):
            by_code[c] = leg

    for v2 in v2_items:
        codes = _legacy_code_keys(v2)
        if not codes:
            continue
        qty = v2.get("quantite") or v2.get("qty") or v2.get("quantite_commande")
        desig = v2.get("designation") or v2.get("designation_article") or ""
        v2_conf = float(v2.get("line_confidence") or 0.88)
        v2_raw = str(v2.get("raw_line") or "").strip()

        for code in codes:
            leg = by_code.get(code)
            if leg is None:
                continue
            if v2_raw:
                leg_raw = str(leg.get("_row_txt") or "").strip()
                if not leg_raw or (len(v2_raw) > len(leg_raw) and not line_has_quantite(leg)):
                    leg["_row_txt"] = v2_raw
            if qty and str(qty).strip() and not line_has_quantite(leg) and not leg.get("_quantite_locked"):
                try:
                    from services.reconciliation import parse_price

                    qf = parse_price(qty)
                    if qf is not None and qf > 0:
                        lock_quantite(
                            leg,
                            qf,
                            source="v2_parser",
                            confidence=max(
                                float((leg.get("_field_confidence") or {}).get("quantite") or 0),
                                v2_conf,
                            ),
                        )
                except (TypeError, ValueError):
                    pass
            if desig and len(str(desig).strip()) >= 3:
                if not str(leg.get("designation") or "").strip():
                    leg["designation"] = str(desig).strip()
    return legacy_lines


def merge_v2_resolver_hints(
    v2_payload: Dict[str, Any],
    legacy_accepted_hints: List[dict],
    source_text: str,
) -> Dict[str, Any]:
    """Map legacy line_item_hints (quantite, nb_crt, …) onto v2 rows where keys align."""
    family = str(v2_payload.get("invoice_family", ""))
    items = list(v2_payload.get("line_items") or [])
    mapped: List[dict] = []
    for h in legacy_accepted_hints or []:
        d = dict(h)
        f = str(d.get("field", ""))
        if f == "nb_crt":
            d["field"] = "nb_cartons"
        elif f == "u_crt":
            d["field"] = "unite_carton"
        mapped.append(d)
    items = apply_v2_line_hints(items, mapped, family, source_text)
    out = dict(v2_payload)
    out["line_items"] = _mirror_v2_qty_fields(items)
    return out
