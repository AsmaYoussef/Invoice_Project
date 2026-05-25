"""Admin telemetry: pipeline run recording and KPI aggregation."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from services.db import get_db_connection

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS system_users (
        IDUser INT AUTO_INCREMENT PRIMARY KEY,
        Username VARCHAR(50) NOT NULL UNIQUE,
        Email VARCHAR(150) NOT NULL UNIQUE,
        PasswordHash VARCHAR(255) NOT NULL,
        Role ENUM('ACCOUNTANT', 'ADMINISTRATOR') NOT NULL DEFAULT 'ACCOUNTANT',
        Status ENUM('ACTIVE', 'SUSPENDED') NOT NULL DEFAULT 'ACTIVE',
        CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        IDRun INT AUTO_INCREMENT PRIMARY KEY,
        filename VARCHAR(255),
        page_count INT DEFAULT 0,
        duration_ms INT DEFAULT 0,
        invoice_number VARCHAR(100),
        line_count INT DEFAULT 0,
        valid_count INT DEFAULT 0,
        low_conf_count INT DEFAULT 0,
        price_mismatch_count INT DEFAULT 0,
        unknown_count INT DEFAULT 0,
        status VARCHAR(20) DEFAULT 'SUCCESS',
        run_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def ensure_admin_tables() -> None:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for stmt in SCHEMA_STATEMENTS:
            cursor.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def _count_status(lines: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "VALID": 0,
        "LOW_CONFIDENCE": 0,
        "PRICE_MISMATCH": 0,
        "UNKNOWN_PRODUCT": 0,
    }
    for line in lines:
        status = str(line.get("validation_status") or "UNCHECKED").upper()
        if status in counts:
            counts[status] += 1
    return counts


def record_pipeline_run(
    *,
    filename: str,
    page_count: int,
    duration_ms: int,
    invoice_number: str,
    product_lines: list[dict[str, Any]],
    status: str = "SUCCESS",
) -> None:
    ensure_admin_tables()
    counts = _count_status(product_lines)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pipeline_runs (
                filename, page_count, duration_ms, invoice_number,
                line_count, valid_count, low_conf_count,
                price_mismatch_count, unknown_count, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                filename[:255],
                page_count,
                duration_ms,
                (invoice_number or "")[:100],
                len(product_lines),
                counts["VALID"],
                counts["LOW_CONFIDENCE"],
                counts["PRICE_MISMATCH"],
                counts["UNKNOWN_PRODUCT"],
                status[:20],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_kpi_metrics() -> dict[str, Any]:
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS cnt FROM facture")
        total_invoices = int((cursor.fetchone() or {}).get("cnt") or 0)

        cursor.execute(
            """
            SELECT
                COALESCE(AVG(duration_ms / NULLIF(page_count, 0)), 0) AS avg_ms_per_page,
                COUNT(*) AS run_count
            FROM pipeline_runs
            WHERE status = 'SUCCESS' AND page_count > 0
            """
        )
        run_row = cursor.fetchone() or {}
        avg_ms = float(run_row.get("avg_ms_per_page") or 0)
        avg_seconds_per_page = round(avg_ms / 1000, 1)
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(valid_count), 0) AS valid_total,
                COALESCE(SUM(line_count), 0) AS line_total
            FROM pipeline_runs
            """
        )
        valid_row = cursor.fetchone() or {}
        valid_total = int(valid_row.get("valid_total") or 0)
        line_total = int(valid_row.get("line_total") or 0)
        valid_rate_pct = round((valid_total / line_total) * 100, 1) if line_total else 0.0

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM reconciliation_alerts WHERE is_resolved = 0"
        )
        unresolved_alerts = int((cursor.fetchone() or {}).get("cnt") or 0)

        return {
            "total_invoices": total_invoices,
            "avg_seconds_per_page": avg_seconds_per_page,
            "valid_rate_pct": valid_rate_pct,
            "unresolved_alerts": unresolved_alerts,
            "pipeline_run_count": int(run_row.get("run_count") or 0),
        }
    finally:
        conn.close()


def get_volume_series(days: int = 14) -> list[dict[str, Any]]:
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT DATE(run_at) AS day, COUNT(*) AS count
            FROM pipeline_runs
            WHERE run_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            GROUP BY DATE(run_at)
            ORDER BY day ASC
            """,
            (days,),
        )
        return [
            {"date": str(row["day"]), "count": int(row["count"])}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def get_validation_breakdown() -> dict[str, int]:
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(valid_count), 0) AS VALID,
                COALESCE(SUM(low_conf_count), 0) AS LOW_CONFIDENCE,
                COALESCE(SUM(price_mismatch_count), 0) AS PRICE_MISMATCH,
                COALESCE(SUM(unknown_count), 0) AS UNKNOWN_PRODUCT
            FROM pipeline_runs
            """
        )
        row = cursor.fetchone() or {}
        return {
            "VALID": int(row.get("VALID") or 0),
            "LOW_CONFIDENCE": int(row.get("LOW_CONFIDENCE") or 0),
            "PRICE_MISMATCH": int(row.get("PRICE_MISMATCH") or 0),
            "UNKNOWN_PRODUCT": int(row.get("UNKNOWN_PRODUCT") or 0),
        }
    finally:
        conn.close()


def aggregate_from_extraction_metadata() -> dict[str, int]:
    """Fallback breakdown from saved extraction_metadata when pipeline_runs is empty."""
    breakdown = {
        "VALID": 0,
        "LOW_CONFIDENCE": 0,
        "PRICE_MISMATCH": 0,
        "UNKNOWN_PRODUCT": 0,
    }
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT raw_json FROM extraction_metadata ORDER BY IDFacture DESC LIMIT 50")
        for row in cursor.fetchall():
            try:
                payload = json.loads(row.get("raw_json") or "{}")
            except json.JSONDecodeError:
                continue
            for line in payload.get("product_lines") or []:
                status = str(line.get("validation_status") or "").upper()
                if status in breakdown:
                    breakdown[status] += 1
    finally:
        conn.close()
    return breakdown
