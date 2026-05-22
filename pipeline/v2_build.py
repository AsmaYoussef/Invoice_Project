"""Assemble canonical v2 export and optional LLM gap targets."""

from __future__ import annotations

from typing import Any, Dict, List

from parsers import FAMILY_BC_AVENIR, FAMILY_BC_OMNIPHARM, FAMILY_BC_PHARMASUD, FAMILY_PROFORMA, parse_body_lines_v2
from schema_v2 import InvoiceV2Payload, document_metadata_from_legacy


def build_v2_payload(document_payload: dict, body_text: str, invoice_family: str) -> dict:
    rows = parse_body_lines_v2(invoice_family, body_text or "")
    meta = document_metadata_from_legacy(document_payload or {})
    payload = InvoiceV2Payload(
        schema_version=2,
        invoice_family=invoice_family,
        document_metadata=meta,
        line_items=rows,
    )
    return payload.to_export_dict()


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
        val = str(hint.get("value", "")).strip()
        evidence = str(hint.get("evidence", "")).strip()
        if not code or not field or not val:
            continue
        if not _has(evidence, src):
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


def merge_v2_quantities_into_product_lines(
    legacy_lines: List[dict],
    v2_payload: Dict[str, Any],
) -> List[dict]:
    """
    Copy quantite / designation from v2 body parsers into legacy all_product_lines.
    v2 BC parser often finds Qté when table/pdf mapping missed it.
    """
    v2_items = list(v2_payload.get("line_items") or [])
    if not v2_items:
        return legacy_lines

    def _codes(item: dict) -> list[str]:
        out = []
        for k in ("code", "code_pct", "code_article"):
            c = str(item.get(k) or "").strip().upper()
            if c:
                out.append(c)
        return out

    by_code: dict[str, dict] = {}
    for leg in legacy_lines:
        for c in _codes(leg):
            by_code[c] = leg

    for v2 in v2_items:
        codes = _codes(v2)
        if not codes:
            continue
        qty = v2.get("quantite") or v2.get("quantite_commande")
        desig = v2.get("designation") or v2.get("designation_article") or ""
        v2_conf = float(v2.get("line_confidence") or 0.88)

        for code in codes:
            leg = by_code.get(code)
            if leg is None:
                continue
            if qty and str(qty).strip() and not str(leg.get("quantite") or "").strip():
                try:
                    from services.reconciliation import parse_price

                    qf = parse_price(qty)
                    if qf is not None and qf > 0:
                        leg["quantite"] = int(qf) if qf == int(qf) else qf
                        src = dict(leg.get("_field_source") or {})
                        fconf = dict(leg.get("_field_confidence") or {})
                        src["quantite"] = "v2_parser"
                        fconf["quantite"] = max(float(fconf.get("quantite") or 0), v2_conf)
                        leg["_field_source"] = src
                        leg["_field_confidence"] = fconf
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
    out["line_items"] = items
    return out
