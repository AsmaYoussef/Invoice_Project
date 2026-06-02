"""Post reconciled invoice payloads to ERP tables (facture, lignefac, metadata)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from services.admin_alerts import dispatch_discrepancy_alert
from services.admin_config import evaluate_price_mismatch_alert
from services.admin_logger import log_error, log_info, log_warn
from services.accountant_notifications import create_notification
from services.invoice_submissions import lib_facture_from_number


def parse_invoice_date(raw: str):
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def post_invoice_to_erp(
    cursor,
    payload: dict[str, Any],
    *,
    saisi_par: str,
    approved_by: str | None = None,
    notify_accountant: str | None = None,
) -> dict[str, Any]:
    """Insert facture + lignefac + extraction_metadata; return ids."""
    info = payload.get("general_info") or {}
    lines = payload.get("product_lines") or []
    financial = payload.get("financial_totals") or {}

    lib_facture = lib_facture_from_number(info.get("invoice_number"))

    cursor.execute(
        "SELECT IDFacture FROM facture WHERE LibFacture = %s LIMIT 1",
        (lib_facture,),
    )
    existing = cursor.fetchone()
    if existing:
        raise ValueError(
            f"Invoice '{lib_facture}' already exists in ERP (ID {existing['IDFacture']})."
        )

    date_facture = parse_invoice_date(info.get("invoice_date", ""))
    supplier = info.get("erp_supplier_name") or info.get("supplier_name") or ""

    total_ht = 0.0
    for line in lines:
        try:
            qty = float(str(line.get("quantite", "0")).replace(",", ".").replace(" ", ""))
        except ValueError:
            qty = 0.0
        price = float(line.get("price_unit") or 0)
        total_ht += qty * price
    if financial.get("total_ht"):
        total_ht = float(financial["total_ht"])

    cursor.execute(
        """
        INSERT INTO facture (
            LibFacture, DateFacture, Client, TotalHT, TotalTTC, TotalTVA,
            MF, Adresse, SaisiPar, SaisiLe, Observations, CoordonneesBancaires
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), %s, %s)
        """,
        (
            lib_facture,
            date_facture,
            supplier[:150],
            total_ht,
            total_ht * 1.19,
            total_ht * 0.19,
            (info.get("erp_supplier_mf") or info.get("supplier_mf") or "")[:20],
            (info.get("address") or "")[:150],
            saisi_par[:50],
            f"Imported from OCR document {info.get('invoice_number', '')}",
            "",
        ),
    )
    id_facture = cursor.lastrowid

    ordre = 0
    for line in lines:
        ordre += 1
        code = str(line.get("code") or line.get("code_article") or line.get("code_pct") or "N/A")
        lib = str(line.get("designation") or line.get("erp_name") or "Unknown Item")
        try:
            qty = float(str(line.get("quantite", "0")).replace(",", ".").replace(" ", ""))
        except ValueError:
            qty = 0.0
        price = float(line.get("price_unit") or line.get("erp_price") or 0)
        id_article = line.get("id_article") or 0
        if not id_article:
            cursor.execute(
                "SELECT IDArticle FROM article WHERE Code = %s LIMIT 1",
                (code.upper(),),
            )
            row = cursor.fetchone()
            if row:
                id_article = row["IDArticle"]

        cursor.execute(
            """
            INSERT INTO lignefac (
                IDFacture, IDArticle, Code, LibProd, Quantite, PrixVente,
                prixMP, TauxTVA, Ordre
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                id_facture,
                id_article or 0,
                code[:50],
                lib,
                qty,
                price,
                float(line.get("erp_price") or price),
                19.0,
                ordre,
            ),
        )
        if line.get("validation_status") == "PRICE_MISMATCH":
            cursor.execute(
                """
                INSERT INTO reconciliation_alerts (
                    IDFacture, type, description, is_resolved
                ) VALUES (%s, %s, %s, 0)
                """,
                (
                    id_facture,
                    "price_mismatch",
                    f"Code {code}: OCR {line.get('price_unit')} vs ERP {line.get('erp_price')}",
                ),
            )

    cursor.execute(
        """
        INSERT INTO extraction_metadata (
            IDFacture, raw_json, avg_confidence, model_version
        ) VALUES (%s, %s, %s, %s)
        """,
        (
            id_facture,
            json.dumps({"general_info": info, "product_lines": lines}, ensure_ascii=False),
            sum(float(l.get("confidence") or 0) for l in lines) / max(len(lines), 1),
            "ocr-api-v2",
        ),
    )

    log_info(
        "Invoice saved to ERP",
        id_facture=id_facture,
        lib_facture=lib_facture,
        lines_saved=len(lines),
        approved_by=approved_by,
    )

    alert = evaluate_price_mismatch_alert(lines, total_ht)
    if alert:
        log_warn(
            "Price mismatch alert threshold exceeded",
            pct=alert["pct"],
            threshold_pct=alert["threshold_pct"],
            mismatch_lines=alert["mismatch_lines"],
        )
        mismatch_details = [
            {
                "code": l.get("code") or l.get("code_pct") or "",
                "designation": l.get("designation") or "",
                "ocr_price": l.get("price_unit") or l.get("ocr_price"),
                "erp_price": l.get("erp_price"),
            }
            for l in lines
            if l.get("validation_status") == "PRICE_MISMATCH"
        ]
        dispatch_discrepancy_alert(
            invoice_id=lib_facture,
            vendor_name=supplier,
            total_amount=total_ht,
            mismatch_details=mismatch_details,
            mismatch_pct=alert["pct"],
        )
        if notify_accountant:
            create_notification(
                username=notify_accountant,
                type="price_alert",
                title="Price discrepancy threshold exceeded",
                message=(
                    f"Invoice {lib_facture}: {alert['pct']:.1f}% of lines "
                    f"have price mismatches (threshold {alert['threshold_pct']:.0f}%)."
                ),
                invoice_ref=lib_facture,
            )

    return {
        "id_facture": id_facture,
        "lib_facture": lib_facture,
        "lines_saved": len(lines),
    }
