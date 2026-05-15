import os
import tempfile
import shutil
import base64
import cv2
import mysql.connector
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any

# --- REAL PIPELINE IMPORT ---
from pipeline.streamlit_ocr_app import extract_invoice_from_file

app = FastAPI(title="Diva Software - Real OCR Sync")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_config = {
    'host': '127.0.0.1',
    'port': 3307,
    'user': 'root',
    'password': 'admin', 
    'database': 'diva_demo',
    'auth_plugin': 'mysql_native_password'
}

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class InvoiceData(BaseModel):
    general_info: Dict[str, Any]
    product_lines: List[Dict[str, Any]]
    financial_totals: Dict[str, Any]

def _image_to_data_url(img) -> str:
    ok, encoded = cv2.imencode(".png", img)
    if not ok: return ""
    b64 = base64.b64encode(encoded.tobytes()).decode("utf-8")
    return f"data:image/png;base64,{b64}"

@app.get("/")
def health():
    return {"status": "Online", "database": "Connected to Diva MySQL"}

# --- REAL EXTRACTION ENDPOINT ---
@app.post("/upload-invoice")
async def upload_and_extract(
    file: UploadFile = File(...),
    use_nlp: bool = Form(True),
    dpi_choice: int = Form(200),
):
    file_path = None
    try:
        suffix = os.path.splitext(file.filename or "")[1] or ".pdf"
        with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=suffix, delete=False) as temp_file:
            file_path = temp_file.name
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # CALL YOUR REAL MODEL
        result = extract_invoice_from_file(
            file_path,
            original_filename=file.filename,
            dpi_choice=dpi_choice,
            use_nlp=use_nlp,
            include_debug_images=True
        )

        original_pages = [_image_to_data_url(img) for img in result.get("all_orig_imgs", [])]
        document = result.get("document_payload", {})

        # Construct the payload for React
        return {
            "dashboard": {
                "general_info": {
                    "invoice_number": document.get("numero", "0"),
                    "invoice_date": document.get("date", ""),
                    "supplier_name": document.get("fournisseur_nom", "Unknown"),
                },
                "product_lines": result.get("all_product_lines", []),
                "financial_totals": {"total_ttc": document.get("total_ttc", 0)},
            },
            "visualizer": {
                "pages": [{"original_image_b64": p} for p in original_pages]
            }
        }
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# --- REAL SAVE ENDPOINT ---
@app.post("/save-invoice")
async def save_invoice(data: InvoiceData):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # IDFacture MUST be a number for Diva
        raw_id = data.general_info.get("invoice_number", "0")
        clean_id = int(''.join(filter(str.isdigit, str(raw_id))) or "1")

        query = """
            INSERT INTO lignefac (IDFacture, Code, LibProd, Quantité, PrixVente, TauxTVA) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        for line in data.product_lines:
            cursor.execute(query, (
                clean_id,
                str(line.get("code", "N/A")),
                str(line.get("designation", "Unknown Item")),
                float(line.get("quantite") or 0),
                float(line.get("price_unit") or 0),
                19.0
            ))
        
        conn.commit()
        cursor.close()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        print(f"Sync Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)