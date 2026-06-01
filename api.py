import os

import re

import json

import tempfile

import shutil

import base64

import time

from datetime import datetime

from typing import List, Dict, Any, Optional

import cv2
import numpy as np

import requests

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request

from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from pipeline.streamlit_ocr_app import extract_invoice_from_file

from services.reconciliation import (
    ReconciliationService,
    dashboard_line_to_internal,
    pipeline_line_to_internal,
    parse_quantity,
)
from services.db import get_db_connection
from services.admin_config import evaluate_price_mismatch_alert, load_config
from services.admin_logger import log_error, log_info, log_warn
from services.admin_telemetry import record_pipeline_run
from services.admin_alerts import dispatch_discrepancy_alert, dispatch_pipeline_failure_alert
from api_admin import router as admin_router
from routes.auth import router as auth_router, get_current_user_optional
from routes.accountant import router as accountant_router
from services.accountant_notifications import (
    create_notification,
    ensure_accountant_notifications_table,
)

app = FastAPI(title="InvoScan API")

app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(accountant_router)

UPLOAD_DIR = "temp_uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.on_event("startup")
def _startup_seed():
    """Ensure the default admin user exists so login works on first boot."""
    try:
        from api_admin import seed_default_admin
        seed_default_admin()
        ensure_accountant_notifications_table()
    except Exception:
        pass

class GeneralInfo(BaseModel):

    invoice_number: Optional[str] = ""

    invoice_date: Optional[str] = ""

    supplier_name: Optional[str] = ""

    supplier_mf: Optional[str] = ""

    address: Optional[str] = ""

    document_type: Optional[str] = ""

    invoice_family: Optional[str] = ""

    supplier_status: Optional[str] = None

    erp_supplier_name: Optional[str] = None

    erp_supplier_mf: Optional[str] = None

    erp_supplier_code: Optional[str] = None

    tel: Optional[str] = ""

    fax: Optional[str] = ""

    email: Optional[str] = ""

class ProductLine(BaseModel):

    code: Optional[str] = ""

    code_pct: Optional[str] = ""

    code_article: Optional[str] = ""

    designation: Optional[str] = ""

    quantite: Optional[str] = ""

    ocr_price: Optional[float] = None

    price_unit: Optional[float] = None

    erp_price: Optional[float] = None

    price_from_db: Optional[bool] = False

    erp_name: Optional[str] = None

    validation_status: Optional[str] = "UNCHECKED"

    confidence: Optional[float] = None

    flags: Optional[List[str]] = None

    computed_montant: Optional[float] = None

    id_article: Optional[int] = None

class FinancialTotals(BaseModel):

    total_ht: Optional[float] = 0

    total_ttc: Optional[float] = 0

    tva: Optional[float] = 0

class DashboardPayload(BaseModel):

    general_info: GeneralInfo

    product_lines: List[ProductLine]

    financial_totals: Optional[FinancialTotals] = None

def _image_to_data_url(img) -> str:

    ok, encoded = cv2.imencode(".png", img)

    if not ok:

        return ""

    b64 = base64.b64encode(encoded.tobytes()).decode("utf-8")

    return f"data:image/png;base64,{b64}"


def _clean_img_to_data_url(img) -> str:
    if img is None:
        return ""
    arr = np.asarray(img)
    if arr.size == 0:
        return ""
    if len(arr.shape) == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    return _image_to_data_url(arr)

def _get_db_connection():
    return get_db_connection()

def _parse_invoice_date(raw: str):

    if not raw:

        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):

        try:

            return datetime.strptime(raw.strip()[:10], fmt).date()

        except ValueError:

            continue

    return None

def _lib_facture_from_number(raw: str) -> str:

    digits = "".join(filter(str.isdigit, str(raw or ""))) or "1"

    return f"OCR-{digits[:12]}"

def reconcile_dashboard(

    lines: List[Dict[str, Any]],

    general_info: Dict[str, Any],

    *,

    doc_type: str = "",

    invoice_family: str = "",

) -> Dict[str, Any]:

    conn = _get_db_connection()

    try:

        cursor = conn.cursor(dictionary=True)

        service = ReconciliationService(
            cursor,
            confidence_threshold=float(load_config().get("confidence_threshold", 0.85)),
        )

        service.load_reference_data()

        result = service.reconcile_document(

            lines,

            general_info=general_info,

            doc_type=doc_type,

            invoice_family=invoice_family,

        )

        return result

    finally:

        conn.close()

