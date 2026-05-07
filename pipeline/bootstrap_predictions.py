from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Dict

import fitz
import pdfplumber
import pytesseract
from PIL import Image


DOC_TYPES = {
    "Proforma": ["proforma", "pro forma", "b.c. interne", "incoterms"],
    "Bon de Commande": ["bon de commande", "commande fournisseur", "bcn-", "bcm-"],
    "Facture": ["facture", "invoice", "facture numero"],
}


def detect_doc_type(text: str) -> str:
    tl = (text or "").lower()
    for dtype, kws in DOC_TYPES.items():
        if any(k in tl for k in kws):
            return dtype
    return "Document"


def extract_text_sample(pdf_path: Path) -> str:
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:2]).strip()
            if text:
                return text[:3000]
    except Exception:
        pass

    # OCR fallback (first page only) for scan-heavy PDFs.
    try:
        doc = fitz.open(str(pdf_path))
        if len(doc) == 0:
            return ""
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        img_bytes = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_bytes))
        text = pytesseract.image_to_string(image, lang="fra+eng", config="--psm 6 --oem 1")
        return (text or "")[:3000]
    except Exception:
        return ""


def build_prediction(case: Dict[str, str]) -> Dict[str, object]:
    source = Path(case["source_file"])
    total_pages = 0
    try:
        with fitz.open(str(source)) as doc:
            total_pages = len(doc)
    except Exception:
        total_pages = 0

    text_sample = extract_text_sample(source)
    return {
        "document": {
            "type": detect_doc_type(text_sample),
            "source_file": str(source),
            "total_pages": total_pages,
        },
        "line_items": [],
        "debug": {
            "bootstrap": True,
            "text_sample_length": len(text_sample),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create initial benchmark prediction files.")
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("pipeline/benchmarks/reference_ground_truth.json"),
        help="Ground-truth benchmark case list.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("pipeline/benchmarks/predictions"),
        help="Output folder for <case_id>_data.json files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing prediction files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.truth.open("r", encoding="utf-8") as fh:
        truth = json.load(fh)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0
    for case in truth.get("cases", []):
        case_id = case["id"]
        out_path = args.out_dir / f"{case_id}_data.json"
        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue
        payload = build_prediction(case)
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        created += 1

    print(json.dumps({"created": created, "skipped": skipped, "output_dir": str(args.out_dir)}, indent=2))


if __name__ == "__main__":
    main()
