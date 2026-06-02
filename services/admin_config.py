"""Admin system configuration persisted as JSON on disk."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "admin_settings.json")

os.makedirs(_CONFIG_DIR, exist_ok=True)

DEFAULT_CONFIG: dict[str, Any] = {
    "confidence_threshold": 0.85,
    "default_dpi": 200,
    "approval_rules": {
        "min_review_score_pct": 85,
        "allow_admin_override": True,
    },
    "alert_rules": {
        "enabled": True,
        "price_mismatch_pct_threshold": 15,
    },
    "notifications": {
        "emails": [],
        "webhooks": [],
    },
    "smtp": {
        "host": "",
        "port": 587,
        "username": "",
        "password": "",
        "from_address": "alerts@diva.local",
        "use_tls": True,
    },
}


def _merge_defaults(data: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_CONFIG)
    if not data:
        return merged
    merged["confidence_threshold"] = float(
        data.get("confidence_threshold", merged["confidence_threshold"])
    )
    merged["default_dpi"] = int(data.get("default_dpi", merged["default_dpi"]))
    approval = data.get("approval_rules") or {}
    merged["approval_rules"] = {
        "min_review_score_pct": float(
            approval.get(
                "min_review_score_pct",
                merged["approval_rules"]["min_review_score_pct"],
            )
        ),
        "allow_admin_override": bool(
            approval.get(
                "allow_admin_override",
                merged["approval_rules"]["allow_admin_override"],
            )
        ),
    }
    alert = data.get("alert_rules") or {}
    merged["alert_rules"] = {
        "enabled": bool(alert.get("enabled", merged["alert_rules"]["enabled"])),
        "price_mismatch_pct_threshold": float(
            alert.get(
                "price_mismatch_pct_threshold",
                merged["alert_rules"]["price_mismatch_pct_threshold"],
            )
        ),
    }
    notifications = data.get("notifications") or {}
    merged["notifications"] = {
        "emails": list(notifications.get("emails") or []),
        "webhooks": list(notifications.get("webhooks") or []),
    }
    smtp_in = data.get("smtp") or {}
    merged["smtp"] = {
        "host": str(smtp_in.get("host", merged["smtp"]["host"])),
        "port": int(smtp_in.get("port", merged["smtp"]["port"])),
        "username": str(smtp_in.get("username", merged["smtp"]["username"])),
        "password": str(smtp_in.get("password", merged["smtp"]["password"])),
        "from_address": str(smtp_in.get("from_address", merged["smtp"]["from_address"])),
        "use_tls": bool(smtp_in.get("use_tls", merged["smtp"]["use_tls"])),
    }
    return merged


def load_config() -> dict[str, Any]:
    if not os.path.isfile(_CONFIG_PATH):
        return deepcopy(DEFAULT_CONFIG)
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            return _merge_defaults(json.load(fh))
    except (json.JSONDecodeError, OSError):
        return deepcopy(DEFAULT_CONFIG)


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    merged = _merge_defaults(payload)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
    return merged


def evaluate_price_mismatch_alert(
    lines: list[dict[str, Any]],
    total_ht: float,
) -> dict[str, Any] | None:
    cfg = load_config()
    rules = cfg.get("alert_rules") or {}
    if not rules.get("enabled"):
        return None
    threshold_pct = float(rules.get("price_mismatch_pct_threshold", 15))
    mismatch_lines = [l for l in lines if l.get("validation_status") == "PRICE_MISMATCH"]
    if not mismatch_lines:
        return None
    mismatch_value = 0.0
    for line in mismatch_lines:
        try:
            qty = float(str(line.get("quantite", "0")).replace(",", ".").replace(" ", ""))
        except ValueError:
            qty = 0.0
        ocr_p = float(line.get("price_unit") or line.get("ocr_price") or 0)
        erp_p = float(line.get("erp_price") or 0)
        mismatch_value += abs(ocr_p - erp_p) * qty
    base = float(total_ht or 0)
    if base <= 0:
        return None
    pct = (mismatch_value / base) * 100
    if pct < threshold_pct:
        return None
    return {
        "pct": round(pct, 2),
        "threshold_pct": threshold_pct,
        "mismatch_lines": len(mismatch_lines),
        "notifications": cfg.get("notifications") or {},
    }
