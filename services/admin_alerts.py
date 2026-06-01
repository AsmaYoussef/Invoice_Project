"""Production alert dispatch engine -- SMTP email + webhook notifications."""
from __future__ import annotations

import smtplib
import traceback
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests

from services.admin_config import load_config
from services.admin_logger import log_error, log_info, log_warn


def _smtp_config() -> dict[str, Any]:
    return load_config().get("smtp") or {}


def _notification_targets() -> dict[str, list[str]]:
    cfg = load_config().get("notifications") or {}
    return {
        "emails": list(cfg.get("emails") or []),
        "webhooks": list(cfg.get("webhooks") or []),
    }


def _send_email(subject: str, html_body: str, recipients: list[str]) -> None:
    smtp = _smtp_config()
    host = smtp.get("host", "").strip()
    if not host or not recipients:
        return

    port = int(smtp.get("port", 587))
    username = smtp.get("username", "")
    password = smtp.get("password", "")
    from_addr = smtp.get("from_address", "alerts@diva.local")
    use_tls = smtp.get("use_tls", True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP(host, port, timeout=15)
        if use_tls:
            server.starttls()
        if username and password:
            server.login(username, password)
        server.sendmail(from_addr, recipients, msg.as_string())
        server.quit()
        log_info("Alert email sent", subject=subject, recipients=recipients)
    except Exception as exc:
        log_error("SMTP email dispatch failed", exc=exc, subject=subject)


def _post_webhook(url: str, payload: dict[str, Any]) -> None:
    if not url:
        return
    try:
        requests.post(url, json=payload, timeout=10)
        log_info("Webhook dispatched", url=url)
    except Exception as exc:
        log_error("Webhook dispatch failed", exc=exc, url=url)


def dispatch_discrepancy_alert(
    *,
    invoice_id: str,
    vendor_name: str,
    total_amount: float,
    mismatch_details: list[dict[str, Any]],
    mismatch_pct: float,
) -> None:
    targets = _notification_targets()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows_html = ""
    for d in mismatch_details:
        ocr = d.get("ocr_price") or 0
        erp = d.get("erp_price") or 0
        diff = round(abs(float(ocr) - float(erp)), 3)
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 12px;border:1px solid #e2e8f0'>{d.get('code','')}</td>"
            f"<td style='padding:6px 12px;border:1px solid #e2e8f0'>{d.get('designation','')}</td>"
            f"<td style='padding:6px 12px;border:1px solid #e2e8f0;text-align:right'>{ocr}</td>"
            f"<td style='padding:6px 12px;border:1px solid #e2e8f0;text-align:right'>{erp}</td>"
            f"<td style='padding:6px 12px;border:1px solid #e2e8f0;text-align:right;color:#dc2626'>{diff}</td>"
            f"</tr>"
        )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto">
      <h2 style="color:#dc2626">Price Discrepancy Alert</h2>
      <p>A financial discrepancy was detected during invoice reconciliation.</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0">
        <tr><td style="padding:4px 0;font-weight:bold">Invoice ID</td><td>{invoice_id}</td></tr>
        <tr><td style="padding:4px 0;font-weight:bold">Vendor</td><td>{vendor_name}</td></tr>
        <tr><td style="padding:4px 0;font-weight:bold">Total HT</td><td>{total_amount:.2f} TND</td></tr>
        <tr><td style="padding:4px 0;font-weight:bold">Mismatch %</td><td style="color:#dc2626;font-weight:bold">{mismatch_pct:.2f}%</td></tr>
        <tr><td style="padding:4px 0;font-weight:bold">Detected At</td><td>{now}</td></tr>
      </table>
      <h3 style="color:#334155">Affected Line Items</h3>
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:#f1f5f9">
            <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:left">Code</th>
            <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:left">Designation</th>
            <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right">OCR Price</th>
            <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right">ERP Price</th>
            <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right">Difference</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p style="margin-top:24px;color:#64748b;font-size:12px">
        InvoScan &mdash; Automated OCR Reconciliation Engine
      </p>
    </div>
    """

    _send_email(
        subject=f"[InvoScan ALERT] Price Discrepancy \u2014 Invoice {invoice_id}",
        html_body=html,
        recipients=targets["emails"],
    )

    webhook_fields = [
        {"name": d.get("code", ""), "value": f"OCR {d.get('ocr_price',0)} vs ERP {d.get('erp_price',0)}"}
        for d in mismatch_details[:10]
    ]
    webhook_payload = {
        "content": f"**[PRICE ALERT]** Invoice `{invoice_id}` \u2014 {mismatch_pct:.2f}% mismatch",
        "embeds": [
            {
                "title": f"Price Discrepancy \u2014 Invoice {invoice_id}",
                "color": 0xDC2626,
                "fields": [
                    {"name": "Vendor", "value": vendor_name, "inline": True},
                    {"name": "Total HT", "value": f"{total_amount:.2f} TND", "inline": True},
                    {"name": "Mismatch", "value": f"{mismatch_pct:.2f}%", "inline": True},
                    {"name": "Affected Lines", "value": str(len(mismatch_details)), "inline": True},
                    *webhook_fields,
                ],
                "footer": {"text": f"InvoScan \u2022 {now}"},
            }
        ],
    }

    for url in targets["webhooks"]:
        _post_webhook(url, webhook_payload)

    log_warn(
        "Discrepancy alert dispatched",
        invoice_id=invoice_id,
        vendor=vendor_name,
        mismatch_pct=mismatch_pct,
        email_targets=len(targets["emails"]),
        webhook_targets=len(targets["webhooks"]),
    )


def dispatch_pipeline_failure_alert(
    *,
    filename: str,
    exception_string: str,
) -> None:
    targets = _notification_targets()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stack = traceback.format_exc()

    webhook_payload = {
        "content": f"**[CRITICAL]** Pipeline failure processing `{filename}`",
        "embeds": [
            {
                "title": "Pipeline Processing Failure",
                "color": 0xB91C1C,
                "fields": [
                    {"name": "Filename", "value": filename or "unknown", "inline": True},
                    {"name": "Timestamp", "value": now, "inline": True},
                    {"name": "Exception", "value": f"```\n{exception_string[:500]}\n```"},
                    {"name": "Stack Trace", "value": f"```\n{stack[:800]}\n```"},
                ],
                "footer": {"text": "InvoScan \u2022 Critical System Alert"},
            }
        ],
    }

    for url in targets["webhooks"]:
        _post_webhook(url, webhook_payload)

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto">
      <h2 style="color:#b91c1c">Critical Pipeline Failure</h2>
      <table style="width:100%;border-collapse:collapse;margin:16px 0">
        <tr><td style="padding:4px 0;font-weight:bold">File</td><td>{filename}</td></tr>
        <tr><td style="padding:4px 0;font-weight:bold">Time</td><td>{now}</td></tr>
        <tr><td style="padding:4px 0;font-weight:bold">Error</td><td style="color:#b91c1c">{exception_string[:300]}</td></tr>
      </table>
      <h3 style="color:#334155">Stack Trace</h3>
      <pre style="background:#0f172a;color:#f8fafc;padding:12px;border-radius:8px;font-size:11px;overflow:auto;max-height:400px">{stack[:1500]}</pre>
      <p style="margin-top:24px;color:#64748b;font-size:12px">
        InvoScan &mdash; System Administration Alert
      </p>
    </div>
    """

    _send_email(
        subject=f"[InvoScan CRITICAL] Pipeline Failure \u2014 {filename}",
        html_body=html,
        recipients=targets["emails"],
    )

    log_error(
        "Pipeline failure alert dispatched",
        filename=filename,
        exception_string=exception_string[:300],
        webhook_targets=len(targets["webhooks"]),
    )
