"""Administrator API routes — mounted from api.py. Protected by ADMINISTRATOR role."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from routes.auth import get_current_user, get_password_hash, require_role
from services.admin_config import load_config, save_config
from services.admin_logger import log_info, read_logs
from services.erp_invoice_sync import post_invoice_to_erp
from services.invoice_submissions import (
    WORKFLOW_ON_HOLD,
    WORKFLOW_PENDING,
    WORKFLOW_POSTED,
    check_can_approve,
    ensure_submissions_table,
    get_submission_by_id,
    list_submissions,
    update_workflow_status,
)
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
    approval_rules: dict[str, Any] = Field(default_factory=dict)
    alert_rules: dict[str, Any] = Field(default_factory=dict)
    notifications: dict[str, Any] = Field(default_factory=dict)


class ApproveErpBody(BaseModel):
    force: bool = False


class HoldBody(BaseModel):
    note: Optional[str] = None


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


@router.get("/pending-invoices")
def get_pending_invoices(
    status: str = Query("ALL"),
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    ensure_submissions_table()
    return list_submissions(
        workflow_status=status,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/pending-invoices/{submission_id}")
def get_pending_invoice_detail(submission_id: int):
    ensure_submissions_table()
    try:
        return get_submission_by_id(submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/pending-invoices/{submission_id}/approve-erp")
def approve_pending_invoice(
    submission_id: int,
    body: ApproveErpBody,
    user: dict[str, Any] = Depends(get_current_user),
):
    ensure_submissions_table()
    cfg = load_config()
    rules = cfg.get("approval_rules") or {}
    try:
        submission = get_submission_by_id(submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        check_can_approve(submission, force=body.force, approval_rules=rules)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    payload = submission.get("payload") or {}
    submitted_by = submission.get("submitted_by") or "OCR-API"
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        result = post_invoice_to_erp(
            cursor,
            payload,
            saisi_par=submitted_by,
            approved_by=user["sub"],
            notify_accountant=submitted_by,
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()

    updated = update_workflow_status(
        submission_id,
        workflow_status=WORKFLOW_POSTED,
        approved_by=user["sub"],
        id_facture=result["id_facture"],
        force_approved=body.force,
    )
    log_info(
        "Admin approved invoice to ERP",
        submission_id=submission_id,
        id_facture=result["id_facture"],
        approved_by=user["sub"],
        force=body.force,
    )
    return {
        "status": "success",
        "submission": updated,
        "erp": result,
    }


@router.post("/pending-invoices/{submission_id}/hold")
def hold_pending_invoice(submission_id: int, body: HoldBody):
    ensure_submissions_table()
    try:
        submission = get_submission_by_id(submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if submission.get("workflow_status") == WORKFLOW_POSTED:
        raise HTTPException(status_code=400, detail="Cannot hold a posted invoice.")
    updated = update_workflow_status(
        submission_id,
        workflow_status=WORKFLOW_ON_HOLD,
        admin_note=body.note,
    )
    return {"status": "success", "submission": updated}


@router.post("/pending-invoices/{submission_id}/release")
def release_pending_invoice(submission_id: int):
    ensure_submissions_table()
    try:
        submission = get_submission_by_id(submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if submission.get("workflow_status") != WORKFLOW_ON_HOLD:
        raise HTTPException(status_code=400, detail="Only ON_HOLD submissions can be released.")
    updated = update_workflow_status(
        submission_id,
        workflow_status=WORKFLOW_PENDING,
    )
    return {"status": "success", "submission": updated}


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
