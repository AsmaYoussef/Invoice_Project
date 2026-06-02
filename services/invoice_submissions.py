"""Pending invoice submissions queue (accountant submit → admin ERP post)."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from services.accountant_history import _count_line_statuses, derive_invoice_status
from services.db import get_db_connection

WORKFLOW_PENDING = "PENDING_ADMIN"
WORKFLOW_ON_HOLD = "ON_HOLD"
WORKFLOW_POSTED = "POSTED_TO_ERP"

ACTIVE_WORKFLOWS = frozenset({WORKFLOW_PENDING, WORKFLOW_ON_HOLD})

SCHEMA_STATEMENT = """
CREATE TABLE IF NOT EXISTS invoice_submissions (
    IDSubmission INT AUTO_INCREMENT PRIMARY KEY,
    lib_facture VARCHAR(100) NOT NULL,
    invoice_number VARCHAR(100),
    supplier_name VARCHAR(255),
    invoice_date DATE,
    total_ht DECIMAL(12,3) DEFAULT 0,
    filename VARCHAR(255),
    submitted_by VARCHAR(50) NOT NULL,
    submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    workflow_status ENUM('PENDING_ADMIN', 'ON_HOLD', 'POSTED_TO_ERP') NOT NULL DEFAULT 'PENDING_ADMIN',
    validation_status VARCHAR(30) NOT NULL DEFAULT 'NEEDS_REVIEW',
    review_score_pct DECIMAL(5,2) DEFAULT 0,
    line_count INT DEFAULT 0,
    valid_count INT DEFAULT 0,
    price_mismatch_count INT DEFAULT 0,
    low_confidence_count INT DEFAULT 0,
    unknown_count INT DEFAULT 0,
    payload_json LONGTEXT NOT NULL,
    id_facture INT DEFAULT NULL,
    approved_by VARCHAR(50) DEFAULT NULL,
    approved_at DATETIME DEFAULT NULL,
    admin_note TEXT,
    force_approved TINYINT DEFAULT 0,
    INDEX idx_workflow (workflow_status),
    INDEX idx_submitted_by (submitted_by),
    INDEX idx_lib_facture (lib_facture)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def lib_facture_from_number(raw: str) -> str:
    digits = "".join(filter(str.isdigit, str(raw or ""))) or "1"
    return f"OCR-{digits[:12]}"


def _parse_invoice_date(raw: str) -> date | None:
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _compute_total_ht(payload: dict[str, Any]) -> float:
    financial = payload.get("financial_totals") or {}
    if financial.get("total_ht"):
        return float(financial["total_ht"])
    total = 0.0
    for line in payload.get("product_lines") or []:
        try:
            qty = float(str(line.get("quantite", "0")).replace(",", ".").replace(" ", ""))
        except ValueError:
            qty = 0.0
        price = float(line.get("price_unit") or 0)
        total += qty * price
    return total


def _review_score_pct(product_lines: list[dict[str, Any]]) -> float:
    if not product_lines:
        return 0.0
    avg = sum(float(l.get("confidence") or 0) for l in product_lines) / len(product_lines)
    return round(avg * 100, 1) if avg <= 1 else round(avg, 1)


def summarize_payload(payload: dict[str, Any], *, filename: str = "") -> dict[str, Any]:
    info = payload.get("general_info") or {}
    lines = payload.get("product_lines") or []
    counts = _count_line_statuses(lines)
    validation_status = derive_invoice_status(counts, open_alerts=0)
    supplier = info.get("erp_supplier_name") or info.get("supplier_name") or ""
    return {
        "lib_facture": lib_facture_from_number(info.get("invoice_number")),
        "invoice_number": str(info.get("invoice_number") or "")[:100],
        "supplier_name": supplier[:255],
        "invoice_date": _parse_invoice_date(info.get("invoice_date", "")),
        "total_ht": _compute_total_ht(payload),
        "filename": (filename or "")[:255],
        "validation_status": validation_status,
        "review_score_pct": _review_score_pct(lines),
        "line_count": len(lines),
        "valid_count": counts["VALID"],
        "price_mismatch_count": counts["PRICE_MISMATCH"],
        "low_confidence_count": counts["LOW_CONFIDENCE"],
        "unknown_count": counts["UNKNOWN_PRODUCT"],
    }


def ensure_submissions_table() -> None:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(SCHEMA_STATEMENT)
        conn.commit()
    finally:
        conn.close()


def _facture_exists(cursor, lib_facture: str) -> int | None:
    cursor.execute(
        "SELECT IDFacture FROM facture WHERE LibFacture = %s LIMIT 1",
        (lib_facture,),
    )
    row = cursor.fetchone()
    return int(row["IDFacture"]) if row else None


def _active_submission_exists(cursor, lib_facture: str) -> bool:
    cursor.execute(
        """
        SELECT IDSubmission FROM invoice_submissions
        WHERE lib_facture = %s AND workflow_status IN (%s, %s)
        LIMIT 1
        """,
        (lib_facture, WORKFLOW_PENDING, WORKFLOW_ON_HOLD),
    )
    return cursor.fetchone() is not None


def create_submission(
    *,
    submitted_by: str,
    payload: dict[str, Any],
    filename: str = "",
) -> dict[str, Any]:
    ensure_submissions_table()
    summary = summarize_payload(payload, filename=filename)
    lib = summary["lib_facture"]

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        if _facture_exists(cursor, lib):
            raise ValueError(
                f"Invoice '{lib}' is already posted to ERP. Duplicate submission is not allowed."
            )
        if _active_submission_exists(cursor, lib):
            raise ValueError(
                f"Invoice '{lib}' is already pending administrative review."
            )

        cursor.execute(
            """
            INSERT INTO invoice_submissions (
                lib_facture, invoice_number, supplier_name, invoice_date, total_ht,
                filename, submitted_by, workflow_status, validation_status,
                review_score_pct, line_count, valid_count, price_mismatch_count,
                low_confidence_count, unknown_count, payload_json
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                lib,
                summary["invoice_number"],
                summary["supplier_name"],
                summary["invoice_date"],
                summary["total_ht"],
                summary["filename"],
                submitted_by[:50],
                WORKFLOW_PENDING,
                summary["validation_status"],
                summary["review_score_pct"],
                summary["line_count"],
                summary["valid_count"],
                summary["price_mismatch_count"],
                summary["low_confidence_count"],
                summary["unknown_count"],
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
        return get_submission_by_id(cursor.lastrowid)
    finally:
        conn.close()


def _row_to_summary(row: dict[str, Any], *, approval_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = approval_rules or {}
    min_score = float(rules.get("min_review_score_pct", 85))
    allow_override = bool(rules.get("allow_admin_override", True))
    score = float(row.get("review_score_pct") or 0)
    workflow = row.get("workflow_status") or WORKFLOW_PENDING
    can_approve = workflow in ACTIVE_WORKFLOWS and score >= min_score
    block_reason = None
    if workflow not in ACTIVE_WORKFLOWS:
        block_reason = f"Submission is {workflow}."
    elif score < min_score:
        block_reason = f"Review score {score:.0f}% is below minimum {min_score:.0f}%."

    submitted_at = row.get("submitted_at")
    invoice_date = row.get("invoice_date")

    return {
        "id": row["IDSubmission"],
        "lib_facture": row.get("lib_facture") or "",
        "invoice_number": row.get("invoice_number") or "",
        "supplier_name": row.get("supplier_name") or "",
        "invoice_date": invoice_date.isoformat()
        if hasattr(invoice_date, "isoformat")
        else str(invoice_date or ""),
        "total_ht": float(row.get("total_ht") or 0),
        "filename": row.get("filename") or "",
        "submitted_by": row.get("submitted_by") or "",
        "submitted_at": submitted_at.isoformat()
        if hasattr(submitted_at, "isoformat")
        else str(submitted_at or ""),
        "workflow_status": workflow,
        "validation_status": row.get("validation_status") or "",
        "review_score_pct": score,
        "line_count": int(row.get("line_count") or 0),
        "valid_count": int(row.get("valid_count") or 0),
        "price_mismatch_count": int(row.get("price_mismatch_count") or 0),
        "low_confidence_count": int(row.get("low_confidence_count") or 0),
        "unknown_count": int(row.get("unknown_count") or 0),
        "id_facture": row.get("id_facture"),
        "approved_by": row.get("approved_by"),
        "can_approve": can_approve,
        "allow_admin_override": allow_override,
        "approve_block_reason": block_reason,
    }


def get_submission_by_id(submission_id: int) -> dict[str, Any]:
    ensure_submissions_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM invoice_submissions WHERE IDSubmission = %s",
            (submission_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise LookupError("Submission not found.")
        return _submission_detail(row)
    finally:
        conn.close()


def _submission_detail(row: dict[str, Any]) -> dict[str, Any]:
    from services.admin_config import load_config

    summary = _row_to_summary(row, approval_rules=load_config().get("approval_rules"))
    try:
        payload = json.loads(row.get("payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    summary["payload"] = payload
    summary["admin_note"] = row.get("admin_note")
    summary["force_approved"] = bool(row.get("force_approved"))
    return summary


def list_submissions(
    *,
    workflow_status: str | None = None,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    submitted_by: str | None = None,
) -> dict[str, Any]:
    from services.admin_config import load_config

    ensure_submissions_table()
    rules = load_config().get("approval_rules") or {}
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        clauses = ["1=1"]
        params: list[Any] = []

        if workflow_status and workflow_status.upper() != "ALL":
            clauses.append("workflow_status = %s")
            params.append(workflow_status.upper())

        if submitted_by:
            clauses.append("submitted_by = %s")
            params.append(submitted_by)

        if search.strip():
            like = f"%{search.strip()}%"
            clauses.append(
                "(lib_facture LIKE %s OR invoice_number LIKE %s OR supplier_name LIKE %s OR submitted_by LIKE %s)"
            )
            params.extend([like, like, like, like])

        where = " AND ".join(clauses)
        cursor.execute(
            f"SELECT COUNT(*) AS cnt FROM invoice_submissions WHERE {where}",
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("cnt") or 0)

        cursor.execute(
            f"""
            SELECT * FROM invoice_submissions
            WHERE {where}
            ORDER BY submitted_at DESC, IDSubmission DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params) + (limit, offset),
        )
        items = [_row_to_summary(r, approval_rules=rules) for r in cursor.fetchall()]
        return {"submissions": items, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def list_accountant_submissions(username: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return list_submissions(
        workflow_status="ALL",
        limit=limit,
        offset=offset,
        submitted_by=username,
    )


def update_workflow_status(
    submission_id: int,
    *,
    workflow_status: str,
    admin_note: str | None = None,
    approved_by: str | None = None,
    id_facture: int | None = None,
    force_approved: bool = False,
) -> dict[str, Any]:
    ensure_submissions_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT IDSubmission FROM invoice_submissions WHERE IDSubmission = %s",
            (submission_id,),
        )
        if not cursor.fetchone():
            raise LookupError("Submission not found.")

        fields = ["workflow_status = %s"]
        values: list[Any] = [workflow_status]

        if admin_note is not None:
            fields.append("admin_note = %s")
            values.append(admin_note)
        if approved_by:
            fields.append("approved_by = %s")
            values.append(approved_by[:50])
            fields.append("approved_at = NOW()")
        if id_facture is not None:
            fields.append("id_facture = %s")
            values.append(id_facture)
        if force_approved:
            fields.append("force_approved = 1")

        values.append(submission_id)
        cursor.execute(
            f"UPDATE invoice_submissions SET {', '.join(fields)} WHERE IDSubmission = %s",
            tuple(values),
        )
        conn.commit()
        return get_submission_by_id(submission_id)
    finally:
        conn.close()


def check_can_approve(
    submission: dict[str, Any],
    *,
    force: bool,
    approval_rules: dict[str, Any],
) -> None:
    workflow = submission.get("workflow_status")
    if workflow not in ACTIVE_WORKFLOWS:
        raise ValueError(f"Cannot approve submission in state {workflow}.")

    min_score = float(approval_rules.get("min_review_score_pct", 85))
    score = float(submission.get("review_score_pct") or 0)
    allow_override = bool(approval_rules.get("allow_admin_override", True))

    if score >= min_score:
        return
    if force and allow_override:
        return
    if not allow_override:
        raise ValueError(
            f"Review score {score:.0f}% is below minimum {min_score:.0f}%. "
            "Admin override is disabled."
        )
    raise ValueError(
        f"Review score {score:.0f}% is below minimum {min_score:.0f}%. "
        "Use force=true to override."
    )
