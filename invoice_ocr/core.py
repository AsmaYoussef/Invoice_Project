import cv2
import numpy as np
import pytesseract
import fitz
import re
import json
import os

# --- TESSERACT CONFIG ---
# Make sure this matches your PC!
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- KNOWLEDGE BASE LOADER ---
def load_db():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vendors.json')
    if os.path.exists(db_path):
        with open(db_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

VENDOR_DB = load_db()

# --- FILE HANDLER ---
def get_images_from_upload(uploaded_file):
    images = []
    file_bytes = uploaded_file.read()
    if uploaded_file.type == "application/pdf":
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)
            images.append(img)
        doc.close()
    else:
        nparr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        images.append(img)
    return images

# --- HEADER EXTRACTOR ---
def extract_header_deep(img):
    text = pytesseract.image_to_string(img, lang='fra')
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    data = {
        "document_type": "Inconnu",
        "invoice_no": "—",
        "date": "—",
        "mf_supplier": "—",
        "address": "—",
        "vendor_name": "—"
    }

    # 1. Document Type
    doc_types = {
        r'\bbon\s+de\s+commande\b': "Bon de Commande",
        r'\bbon\s+de\s+livraison\b': "Bon de Livraison",
        r'\bfacture\b': "Facture",
        r'\bavoir\b': "Avoir"
    }
    for pattern, doc_name in doc_types.items():
        if re.search(pattern, text, re.I): data["document_type"] = doc_name

    # 2. Invoice/Doc Number
    num_match = re.search(r'(?:N°|Facture N°|BCN|BL|FA|BC)[\s:.-]*([A-Z0-9/-]{4,15})', text, re.I)
    if num_match: data["invoice_no"] = num_match.group(1).strip()

    # 3. Date
    date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', text)
    if date_match: data["date"] = date_match.group(1)

    # 4. Matricule Fiscal & Vendor Name (Using the DB)
    mf_match = re.search(r'(\d{6,8})\s*[A-Z]/\w/\w/\d{3}', text, re.I)
    if mf_match:
        core_mf = mf_match.group(1)
        data["mf_supplier"] = re.search(r'(\d{6,8}\s*[A-Z]/\w/\w/\d{3})', text, re.I).group(1)
        
        # Check DB for name
        for known_mf, info in VENDOR_DB.items():
            if known_mf in core_mf:
                data["vendor_name"] = info["supplier_name"]
                break

    # 5. Address keywords
    address_keywords = [r'\bRoute\b', r'\bAvenue\b', r'\bAv\.\b', r'\bRue\b', r'\bZ\.?I\b']
    for i, line in enumerate(lines):
        for kw in address_keywords:
            if re.search(kw, line, re.I):
                city_line = lines[i+1] if i+1 < len(lines) else ""
                data["address"] = f"{line} {city_line}".strip()
                break
        if data["address"] != "—": break

    # Fallback Name if not in DB
    if data["vendor_name"] == "—" and lines:
        if not re.search(r'facture|bon|page', lines[0], re.I):
            data["vendor_name"] = lines[0]

    return data

# --- BODY EXTRACTOR (DYNAMIC LANES) ---
def extract_table_dynamic_headers(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    d = pytesseract.image_to_data(gray, lang='fra', output_type=pytesseract.Output.DICT)
    
    lines = {}
    for i in range(len(d['text'])):
        if int(d['conf'][i]) > 30:
            y = d['top'][i] // 15 * 15 
            x = d['left'][i]
            text = d['text'][i].strip()
            if text:
                if y not in lines: lines[y] = []
                lines[y].append({'x': x, 'text': text})

    column_lanes = {}
    header_y = -1
    
    # 1. Find Header Row
    for y in sorted(lines.keys()):
        words = sorted(lines[y], key=lambda item: item['x'])
        line_str = " ".join([w['text'].lower() for w in words])
        
        if 'code' in line_str or 'qte' in line_str or 'qté' in line_str or 'prix' in line_str or 'desig' in line_str:
            header_y = y
            for w in words:
                txt = w['text'].lower()
                if 'code' in txt or 'ref' in txt: column_lanes['Code'] = w['x']
                elif 'qte' in txt or 'qté' in txt or 'quant' in txt: column_lanes['Quantité'] = w['x']
                elif 'prix' in txt or 'p.u' in txt or 'pu' in txt: column_lanes['Prix Unitaire'] = w['x']
                elif 'desig' in txt or 'produit' in txt or 'article' in txt: column_lanes['Désignation'] = w['x']
            break

    rows = []
    # 2. Extract Data using Lanes
    if header_y != -1 and column_lanes:
        for y in sorted(lines.keys()):
            if y <= header_y + 15: continue 
            
            words = sorted(lines[y], key=lambda item: item['x'])
            
            if re.match(r'^[\w\d]{3,}', words[0]['text']):
                row_data = {"Code": "—", "Quantité": "—", "Prix Unitaire": "—", "Désignation": []}
                
                for w in words:
                    wx, text = w['x'], w['text']
                    closest_col, min_dist = None, 9999
                    
                    for col_name, col_x in column_lanes.items():
                        dist = abs(wx - col_x)
                        if dist < min_dist and dist < 120: 
                            min_dist = dist
                            closest_col = col_name
                            
                    if closest_col == 'Code': row_data['Code'] = text
                    elif closest_col == 'Quantité' and (text.isdigit() or ',' in text): row_data['Quantité'] = text
                    elif closest_col == 'Prix Unitaire' and (text.isdigit() or ',' in text or '.' in text): row_data['Prix Unitaire'] = text
                    else: row_data['Désignation'].append(text)
                
                row_data['Désignation'] = " ".join(row_data['Désignation'])
                rows.append(row_data)

    return rows