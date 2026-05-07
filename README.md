# 🧾 Automated Invoice Preprocessing & Extraction System

> **Project:** PFE — Final Year Project  
> **Scope (this document):** `invoice_extractor.py` · `invoice_app.py`  
> **Date:** March 2026

---

## 📌 Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [File 1 — `invoice_extractor.py`](#3-file-1--invoice_extractorpy)
   - [What It Does](#what-it-does)
   - [Pipeline Step-by-Step](#pipeline-step-by-step)
   - [Technologies Used & Why](#technologies-used--why)
4. [File 2 — `invoice_app.py`](#4-file-2--invoice_apppy)
   - [What It Does](#what-it-does-1)
   - [UI Sections](#ui-sections)
   - [Technologies Used & Why](#technologies-used--why-1)
5. [The Journey: Errors, Fixes, and Iterations](#5-the-journey-errors-fixes-and-iterations)
6. [Results](#6-results)
7. [How to Run](#7-how-to-run)

---

## 1. Project Overview

The goal of this project is to automatically **extract structured data from pharmaceutical invoices** — both scanned (image-based) PDFs and native (text-based) PDFs. These invoices come from different Tunisian pharmaceutical distributors (Distrimed, MEDIS Proforma, SM Pharma, Opalia, etc.) and have widely different layouts, colors, stamps, and scan quality.

The system:
- Cleans and preprocesses each page image to remove noise, colored stamps, and table borders
- Runs OCR (Optical Character Recognition) to extract raw text
- Parses the text into structured header / body / footer sections
- Outputs a clean JSON file for each invoice
- Provides a visual Streamlit UI to inspect every preprocessing step

---

## 2. System Architecture

```
PDF / Image input
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│              invoice_extractor.py                        │
│                                                          │
│  detect_pdf_type()                                       │
│       ├─ native PDF ──► extract_native_pdf()             │
│       └─ scanned PDF ──► extract_scanned_pdf()           │
│                               │                          │
│             ┌─────────────────┘                          │
│             │  preprocess_scanned_page()                 │
│             │    ├─ fix_rotation()                       │
│             │    ├─ erase_colored_ink()                  │
│             │    ├─ binarize()                           │
│             │    ├─ remove_long_lines()                  │
│             │    └─ build_keep_mask()                    │
│             │                                            │
│             │  run_ocr()                                 │
│             │  clean_extracted_text()                    │
│             │  parse_text_structure()                    │
│             └──────────────────────► result dict + JSON  │
└─────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│              invoice_app.py  (Streamlit UI)              │
│                                                          │
│  Upload PDF/Image                                        │
│  Page selector (multi-page PDFs)                        │
│  preprocess_scanned_page_steps()  ─► 6 step images      │
│  run_ocr() × all pages            ─► text panels        │
│  extract_invoice()                ─► JSON result        │
└─────────────────────────────────────────────────────────┘
```

---

## 3. File 1 — `invoice_extractor.py`

### What It Does

This is the **core processing engine**. It accepts a PDF or image file, runs the full preprocessing and OCR pipeline on every page, and returns a Python dictionary (also saved as JSON) with the following structure:

```json
{
  "pdf_type": "scanned",
  "source_file": "distrimed medis.pdf",
  "total_pages": 3,
  "pages": [
    {
      "page_number": 1,
      "structure": {
        "header": ["DISTRI-MED s | RIB : ...", "..."],
        "body":   ["302463 240 ATOR 10MG B/30 CP", "..."],
        "footer": []
      }
    }
  ]
}
```

---

### Pipeline Step-by-Step

#### Step 1 — PDF Type Detection (`detect_pdf_type`)

Before doing any image processing, we check whether the PDF already contains selectable text (native PDF) or is just a scanned image baked into a PDF (scanned PDF).

- **Native PDF** → text extracted directly using `pdfplumber` (no OCR needed)
- **Scanned PDF** → converted to images first, then processed

> **Why this matters:** Running OCR on a native PDF is unnecessary and introduces errors. Extracting text directly from a native PDF is 100% accurate.

---

#### Step 2 — PDF to Image (`pdf_page_to_image`)

Each page of a scanned PDF is rendered as a high-resolution image at **300 DPI** using `PyMuPDF (fitz)`.

> **Why 300 DPI?** Tesseract's OCR accuracy drops significantly below 200 DPI. 300 DPI is the industry standard for document OCR.

---

#### Step 3 — Rotation Fix (`fix_rotation`)

Many scanned invoices are slightly tilted (1–3°) or fully rotated (90°/180°/270°). The function:

1. Uses **Tesseract OSD** (Orientation and Script Detection) to detect large rotations (90°, 180°, 270°) with confidence scoring
2. Uses **OpenCV `minAreaRect`** on the dark pixel cloud to detect small skew angles (0.3° – 3°)
3. Applies the correction with `warpAffine`

> **Why two methods?** OSD handles coarse rotations well but misses small skew. `minAreaRect` catches fine tilt but can't detect full 90° flips.

---

#### Step 4 — Color Ink Erasure (`erase_colored_ink`)

Pharmaceutical invoices often have **colored rubber stamps** (red, blue, green) overlapping the text. This step:

1. Converts the image to **HSV color space** (Hue-Saturation-Value)
2. Detects colored pixels (saturation ≥ 50, value ≥ 60)
3. Replaces colored non-dark pixels with **white** (erasing the stamp)
4. Forces colored dark pixels to **black** (preserving dark ink text inside stamps)

> **Why HSV and not RGB?** HSV separates color (hue) from brightness, making it much easier to define "colored" vs "gray/black" thresholds that work across different lighting and scan conditions.

**Key tuning (after fixes):**

| Parameter | Before | After | Reason |
|---|---|---|---|
| Min saturation | 25 | **50** | Avoid erasing lightly tinted text |
| Min value | 40 | **60** | Same |
| Dilation kernel | 5×5 | **3×3** | Less bleed into adjacent text |
| Dark threshold | < 100 | **< 80** | More conservative — preserve dark text |

---

#### Step 5 — Binarization (`binarize`)

The grayscale image is converted to pure black and white using **Adaptive Gaussian Thresholding**.

> **Why adaptive thresholding instead of simple (Otsu)?** Scanned invoices have uneven lighting — darker edges, brighter center. Adaptive thresholding calculates a different threshold per small region (block size 25px), making it robust to shadows and scanning artifacts.

---

#### Step 6 — Table Line Removal (`remove_long_lines`)

Invoice tables have horizontal and vertical borders that can confuse OCR (it may try to read the lines as characters). This step:

1. Uses **morphological opening** with a long horizontal kernel (80×1 px) to isolate horizontal lines
2. Same with a tall vertical kernel (1×80 px) to isolate vertical lines
3. Uses **connected component analysis** to identify and protect text blobs near the lines
4. Removes only line pixels that are **not adjacent to protected text**

> **Why protect text?** Without protection, the long-line removal erases letters like `|`, `l`, `1`, `I` that happen to be tall and thin — identical in shape to vertical borders.

---

#### Step 7 — Blob Filtering / Keep Mask (`build_keep_mask`)

After removing lines, leftover noise (dots, smudges, scan artifacts) must be removed without deleting letters. This function:

1. Runs **connected component analysis** on all remaining black blobs
2. Keeps blobs that look like text based on:
   - **Size:** Not too tiny (< 6 px²) and not too huge (> 30,000 px²)
   - **Aspect ratio:** Not too narrow (rules out remaining thin lines)
   - **Fill ratio:** Blob area vs bounding box area (letters have consistent fill)
   - **Stroke variation (CV):** Measures how evenly the blob erodes — letters erode evenly, noise does not

> **Why stroke variation?** A random noise blob collapses unevenly when eroded. A letter erodes predictably. This is the most powerful discriminator between text and noise.

**Key tuning (after fixes):**

| Parameter | Before | After | Reason |
|---|---|---|---|
| Min area | 15 | **6** | Keep accent dots, i-dots |
| Max area | 15,000 | **30,000** | Keep large connected chars |
| Fill ratio cutoff | 0.12 | **0.07** | Keep thin strokes: `l`, `1`, `:` |
| Stroke CV cutoff | 1.5 | **2.5** | More tolerance for varied letterforms |
| Large blob fill | 0.15 | **0.08** | Keep open chars: `C`, `G`, `0` |

---

#### Step 8 — OCR (`run_ocr`)

The cleaned binary image is passed to **Tesseract OCR** in French+English mode (`fra+eng`) with:
- `--psm 6` — assume a single uniform block of text (best for full-page invoices)
- `--oem 1` — LSTM neural network engine (best accuracy)

> **Why bilingue / French+English?** Tunisian pharmaceutical invoices mix French labels ("Désignation", "Bon de Commande") with English abbreviations and Latin product names.

---

#### Step 9 — Text Cleaning (`clean_extracted_text` + `_fix_pharma_codes`)

Raw OCR output contains systematic errors that are predictable and fixable:

**`_fix_pharma_codes` — Product Code Correction**

Pharmaceutical product codes follow a strict format: `PF` + 9 digits (e.g., `PF001500003`). OCR commonly misreads:

| OCR Error | Rule | Fix |
|---|---|---|
| `PFO00400001` | `O` → `0` in digit sequences | `PF000400001` |
| `PFOO1S00016` | `O` → `0`, `S` → `5` | `PF001500016` |
| `FF005500001` | `FF` prefix → `PF` (P misread as F) | `PF005500001` |
| `§ 530,320` | `§` at start of number → `5` | `5 530,320` |
| `ND` (quantity) | "Non disponible" → numeric 0 | `0` |

**`clean_extracted_text` — General Text Cleanup**

- Removes `(cid:XX)` PDF encoding artifacts
- Collapses spaced-out letters (e.g., `O M N I P H A R M` → `OMNIPHARM`) — only for 6+ consecutive spaced letters to avoid false positives on short product specs like `B/30 CP`
- Fixes `l`/`I` ↔ `1` confusion in numeric contexts
- Fixes `°` symbol mistaken for `0`
- Strips leading `"` and `'` from quantity values (`'216` → `216`)
- Removes lines with fewer than 2 alphanumeric characters or >65% symbols

---

#### Step 10 — Text Structure Parsing (`parse_text_structure`)

The cleaned text is segmented into three sections:

- **Header** — everything above the first line that contains 2+ table column keywords (e.g., "Code", "Désignation", "Qté", "Montant")
- **Body** — the table rows (product lines)
- **Footer** — totals, signatures, TVA summary at the bottom

> **Why this split?** Downstream processes (field extraction, JSON output) need to know where the company header ends and the article table begins — without this, you'd extract "DISTRI-MED" as a product name.

---

### Technologies Used & Why

| Library | Role | Why Chosen |
|---|---|---|
| **PyMuPDF (`fitz`)** | Render PDF pages to images | Fastest Python PDF renderer; handles scanned and native PDFs; 300 DPI output |
| **pdfplumber** | Extract text from native PDFs | Excellent table detection and x/y tolerance control for native PDFs |
| **OpenCV (`cv2`)** | All image processing | Industry-standard computer vision library; morphological ops, thresholding, connected components |
| **NumPy** | Array operations | Required by OpenCV; efficient pixel-level math |
| **pytesseract** | OCR engine wrapper | Wraps Google Tesseract — the most accurate open-source OCR, supports French |
| **re (regex)** | Text pattern matching and cleaning | Fast, standard Python library for all text correction rules |
| **json / pathlib** | File I/O | Standard library — no extra dependencies |

---

## 4. File 2 — `invoice_app.py`

### What It Does

This is the **visual interface** — a Streamlit web application that lets you upload any invoice and see exactly what happens to it at each stage of the preprocessing pipeline, along with the OCR output and final extracted JSON for every page.

**Run it with:**
```bash
streamlit run invoice_app.py
```
Then open **http://localhost:8501** in your browser.

---

### UI Sections

#### Sidebar — Controls

| Control | Description |
|---|---|
| File uploader | Accepts PDF, PNG, JPG, TIFF, BMP |
| Run full extraction (JSON) | Checkbox — triggers full pipeline + JSON output |
| Show OCR text panel | Checkbox — shows raw/cleaned text panels |
| Preview DPI slider | Controls render quality for PDF pages (100–300 DPI) |

---

#### Section 1 — Quick Metrics

Four info cards displayed at the top:
- Image dimensions (pixels)
- Current page / total pages
- File type (PDF / JPG / …)
- File size (KB)

---

#### Section 2 — Preprocessing Pipeline (6 Steps)

The most important section. Shows every intermediate image in a horizontal grid:

```
Step 1        Step 2        Step 3          Step 4       Step 5          Step 6
Source   →   Rotated  →  Color Removed  →  Binarized →  Lines Removed →  Final Cleaned
```

Each step has:
- A labeled image card
- An expandable "ℹ️ What this step does" explanation

> **Why show each step individually?** When the final result is bad (missing text), you can immediately see *which step* caused the problem — rotation fix gone wrong, color removal eating text, etc.

---

#### Section 3 — Before / After Comparison

Two dropdown selectors let you pick any two pipeline steps and compare them side by side. Useful for quickly seeing the impact of a specific step.

---

#### Section 4 — OCR Text (All Pages)

**Key improvement:** Processes **all pages** of a multi-page PDF, not just the selected one.

Shows three tabs:
- **Raw OCR (all pages)** — unmodified Tesseract output for all pages combined
- **Cleaned Text (all pages)** — after `clean_extracted_text()` for all pages
- **Per-page view** — collapsible panels showing raw vs cleaned side by side per page, with word count

Word count metrics (Raw / Clean / Removed) shown at the bottom.

---

#### Section 5 — Full Structured Extraction (optional)

When the "Run full extraction" checkbox is enabled:
- Runs `extract_invoice()` on the full file (all pages, all cleaning steps)
- Shows a **per-page expandable summary** with numbered body lines and footer
- Raw JSON available in a collapsible expander
- **Download JSON** button to save the result

---

### Technologies Used & Why

| Library | Role | Why Chosen |
|---|---|---|
| **Streamlit** | Web UI framework | Build interactive data apps in pure Python — no HTML/CSS/JS needed; perfect for ML prototypes |
| **PyMuPDF (`fitz`)** | Render PDF pages for the UI | Same as in extractor — consistent behavior |
| **OpenCV** | Image conversion for display | Convert BGR (OpenCV format) to RGB (browser display format) |
| **NumPy** | Image array handling | Required for image manipulation |

---

## 5. The Journey: Errors, Fixes, and Iterations

### 🔴 Problem 1 — `invoice_app.py` Was Completely Broken

**What happened:** The original `invoice_app.py` called two functions — `preprocess_pipeline()` and `safe_ocr()` — that **did not exist** anywhere in the codebase. Running the app crashed immediately with a `NameError`.

**Root cause:** The app was written against an old version of the extractor that was later refactored.

**Fix:** Complete rewrite of `invoice_app.py`. The new version calls the actual existing functions from `invoice_extractor.py` (`preprocess_scanned_page_steps`, `run_ocr`, `clean_extracted_text`, `extract_invoice`).

---

### 🔴 Problem 2 — Cleaning Was Destroying Letters

**What happened:** After preprocessing, many letters were disappearing from the output — especially thin strokes like `l`, `1`, `i`, accented characters (é, à), and small punctuation. This caused OCR to miss entire words and produce wrong product codes and quantities.

**Root cause:** The `build_keep_mask` function had thresholds that were too conservative:
- Min area of **15 px²** was too high — accent dots and small punctuation are only 6–10 px²
- Fill ratio cutoff of **0.12** was too strict — thin letters like `l` and `1` have very low fill ratios
- Stroke variation cutoff of **1.5** was too tight — many valid letter shapes were being rejected

Additionally, `erase_colored_ink` was erasing too broadly with:
- Saturation threshold set too low (25) → erasing valid slightly-tinted ink
- 5×5 dilation spreading the erase zone too far into adjacent text
- Dark threshold too high (100) → treating some dark-colored text as "colored" and erasing it

**Fixes applied:**

```
build_keep_mask:
  area_min:       15  →  6       (keep tiny accent dots)
  area_max:    15000  →  30000   (keep large connected chars)
  aspect cutoff:  200 →  500     (only skip very elongated, large blobs)
  fill_ratio:    0.12 →  0.07    (keep thin strokes)
  stroke CV:     1.5  →  2.5     (more tolerance for letterforms)
  large fill:    0.15 →  0.08    (keep open glyphs: C, G, 0)

erase_colored_ink:
  saturation_min: 25  →  50      (don't erase lightly tinted ink)
  value_min:      40  →  60      (same)
  dilation kernel: 5×5 → 3×3    (less spread)
  dark threshold: 100  → 80      (keep more dark colored ink as text)
```

**Safety net added:** If the blob filter removes more than 99% of pixels (< 300 dark px), the function falls back to plain binarization instead of returning a near-blank page.

---

### 🔴 Problem 3 — Spaced-Letter Collapse Wrong

**What happened:** `clean_extracted_text` had a rule to collapse spaced-out letters like `O M N I P H A R M` (which OCR sometimes produces for bold text) into `OMNIPHARM`. The rule triggered on sequences of **3+ spaced uppercase letters**.

This incorrectly collapsed product descriptions like `B/30 CP` → `B/30CP` or fragmented designations.

**Fix:** Raised the threshold from 3+ to **6+ consecutive spaced uppercase letters** before collapsing. Short pharmaceutical specs are safe.

---

### 🔴 Problem 4 — Product Codes Full of Wrong Characters

**What happened:** PF-series product codes (e.g., `PF001500003`) were being read with systematic OCR errors:

| OCR Output | Actual value |
|---|---|
| `PFO00400001` | `PF000400001` |
| `PFOO1S00016` | `PF001500016` |
| `FF005500001` | `PF005500001` |
| `§ 530,320` | `5 530,320` |

**Root cause:** Tesseract confuses `O` with `0`, `S` with `5`, and sometimes `P` with `F` in digit-dense sequences. The `§` symbol appears when `5` is at the very start of a word.

**Fix:** Added `_fix_pharma_codes()` — a targeted correction function applied before the general text cleaning. It:
- Detects PF/PE/PH/FF code patterns using regex
- Replaces `O→0`, `S→5`, `I→1`, `B→8` only within the numeric portion of codes
- Converts `FF` prefix to `PF`
- Converts `§` before digits to `5`
- Converts standalone `ND` quantities to `0`

---

### 🔴 Problem 5 — Multi-Page PDFs Only Showing First Page

**What happened:** The OCR text panel in the UI only ran OCR on the currently selected page. For a 3-page invoice, only page 1's text was shown. Users had no way to see or verify content from pages 2 and 3 without switching the page slider and re-running manually.

**Fix:** OCR panel now loops over **all pages** of the PDF sequentially, accumulates text, and displays:
- One combined text area for all pages
- Per-page expandable sections with word counts

---

### 🔴 Problem 6 — Footer Detection Cutting Off Body Lines

**What happened:** `parse_text_structure` scanned the text backwards from the bottom looking for footer keywords ("total", "tva", "signature", etc.). The scan **stopped immediately** at the first non-footer line it hit. This meant that if page 2 ended with:

```
...product line 47...
TOTAL HT: 45,000
```

The footer scanner would correctly find "TOTAL HT", but then stop — and page 3's structure would be parsed separately, missing continuation of the body.

**Fix:** Changed the footer scanner to:
1. Collect all footer-keyword lines from the last 12 lines
2. Extend the footer region continuously from the lowest-found keyword to the end
3. Never `break` mid-scan — gaps of 1-2 non-footer lines are allowed

---

## 6. Results

### Before vs After — Distrimed MEDIS Invoice

**Before fixes** (raw OCR, page 1):
```
352730 a 0) oO ° ACLASTAT-MEDISTAR 5MG/LOOML INJ FL 100ML
301500 '216 ADEX LP 1.5MGjB/30 CP
302970 60 AMLODIPINE MEDIS 19MG B/30 CP
```

**After fixes** (cleaned OCR, page 1):
```
352730 0 ACLASTAT-MEDISTAR 5MG/100ML INJ FL 100ML
301500 216 ADEX LP 1.5MG B/30 CP
302970 60 AMLODIPINE MEDIS 10MG B/30 CP
```

---

### Before vs After — MEDIS Proforma Product Codes

**Before:**
```
PFO00400001 -DMAX 200000 U UML AMP
PFOO1S00016 ATOR 20 MG CP B90
FF005500001 PIDOGREL 75 MG CP B30
§ 530,320
```

**After `_fix_pharma_codes()`:**
```
PF000400001 -DMAX 200000 U UML AMP
PF001500016 ATOR 20 MG CP B90
PF005500001 PIDOGREL 75 MG CP B30
5 530,320
```

---

### UI — Pipeline Visualizer

The Streamlit app provides a 6-step visual pipeline:

| Step | Image shown |
|---|---|
| 1 · Source | Original color scan |
| 2 · Rotated | After rotation/deskew correction |
| 3 · Color Removed | After stamp/colored ink erasure |
| 4 · Binarized | Black and white (adaptive threshold) |
| 5 · Lines Removed | Table borders removed |
| 6 · Final Cleaned | After blob filter — text only |

Plus: before/after comparison, per-page OCR text, and downloadable JSON.

---

## 7. How to Run

### Prerequisites

```bash
pip install pymupdf pdfplumber opencv-python pytesseract numpy streamlit
```

Also install **Tesseract OCR** for Windows:  
https://github.com/UB-Mannheim/tesseract/wiki  
Default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`

Make sure the `fra` (French) language pack is installed.

---

### Run the Visualizer UI

```bash
streamlit run invoice_app.py
```

Open → http://localhost:8501

---

### Run Extraction Only (no UI)

```python
from invoice_extractor import extract_invoice
import json

result = extract_invoice("your_invoice.pdf", save_debug_images=True)
with open("result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
```

---

*Documentation written for PFE — Automated Invoice Intelligence System, March 2026.*
