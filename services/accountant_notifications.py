"""In-app notifications for accountant users."""
from __future__ import annotations

from typing import Any

from services.db import get_db_connection

SCHEMA_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS accountant_notifications (
    IDNotification INT AUTO_INCREMENT PRIMARY KEY,
    Username VARCHAR(50) NOT NULL,
    type VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    invoice_ref VARCHAR(100),
    is_read TINYINT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_unread (Username, is_read, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_accountant_notifications_table() -> None:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(SCHEMA_NOTIFICATIONS)
        conn.commit()
    finally:
        conn.close()


def create_notification(
    *,
    username: str,
    type: str,
    title: str,
    message: str = "",
    invoice_ref: str = "",
) -> int | None:
    if not username:
        return None
    ensure_accountant_notifications_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO accountant_notifications
                (Username, type, title, message, invoice_ref, is_read)
            VALUES (%s, %s, %s, %s, %s, 0)
            """,
            (
                username[:50],
                type[:50],
                title[:255],
                message,
                (invoice_ref or "")[:100],
            ),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)
    finally:
        conn.close()


def list_notifications(
    username: str,
    *,
    unread_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    ensure_accountant_notifications_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        where = "WHERE Username = %s"
        params: list[Any] = [username]
        if unread_only:
            where += " AND is_read = 0"
        cursor.execute(
            f"""
            SELECT IDNotification, Username, type, title, message, invoice_ref,
                   is_read, created_at
            FROM accountant_notifications
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (*params, limit),
        )
        rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt FROM accountant_notifications
            WHERE Username = %s AND is_read = 0
            """,
            (username,),
        )
        unread = int((cursor.fetchone() or {}).get("cnt") or 0)
        return {
            "notifications": [_row_to_dict(r) for r in rows],
            "unread_count": unread,
        }
    finally:
        conn.close()


def mark_notification_read(notification_id: int, username: str) -> bool:
    ensure_accountant_notifications_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE accountant_notifications
            SET is_read = 1
            WHERE IDNotification = %s AND Username = %s
            """,
            (notification_id, username),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_all_notifications_read(username: str) -> int:
    ensure_accountant_notifications_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE accountant_notifications
            SET is_read = 1
            WHERE Username = %s AND is_read = 0
            """,
            (username,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    return {
        "id": row["IDNotification"],
        "type": row["type"],
        "title": row["title"],
        "message": row.get("message") or "",
        "invoice_ref": row.get("invoice_ref") or "",
        "is_read": bool(row.get("is_read")),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
    }
