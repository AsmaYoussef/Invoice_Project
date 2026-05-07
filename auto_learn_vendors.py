import os
import fitz
import pytesseract
import cv2
import numpy as np
import re
import json

# Set your Tesseract path
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# The folder where all your 100MB of PDFs are stored
DATASET_FOLDER = "dataset"
OUTPUT_JSON = "vendors.json"

def process_pdf_header(pdf_path):
    """Opens a PDF, reads only the top half of the first page to find the vendor."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    # Get image of the first page
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)
    doc.close()

    # Crop to top 30% (where the supplier info always is)
    h, w = img.shape[:2]
    header_crop = img[0:int(h*0.3), 0:w]
    
    # Extract text
    text = pytesseract.image_to_string(header_crop, lang='fra')
    
    vendor_data = {}
    
    # 1. Find Matricule Fiscal
    mf_match = re.search(r'(\d{6,8})\s*[A-Z]/\w/\w/\d{3}', text, re.I)
    if mf_match:
        core_mf = mf_match.group(1)
        
        # 2. Guess Supplier Name (Usually the first or second line of text)
        lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 3]
        guessed_name = lines[0] if lines else "UNKNOWN_SUPPLIER"
        
        # Avoid picking up generic words as the name
        if "REPUBLIQUE" in guessed_name.upper() or "FACTURE" in guessed_name.upper():
            guessed_name = lines[1] if len(lines) > 1 else "UNKNOWN_SUPPLIER"

        vendor_data[core_mf] = {
            "supplier_name": guessed_name,
            "expected_client": "MEDIS", # Defaulting to your main client
            "layout_type": "GENERIC_LAYOUT", # Can be manually tweaked later
            "columns": ["Code", "Quantité", "Désignation", "Prix Unitaire"] # Default guess
        }
        
    return vendor_data

def main():
    print("🚀 Starting Auto-Discovery of Vendors...")
    all_vendors = {}
    
    # Loop through every PDF in the dataset folder
    for filename in os.listdir(DATASET_FOLDER):
        if filename.lower().endswith(".pdf"):
            print(f"Scanning {filename}...")
            filepath = os.path.join(DATASET_FOLDER, filename)
            
            try:
                found_vendor = process_pdf_header(filepath)
                all_vendors.update(found_vendor) # Add to our master list
            except Exception as e:
                print(f"Error scanning {filename}: {e}")

    # Save the master list to JSON
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(all_vendors, f, indent=4, ensure_ascii=False)
        
    print(f"✅ Done! Successfully learned {len(all_vendors)} suppliers.")
    print(f"Data saved to {OUTPUT_JSON}")

if __name__ == "__main__":
    main()