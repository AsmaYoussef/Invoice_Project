"""Accountant API: invoice history and in-app notifications."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from routes.auth import get_current_user, require_role
from services.accountant_history import list_invoice_history
from services.accountant_notifications import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

router = APIRouter(
    prefix="/api/accountant",
    tags=["accountant"],
    dependencies=[Depends(require_role("ACCOUNTANT"))],
)


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
