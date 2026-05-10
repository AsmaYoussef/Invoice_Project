"""Headless invoice OCR entrypoint for FastAPI and other non-Streamlit callers."""

from pipeline.streamlit_ocr_app import extract_invoice_from_file


def extract_data(file_path: str) -> dict:
    """Run the full invoice OCR pipeline on a PDF or image path."""
    result = extract_invoice_from_file(file_path, include_debug_images=False)
    doc = result["document_payload"]
    return {
        "header": result["header"],
        "totals": result["totals"],
        "line_items": result["line_items"],
        "v2_export": result["v2_export"],
        "document": doc,
        "invoice_number": doc.get("numero"),
        "supplier": doc.get("fournisseur_nom"),
        "document_type": doc.get("type"),
    }
