"""Administrator API routes — mounted from api.py. Protected by ADMINISTRATOR role."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from routes.auth import get_password_hash, require_role
from services.admin_config import load_config, save_config
from services.admin_logger import read_logs
from services.admin_telemetry import (
    aggregate_from_extraction_metadata,
    ensure_admin_tables,
    get_kpi_metrics,
    get_validation_breakdown,
    get_volume_series,
)
from services.db import get_db_connection

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMINISTRATOR"))],
)


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: str
    password: str = Field(min_length=6)
    role: Literal["ACCOUNTANT", "ADMINISTRATOR"] = "ACCOUNTANT"


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[Literal["ACCOUNTANT", "ADMINISTRATOR"]] = None
    status: Optional[Literal["ACTIVE", "SUSPENDED"]] = None
    password: Optional[str] = Field(default=None, min_length=6)


class AdminConfigPayload(BaseModel):
    confidence_threshold: float = Field(ge=0.5, le=0.99)
    default_dpi: int = Field(ge=150, le=450)
    alert_rules: dict[str, Any] = Field(default_factory=dict)
    notifications: dict[str, Any] = Field(default_factory=dict)


def _hash_password(raw: str) -> str:
    return get_password_hash(raw)


def _user_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["IDUser"],
        "username": row["Username"],
        "email": row["Email"],
        "role": row["Role"],
        "status": row["Status"],
        "created_at": row["CreatedAt"].isoformat()
        if isinstance(row.get("CreatedAt"), datetime)
        else str(row.get("CreatedAt") or ""),
    }


def seed_default_admin() -> None:
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS cnt FROM system_users")
        if int((cursor.fetchone() or {}).get("cnt") or 0) > 0:
            return
        cursor.execute(
            """
            INSERT INTO system_users (Username, Email, PasswordHash, Role, Status)
            VALUES (%s, %s, %s, %s, 'ACTIVE')
            """,
            (
                "admin",
                "admin@diva.local",
                _hash_password("admin123"),
                "ADMINISTRATOR",
            ),
        )
        cursor.execute(
            """
            INSERT INTO system_users (Username, Email, PasswordHash, Role, Status)
            VALUES (%s, %s, %s, %s, 'ACTIVE')
            """,
            (
                "accountant",
                "accountant@diva.local",
                _hash_password("accountant123"),
                "ACCOUNTANT",
            ),
        )
        conn.commit()
    finally:
        conn.close()


@router.get("/users")
def list_users():
    ensure_admin_tables()
    seed_default_admin()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT IDUser, Username, Email, Role, Status, CreatedAt FROM system_users ORDER BY IDUser ASC"
        )
        return {"users": [_user_row(r) for r in cursor.fetchall()]}
    finally:
        conn.close()


@router.post("/users", status_code=201)
def create_user(payload: UserCreate):
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            INSERT INTO system_users (Username, Email, PasswordHash, Role, Status)
            VALUES (%s, %s, %s, %s, 'ACTIVE')
            """,
            (
                payload.username.strip(),
                str(payload.email).strip(),
                _hash_password(payload.password),
                payload.role,
            ),
        )
        conn.commit()
        user_id = cursor.lastrowid
        cursor.execute(
            "SELECT IDUser, Username, Email, Role, Status, CreatedAt FROM system_users WHERE IDUser = %s",
            (user_id,),
        )
        row = cursor.fetchone()
        return {"user": _user_row(row)}
    except Exception as exc:
        conn.rollback()
        if "Duplicate" in str(exc):
            raise HTTPException(status_code=409, detail="Username or email already exists.") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


@router.put("/users/{user_id}")
def update_user(user_id: int, payload: UserUpdate):
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT IDUser FROM system_users WHERE IDUser = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="User not found.")

        fields: list[str] = []
        values: list[Any] = []
        if payload.email is not None:
            fields.append("Email = %s")
            values.append(str(payload.email))
        if payload.role is not None:
            fields.append("Role = %s")
            values.append(payload.role)
        if payload.status is not None:
            fields.append("Status = %s")
            values.append(payload.status)
        if payload.password:
            fields.append("PasswordHash = %s")
            values.append(_hash_password(payload.password))

        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update.")

        values.append(user_id)
        cursor.execute(
            f"UPDATE system_users SET {', '.join(fields)} WHERE IDUser = %s",
            tuple(values),
        )
        conn.commit()
        cursor.execute(
            "SELECT IDUser, Username, Email, Role, Status, CreatedAt FROM system_users WHERE IDUser = %s",
            (user_id,),
        )
        return {"user": _user_row(cursor.fetchone())}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if "Duplicate" in str(exc):
            raise HTTPException(status_code=409, detail="Email already in use.") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


@router.delete("/users/{user_id}")
def delete_user(user_id: int, hard: bool = Query(False)):
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT IDUser, Username FROM system_users WHERE IDUser = %s", (user_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        if hard:
            cursor.execute("DELETE FROM system_users WHERE IDUser = %s", (user_id,))
            action = "deleted"
        else:
            cursor.execute(
                "UPDATE system_users SET Status = 'SUSPENDED' WHERE IDUser = %s",
                (user_id,),
            )
            action = "suspended"
        conn.commit()
        return {"status": "success", "action": action, "user_id": user_id}
    finally:
        conn.close()


@router.get("/metrics")
def get_metrics():
    kpis = get_kpi_metrics()
    volume = get_volume_series()
    breakdown = get_validation_breakdown()
    if sum(breakdown.values()) == 0:
        breakdown = aggregate_from_extraction_metadata()
    return {
        **kpis,
        "volume_by_day": volume,
        "validation_breakdown": breakdown,
    }


@router.get("/logs")
def get_logs(
    search: str = Query(""),
    severity: str = Query("all"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    entries, total = read_logs(
        search=search.strip(),
        severity=severity.lower(),
        limit=limit,
        offset=offset,
    )
    return {"logs": entries, "total": total}


@router.get("/config")
def get_config():
    return load_config()


@router.post("/config")
def post_config(payload: AdminConfigPayload):
    saved = save_config(payload.model_dump())
    return saved
