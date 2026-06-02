"""Accountant API: invoice history and in-app notifications."""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from routes.auth import get_current_user, require_role
from services.accountant_history import list_invoice_history
from services.accountant_notifications import (
    create_notification,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from services.admin_logger import log_info
from services.invoice_submissions import create_submission, list_accountant_submissions

router = APIRouter(
    prefix="/api/accountant",
    tags=["accountant"],
    dependencies=[Depends(require_role("ACCOUNTANT"))],
)


class SubmitInvoicePayload(BaseModel):
    general_info: dict[str, Any]
    product_lines: List[dict[str, Any]]
    financial_totals: Optional[dict[str, Any]] = None
    filename: Optional[str] = ""


@router.post("/submit-invoice", status_code=201)
def submit_invoice(
    payload: SubmitInvoicePayload,
    user: dict[str, Any] = Depends(get_current_user),
):
    body = {
        "general_info": payload.general_info,
        "product_lines": payload.product_lines,
        "financial_totals": payload.financial_totals or {},
    }
    try:
        submission = create_submission(
            submitted_by=user["sub"],
            payload=body,
            filename=payload.filename or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    lib = submission.get("lib_facture", "")
    log_info(
        "Invoice submitted for admin approval",
        submission_id=submission.get("id"),
        lib_facture=lib,
        submitted_by=user["sub"],
    )
    create_notification(
        username=user["sub"],
        type="submit_success",
        title="Submitted for administrative approval",
        message=(
            f"Invoice {lib} is queued for admin review "
            f"(score {submission.get('review_score_pct', 0)}%)."
        ),
        invoice_ref=lib,
    )
    return {"status": "success", "submission": submission}


@router.get("/submissions")
def get_submissions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
):
    return list_accountant_submissions(user["sub"], limit=limit, offset=offset)


@router.get("/invoices")
def get_invoice_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
):
    return list_invoice_history(user["sub"], limit=limit, offset=offset)


@router.get("/notifications")
def get_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    user: dict[str, Any] = Depends(get_current_user),
):
    return list_notifications(user["sub"], unread_only=unread_only, limit=limit)


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: int,
    user: dict[str, Any] = Depends(get_current_user),
):
    ok = mark_notification_read(notification_id, user["sub"])
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"status": "success", "id": notification_id}


@router.post("/notifications/read-all")
def read_all_notifications(user: dict[str, Any] = Depends(get_current_user)):
    updated = mark_all_notifications_read(user["sub"])
    return {"status": "success", "marked_read": updated}