def _build_general_info(document: Dict[str, Any], invoice_family: str = "") -> Dict[str, Any]:

    return {

        "invoice_number": document.get("numero", ""),

        "invoice_date": document.get("date", ""),

        "supplier_name": document.get("fournisseur_nom", ""),

        "supplier_mf": document.get("supplier_mf", ""),

        "address": document.get("adresse", ""),

        "tel": document.get("tel", ""),

        "fax": document.get("fax", ""),

        "email": document.get("email", ""),

        "document_type": document.get("type", ""),

        "invoice_family": invoice_family,

    }

@app.get("/")

def health():

    return {"status": "Online", "database": "Connected to InvoScan MySQL"}

@app.post("/upload-invoice")

async def upload_and_extract(
    request: Request,
    file: UploadFile = File(...),

    use_nlp: bool = Form(True),

    dpi_choice: int = Form(200),
    use_fix_rotation: bool = Form(True),
    use_erase_color: bool = Form(True),
    use_remove_lines: bool = Form(True),
    use_keep_mask: bool = Form(True),
):

    file_path = None
    started = time.perf_counter()

    try:

        suffix = os.path.splitext(file.filename or "")[1] or ".pdf"

        with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=suffix, delete=False) as temp_file:

            file_path = temp_file.name

        with open(file_path, "wb") as buffer:

            shutil.copyfileobj(file.file, buffer)

        result = extract_invoice_from_file(

            file_path,

            original_filename=file.filename,

            dpi_choice=dpi_choice,

            use_nlp=use_nlp,
            use_fix_rotation=use_fix_rotation,
            use_erase_color=use_erase_color,
            use_remove_lines=use_remove_lines,
            use_keep_mask=use_keep_mask,
            include_debug_images=True,

        )

        original_pages = [_image_to_data_url(img) for img in result.get("all_orig_imgs", [])]

        clean_pages = [_clean_img_to_data_url(img) for img in result.get("all_clean_imgs", [])]

        visualizer_pages = [
            {
                "page": i + 1,
                "original_image_b64": orig,
                "cleaned_image_b64": (clean_pages[i] if i < len(clean_pages) else "") or orig,
            }
            for i, orig in enumerate(original_pages)
        ]

        document = result.get("document_payload", {})

        invoice_family = result.get("invoice_family", "") or ""

        raw_lines = [

            pipeline_line_to_internal(line)

            for line in result.get("all_product_lines", [])

        ]

        general_info = _build_general_info(document, invoice_family)

        reconciled = reconcile_dashboard(

            raw_lines,

            general_info,

            doc_type=document.get("type", ""),

            invoice_family=invoice_family,

        )

        duration_ms = int((time.perf_counter() - started) * 1000)
        page_count = len(original_pages) or 1
        record_pipeline_run(
            filename=file.filename or "upload",
            page_count=page_count,
            duration_ms=duration_ms,
            invoice_number=general_info.get("invoice_number", ""),
            product_lines=reconciled.get("product_lines", []),
            status="SUCCESS",
        )
        log_info(
            "Pipeline extraction completed",
            filename=file.filename,
            invoice_number=general_info.get("invoice_number", ""),
            duration_ms=duration_ms,
            page_count=page_count,
            line_count=len(reconciled.get("product_lines", [])),
        )

        user = get_current_user_optional(request)
        if user and user.get("role") == "ACCOUNTANT":
            lines = reconciled.get("product_lines", [])
            mismatch = sum(1 for l in lines if l.get("validation_status") == "PRICE_MISMATCH")
            unknown = sum(1 for l in lines if l.get("validation_status") == "UNKNOWN_PRODUCT")
            inv_ref = general_info.get("invoice_number") or file.filename or ""
            if mismatch or unknown:
                create_notification(
                    username=user["sub"],
                    type="validation_warning",
                    title="Validation issues detected",
                    message=(
                        f"Invoice {inv_ref}: {mismatch} price mismatch(es), "
                        f"{unknown} unknown product(s). Review before saving."
                    ),
                    invoice_ref=inv_ref,
                )

        return {

            "dashboard": {

                "general_info": reconciled["general_info"],

                "product_lines": reconciled["product_lines"],

                "financial_totals": {

                    "total_ht": document.get("total_ht"),

                    "total_ttc": document.get("total_ttc"),

                    "tva": document.get("tva"),

                },

            },

            "visualizer": {

                "pages": visualizer_pages,

            },

            "technical": {

                "raw_ocr_text": result.get("combined_full", ""),

                "invoice_family": invoice_family,

                "clean_json": result.get("v2_export") or result.get("v2_payload") or {},

                "pipeline_status": {

                    "preprocessing": "Deskew & Thresholding Active",

                    "ocr_engine": "Tesseract OCR + Layout Recovery Active",

                    "nlp_layer": "Extract-Lock-Clean Architecture Active",

                },

            },

        }

    except Exception as e:

        log_error(
            "Pipeline extraction failed",
            exc=e,
            filename=getattr(file, "filename", ""),
        )
        dispatch_pipeline_failure_alert(
            filename=getattr(file, "filename", "unknown"),
            exception_string=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:

        if file_path and os.path.exists(file_path):

            os.remove(file_path)

@app.post("/revalidate")

async def revalidate(data: DashboardPayload):

    try:

        lines = [dashboard_line_to_internal(line.model_dump()) for line in data.product_lines]

        info = data.general_info.model_dump()

        reconciled = reconcile_dashboard(

            lines,

            info,

            doc_type=info.get("document_type", ""),

            invoice_family=info.get("invoice_family", ""),

        )

        totals = data.financial_totals.model_dump() if data.financial_totals else {}

        return {

            "dashboard": {

                "general_info": reconciled["general_info"],

                "product_lines": reconciled["product_lines"],

                "financial_totals": totals,

            },

        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/save-invoice")

async def save_invoice(
    request: Request,
    data: DashboardPayload,
):

    conn = None
    user = get_current_user_optional(request)
    saisi_par = (user["sub"] if user else None) or "OCR-API"

    try:

        conn = _get_db_connection()

        cursor = conn.cursor(dictionary=True)

        info = data.general_info.model_dump()

        lib_facture = _lib_facture_from_number(info.get("invoice_number"))

        cursor.execute(
            "SELECT IDFacture FROM facture WHERE LibFacture = %s LIMIT 1",
            (lib_facture,),
        )
        existing = cursor.fetchone()
        if existing:
            if user and user.get("role") == "ACCOUNTANT":
                create_notification(
                    username=user["sub"],
                    type="save_error",
                    title="Duplicate invoice blocked",
                    message=(
                        f"Invoice '{lib_facture}' was already saved "
                        f"(ID {existing['IDFacture']}). Re-saving is not allowed."
                    ),
                    invoice_ref=lib_facture,
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This invoice was already saved to ERP as '{lib_facture}' "
                    f"(facture ID {existing['IDFacture']}). "
                    "Re-saving the same document is not allowed."
                ),
            )

        date_facture = _parse_invoice_date(info.get("invoice_date", ""))

        supplier = info.get("erp_supplier_name") or info.get("supplier_name") or ""

        total_ht = 0.0

        lines = [line.model_dump() for line in data.product_lines]

        for line in lines:

            qty = float(line.get("quantite") or 0) if str(line.get("quantite", "")).replace(",", ".").replace(" ", "").replace(".", "", 1).isdigit() else 0.0

            try:

                qty = float(str(line.get("quantite", "0")).replace(",", ".").replace(" ", ""))

            except ValueError:

                qty = 0.0

            price = float(line.get("price_unit") or 0)

            total_ht += qty * price

        if data.financial_totals and data.financial_totals.total_ht:

            total_ht = float(data.financial_totals.total_ht)

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

        conn.commit()

        log_info(
            "Invoice saved to ERP",
            id_facture=id_facture,
            lib_facture=lib_facture,
            lines_saved=len(lines),
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
            if user and user.get("role") == "ACCOUNTANT":
                create_notification(
                    username=user["sub"],
                    type="price_alert",
                    title="Price discrepancy threshold exceeded",
                    message=(
                        f"Invoice {lib_facture}: {alert['pct']:.1f}% of lines "
                        f"have price mismatches (threshold {alert['threshold_pct']:.0f}%)."
                    ),
                    invoice_ref=lib_facture,
                )

        if user and user.get("role") == "ACCOUNTANT":
            avg_conf = sum(float(l.get("confidence") or 0) for l in lines) / max(len(lines), 1)
            create_notification(
                username=user["sub"],
                type="save_success",
                title="Invoice saved to ERP",
                message=(
                    f"{lib_facture} saved successfully ({len(lines)} lines, "
                    f"review score {round(avg_conf * 100)}%)."
                ),
                invoice_ref=lib_facture,
            )

        return {

            "status": "success",

            "id_facture": id_facture,

            "lib_facture": lib_facture,

            "lines_saved": len(lines),

        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:

        if conn:

            conn.rollback()

        print(f"Sync Error: {e}")
        log_error("Save to ERP failed", exc=e)

        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:

        if conn:

            conn.close()

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

