"""Invoice history listing for accountant dashboard."""
from __future__ import annotations

import json
from typing import Any

from services.db import get_db_connection

LEGACY_SAISI_PAR = "OCR-API"


def _count_line_statuses(product_lines: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "VALID": 0,
        "PRICE_MISMATCH": 0,
        "LOW_CONFIDENCE": 0,
        "UNKNOWN_PRODUCT": 0,
        "UNCHECKED": 0,
    }
    for line in product_lines:
        status = str(line.get("validation_status") or "UNCHECKED").upper()
        if status in counts:
            counts[status] += 1
        else:
            counts["UNCHECKED"] += 1
    return counts


def derive_invoice_status(counts: dict[str, int], open_alerts: int) -> str:
    if open_alerts > 0 or counts.get("PRICE_MISMATCH", 0) > 0:
        return "DISCREPANCY"
    if counts.get("LOW_CONFIDENCE", 0) > 0 or counts.get("UNKNOWN_PRODUCT", 0) > 0:
        return "NEEDS_REVIEW"
    return "VALIDATED"


def list_invoice_history(
    username: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                f.IDFacture,
                f.LibFacture,
                f.DateFacture,
                f.Client,
                f.SaisiPar,
                f.SaisiLe,
                f.TotalHT,
                m.avg_confidence,
                m.raw_json,
                m.created_at AS meta_created,
                (
                    SELECT COUNT(*)
                    FROM reconciliation_alerts r
                    WHERE r.IDFacture = f.IDFacture AND r.is_resolved = 0
                ) AS open_alerts
            FROM facture f
            LEFT JOIN extraction_metadata m ON m.IDFacture = f.IDFacture
            WHERE f.SaisiPar IN (%s, %s)
            ORDER BY COALESCE(f.SaisiLe, m.created_at, f.IDFacture) DESC, f.IDFacture DESC
            LIMIT %s OFFSET %s
            """,
            (username, LEGACY_SAISI_PAR, limit, offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS cnt FROM facture
            WHERE SaisiPar IN (%s, %s)
            """,
            (username, LEGACY_SAISI_PAR),
        )
        total = int((cursor.fetchone() or {}).get("cnt") or 0)

        invoices = []
        for row in rows:
            invoices.append(_row_to_invoice(row))

        return {"invoices": invoices, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def _row_to_invoice(row: dict[str, Any]) -> dict[str, Any]:
    raw_json = row.get("raw_json") or "{}"
    try:
        payload = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except json.JSONDecodeError:
        payload = {}

    general = payload.get("general_info") or {}
    product_lines = payload.get("product_lines") or []
    counts = _count_line_statuses(product_lines)
    open_alerts = int(row.get("open_alerts") or 0)
    status = derive_invoice_status(counts, open_alerts)

    avg_conf = float(row.get("avg_confidence") or 0)
    review_score_pct = round(avg_conf * 100) if avg_conf <= 1 else round(avg_conf)

    date_facture = row.get("DateFacture")
    saisi_le = row.get("SaisiLe")
    meta_created = row.get("meta_created")

    return {
        "id_facture": row["IDFacture"],
        "lib_facture": row.get("LibFacture") or "",
        "invoice_number": general.get("invoice_number") or row.get("LibFacture") or "",
        "supplier": row.get("Client") or general.get("supplier_name") or general.get("erp_supplier_name") or "",
        "invoice_date": date_facture.isoformat() if hasattr(date_facture, "isoformat") else str(date_facture or ""),
        "saved_at": (
            saisi_le.isoformat()
            if hasattr(saisi_le, "isoformat")
            else (meta_created.isoformat() if hasattr(meta_created, "isoformat") else str(saisi_le or meta_created or ""))
        ),
        "validation_status": status,
        "review_score_pct": review_score_pct,
        "line_count": len(product_lines) or counts["VALID"] + counts["PRICE_MISMATCH"] + counts["LOW_CONFIDENCE"] + counts["UNKNOWN_PRODUCT"],
        "valid_count": counts["VALID"],
        "price_mismatch_count": counts["PRICE_MISMATCH"],
        "low_confidence_count": counts["LOW_CONFIDENCE"],
        "unknown_count": counts["UNKNOWN_PRODUCT"],
        "open_alerts": open_alerts,
        "total_ht": float(row.get("TotalHT") or 0),
        "uploaded_by": row.get("SaisiPar") or "",
    }
