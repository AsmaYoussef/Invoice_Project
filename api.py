from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
import tempfile
import base64
import cv2

from database_integration import InvoiceDBHandler
from pipeline.streamlit_ocr_app import extract_invoice_from_file

# 1. Initialize the FastAPI App
app = FastAPI(title="Diva Software - OCR API")

# 2. Setup CORS (CRITICAL FOR REACT)
# This tells our Python server: "It's okay if a React app on a different port talks to you."
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, we will lock this down to just the React URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Create a temporary folder for uploaded PDFs
UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- ENDPOINT 1: Upload and Extract ---
@app.post("/upload-invoice")
async def upload_and_extract(
    file: UploadFile = File(...),
    use_nlp: bool = Form(True),
    dpi_choice: int = Form(200),
    use_fix_rotation: bool = Form(True),
    use_erase_color: bool = Form(True),
    use_remove_lines: bool = Form(True),
    use_keep_mask: bool = Form(True),
):
    file_path = None
    try:
        # Save the uploaded file temporarily so your OCR can read it
        suffix = os.path.splitext(file.filename or "")[1] or ".pdf"
        with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=suffix, delete=False) as temp_file:
            file_path = temp_file.name
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        result = extract_invoice_from_file(
            file_path,
            original_filename=file.filename,
            use_fix_rotation=use_fix_rotation,
            use_erase_color=use_erase_color,
            use_remove_lines=use_remove_lines,
            use_keep_mask=use_keep_mask,
            dpi_choice=dpi_choice,
            split_zones=True,
            show_tables=True,
            show_products=True,
            use_nlp=use_nlp,
            include_debug_images=True,
        )

        def _image_to_data_url(img) -> str:
            ok, encoded = cv2.imencode(".png", img)
            if not ok:
                return ""
            b64 = base64.b64encode(encoded.tobytes()).decode("utf-8")
            return f"data:image/png;base64,{b64}"

        original_pages = [_image_to_data_url(img) for img in result.get("all_orig_imgs", [])]
        cleaned_pages = [_image_to_data_url(img) for img in result.get("all_clean_imgs", [])]

        document = result.get("document_payload", {})
        confidence = result.get("confidence", {})
        totals = result.get("totals", {})
        field_confidence = {k: round(float(v), 3) for k, v in confidence.items() if isinstance(v, (int, float))}

        extracted_data = {
            "dashboard": {
                "general_info": {
                    "type": document.get("type", ""),
                    "invoice_number": document.get("numero", ""),
                    "invoice_date": document.get("date", ""),
                    "supplier_name": document.get("fournisseur_nom", ""),
                    "supplier_mf": document.get("supplier_mf", ""),
                    "client_mf": document.get("client_mf", ""),
                    "telephone": document.get("tel", ""),
                    "fax": document.get("fax", ""),
                    "email": document.get("email", ""),
                    "rc": document.get("rc", ""),
                    "address": document.get("adresse", ""),
                },
                "financial_totals": {
                    "total_brut_ht": document.get("total_brut_ht"),
                    "remise_pct": document.get("remise_pct"),
                    "total_ht": document.get("total_ht", totals.get("total_ht")),
                    "tva": document.get("tva", totals.get("total_tva")),
                    "transport": document.get("transport"),
                    "timbre_fiscal": document.get("timbre_fiscal"),
                    "total_ttc": document.get("total_ttc", totals.get("total_ttc")),
                    "tva_detail": document.get("tva_detail", []),
                },
                "product_lines": result.get("all_product_lines", []),
            },
            "visualizer": {
                "total_pages": result.get("total_pages", 0),
                "is_pdf": result.get("is_pdf", False),
                "is_native_pdf": result.get("is_native", False),
                "pages": [
                    {
                        "page_number": idx + 1,
                        "original_image_b64": orig,
                        "cleaned_image_b64": cleaned_pages[idx] if idx < len(cleaned_pages) else "",
                    }
                    for idx, orig in enumerate(original_pages)
                ],
            },
            "technical": {
                "raw_ocr_text": result.get("combined_full", ""),
                "field_confidence_scores": field_confidence,
                "warnings": result.get("warnings_nlp", []),
                "extraction_trace": result.get("extraction_trace", {}),
                "table_extraction_audit": result.get("table_extraction_audit", {}),
                "nlp_model": result.get("nlp_model_name", ""),
                "profile_hints": result.get("profile_hints", {}),
            },
            "system_trace": [
                {"step": "Save uploaded file", "status": "done", "detail": file.filename or ""},
                {"step": "Convert PDF/Image to OCR pages", "status": "done", "detail": f"{result.get('total_pages', 0)} page(s)"},
                {"step": "Apply cleaning and DPI preprocessing", "status": "done", "detail": f"DPI {dpi_choice}"},
                {"step": "Run OCR text extraction", "status": "done", "detail": f"{len(result.get('combined_full', ''))} chars extracted"},
                {"step": "Run regex/NLP field extraction", "status": "done", "detail": result.get("predicted_doc_type", "Document")},
                {"step": "Assemble accountant payload", "status": "done", "detail": "dashboard + visualizer + technical"},
            ],
            "raw_pipeline": {
                "header": result.get("header", {}),
                "totals": result.get("totals", {}),
                "line_items": result.get("line_items", []),
                "document_payload": document,
                "v2_export": result.get("v2_export", {}),
            },
        }

        # Clean up the temporary file (optional but good practice)
        os.remove(file_path)

        # Return the JSON data (React will receive this!)
        return extracted_data

    except Exception as e:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 2: Save to Database ---
@app.post("/save-invoice")
async def save_invoice(invoice_data: dict):
    try:
        db = InvoiceDBHandler()
        invoice_id = db.save_extraction(invoice_data)
        return {"status": "success", "invoice_id": invoice_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 3: A simple health check ---
@app.get("/")
def read_root():
    return {"message": "Diva Software OCR API is running!"}