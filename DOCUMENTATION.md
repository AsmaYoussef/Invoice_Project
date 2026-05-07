# 📄 Invoice Processing System — Technical Documentation

> **Scope:** `invoice_extractor.py` · `invoice_app.py`
> **Project:** Automated Invoice Intelligence System (PFE)
> **Date:** March 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technologies Used](#2-technologies-used)
3. [File 1 — `invoice_extractor.py`](#3-file-1--invoice_extractorpy)
4. [File 2 — `invoice_app.py`](#4-file-2--invoice_apppy)
5. [Processing Pipeline (End to End)](#5-processing-pipeline-end-to-end)
6. [Journey — Errors, Setbacks & Fixes](#6-journey--errors-setbacks--fixes)
7. [Results](#7-results)

---

## 1. Project Overview

This system takes **pharmaceutical invoice documents** (PDFs or scanned images) and automatically:

1. Converts them into images at high resolution
2. Cleans and normalizes the image (remove noise, table lines, color ink)
3. Runs OCR (Optical Character Recognition) to extract text
4. Structures the text into JSON (header, body lines, footer)
5. Visualizes every step in an interactive web interface
---

## 2. Technologies Used

| Library | Role | Why we used it |
|---|---|---|
| **OpenCV (`cv2`)** | Image processing | Industry standard for computer vision. Handles binarization, morphology, connected components, rotation. Very fast (C++ under the hood). |
| **NumPy** | Array operations | All images are NumPy arrays. Essential for pixel-level operations and masks. |
| **PyMuPDF (`fitz`)** | PDF → image | Converts PDF pages to high-DPI images without needing external tools like Ghostscript. |
| **Tesseract / `pytesseract`** | OCR engine | Free, open-source OCR with good French + Arabic support. Used with LSTM neural net mode for better accuracy. |
| **pdfplumber** | Native PDF text | Extracts selectable text from digital PDFs (non-scanned). Preserves column layout better than other tools. |
| **Streamlit** | Web UI | Lets you build interactive Python apps with no HTML/CSS knowledge. Perfect for data/ML demos. |
| **re (Regex)** | Text cleaning | Fast pattern matching for fixing OCR errors, extracting phone numbers, dates, product codes. |

---

## 3. File 1 — `invoice_extractor.py`

This is the **core processing engine**. It contains 8 parts:

---

### Part 1 — PDF Type Detection

```python
def detect_pdf_type(pdf_path) -> str: ...
```

Opens the PDF and counts extractable characters. If there are more than 100, the PDF has embedded text (native). Otherwise it's a scan.

- **Native PDF** → skip image conversion, use `pdfplumber` directly
- **Scanned PDF** → convert to images, then OCR

---

### Part 2 — Image Preprocessing

This is the most important part. A scanned invoice straight from a scanner or camera is noisy, tilted, and full of colored stamps. We clean it step by step:

#### `pdf_page_to_image()`
Renders one PDF page into a high-resolution BGR (color) image using PyMuPDF at 300 DPI. 300 DPI is the minimum for reliable OCR.

#### `fix_rotation()`
Two-stage rotation correction:
1. **Tesseract OSD** — asks Tesseract what angle the page is at (0°, 90°, 180°, 270°)
2. **`minAreaRect`** — OpenCV finds the minimum bounding rectangle of all dark pixels, giving the skew angle (tiny tilts like 1.2°)

Only rotates if confidence is above 2.0 to avoid false corrections.

#### `erase_colored_ink()`
Pharmaceutical invoices often have colored rubber stamps (blue/red) that confuse OCR. This function:
- Converts to HSV color space (better for color detection than RGB)
- Detects saturated pixels (saturation ≥ 50, value ≥ 60)
- Replaces light colored pixels → white (background)
- Keeps dark colored pixels → black (text ink)

> **Why HSV and not RGB?** In RGB, "red" covers a wide range. In HSV, all reds share the same hue range regardless of brightness, making thresholding much more reliable.

#### `binarize()`
Converts grayscale to pure black-and-white using **Adaptive Gaussian Threshold** (block size 25, C=8). Unlike global Otsu threshold, this adapts to local lighting variations — essential for scans with uneven illumination.

#### `remove_long_lines()`
Table borders in invoices span horizontally or vertically for dozens or hundreds of pixels. OCR tries to read these as characters and fails. We:
1. Use morphological **opening** with a 80×1 kernel to detect horizontal lines
2. Use a 1×80 kernel to detect vertical lines
3. Build a **text protection mask** — any connected component with text-like dimensions is protected
4. Erase only lines that don't overlap protected text

#### `build_keep_mask()` + `stroke_cv()`
This is the most advanced cleaning step. We analyze every connected black blob on the cleaned image and decide: is this text or noise?

**Criteria to keep a blob:**
| Condition | Reason |
|---|---|
| Area ≥ 6 pixels | Keeps accent dots, i-dots, cedillas |
| Area ≤ 30,000 pixels | Removes large filled regions (solid stamps) |
| Aspect ratio ≤ 25 (if area > 500) | Removes long thin lines |
| Fill ratio ≥ 0.07 | Keeps thin strokes: `l`, `1`, `i`, `:` |
| Stroke CV < 2.5 | Text has varying stroke widths (serifs), noise has uniform width |

`stroke_cv()` measures how variable a blob's stroke width is by repeatedly eroding it and measuring pixel loss. Uniform shapes (noise) erode predictably; letters do not.

#### `preprocess_scanned_page()` 
Runs the full pipeline in sequence:
Source → Rotation → Color removal → Binarize → Remove lines → Keep only text

🆕 **Safety fallback:** if the final result has fewer than 300 dark pixels (meaning the filter was too aggressive), fall back to pure binarization.

#### 🆕 `preprocess_scanned_page_steps()` *(Added for UI)*
Same as above but returns **every intermediate image** as a dictionary, so the Streamlit app can display each step visually.

---

### Part 3 — OCR

```python
def run_ocr(img) -> str: ...
```

Calls Tesseract with:
- `lang="fra+eng"` — French + English combined model
- `--psm 6` — assumes a single uniform text block
- `--oem 1` — LSTM neural network only (most accurate)

---

### Part 4 — Text Cleaning (`clean_extracted_text`)

Raw OCR output is always messy. This function applies a chain of regex fixes:

| Fix | Example | Rule |
|---|---|---|
| Remove PDF artifacts | `(cid:10)` → `` | `re.sub(r'\(cid:\d+\)', ...)` |
| Collapse spaced letters | `O M N I P H A R M` → `OMNIPHARM` | Only when 6+ uppercase letters |
| Fix table border `\|` noise | `MEDIS\|COM` → `MEDIS COM` | Between alphanumeric chars |
| Degree/zero confusion | `5°4` → `504` | After digit, before digit |
| `l`/`I` → `1` confusion | `2l5` → `215` | Between digits only |
| 🆕 PF product code repair | `PFO00400001` → `PF000400001` | Via `_fix_pharma_codes()` |
| 🆕 `§` symbol → `5` | `§ 530,320` → `5 530,320` | Start of numeric context |
| 🆕 Strip quote noise | `'216` → `216` | Line-start quotes before digits |
| 🆕 `ND` quantities → `0` | `ND` → `0` | Non-disponible products |
| Remove noise-only lines | Lines with < 2 alnum chars | Symbol ratio filter |

#### 🆕 `_fix_pharma_codes()` — Key Addition

Pharmaceutical product codes in Tunisia follow the pattern `PFxxxxxxxxxx` (2-letter prefix + 10 digits). OCR frequently misreads them because:
- `O` and `0` look identical at low resolution
- `S` and `5` are very similar
- `I` and `1` are indistinguishable
- `P` can be misread as `F` (giving `FF` instead of `PF`)

This function applies these fixes **only inside code sequences**, so normal words like `SOCIAL` or `DOSE` are never affected.

```
PFO00400001 → PF000400001    (O→0)
PFOO1S00016 → PF001500016    (two O→0, S→5)
FF005500001 → PF005500001    (FF→PF)
```

---

### Part 5 — Text Structure Parser

```python
def parse_text_structure(text) -> dict: ...
```

Splits the cleaned text into three zones:
- **Header** — everything above the table column headers
- **Body** — the line items (products, quantities, prices)
- **Footer** — totals, TVA, signatures

Detection strategy:
- Find the first line containing ≥ 2 table keywords (`désignation`, `qté`, `code`, `prix`…)
- Everything above = header
- Scan from the bottom for footer keywords (`total`, `tva`, `ttc`, `timbre`…)

🆕 **Fixed footer detection:** Originally it stopped scanning backwards at the first non-footer line, which caused the last body lines to be silently moved into the footer. The fix does a proper collection-then-resolve pass.

---

### Parts 6 & 6.5 — Scanned PDF / Direct Image Pipeline

```python
def extract_scanned_pdf(pdf_path, save_debug_images) -> dict: ...
def extract_image(img_path, save_debug_images) -> dict: ...
```

Both loop through pages, run the preprocessing pipeline, run OCR, clean text, and structure it. Results are collected into a unified JSON dict with `pages[]` array.

---

### Part 7 — Master Entry Point

```python
def extract_invoice(file_path, save_debug_images) -> dict: ...
```

Auto-detects the input type:
- `.pdf` → check if native or scanned, branch accordingly
- `.jpg/.png/.tiff/…` → direct image pipeline

Returns unified JSON regardless of input type.

---

## 4. File 2 — `invoice_app.py`

A **Streamlit** web application that makes the pipeline interactive and visual. Users upload a file and immediately see every processing step.

### Architecture

```
Sidebar (controls)
│
├── Upload widget (PDF / PNG / JPG / TIFF)
├── Page selector slider (multi-page PDFs)
├── DPI selector (100–300)
├── ☑ Run full extraction checkbox
└── ☑ Show OCR panel checkbox

Main Area
│
├── Metrics row (image dimensions, page count, file size)
├── Pipeline grid (6 step images side by side)
├── Before/After comparator (any two steps)
├── OCR text panel ← 🆕 multi-page
└── Full JSON extraction panel ← 🆕 per-page body view
```

### Key Sections

#### Pipeline Grid
Calls `preprocess_scanned_page_steps()` on the selected page and displays the 6 intermediate images in a responsive column layout. Each image card has an expandable explanation.

#### Before/After Comparator
Two `st.selectbox` widgets let the user pick any two steps. Both images render side by side — useful for quickly seeing what a specific step removed or changed.

#### 🆕 Multi-Page OCR Panel
Previously: only ran OCR on the page selected by the slider.

Now: loops through **all pages** of the PDF, preprocesses each one, runs OCR, and cleans the text. Results are shown in three tabs:
- `Raw OCR (all pages)` — full concatenated raw text
- `Cleaned Text (all pages)` — after `clean_extracted_text()`
- `Per-page view` — one expandable section per page, raw + cleaned side by side

#### 🆕 Full JSON Panel
Previously: dumped the raw JSON blob directly.

Now: renders a **readable per-page summary** — numbered body lines inside expandable sections for each page. The raw JSON is still accessible inside a collapsed expander. A download button saves the result as `.json`.

---

## 5. Processing Pipeline (End to End)

```
Upload (PDF / Image)
        │
        ▼
 detect_pdf_type()
    │           │
  native      scanned / image
    │           │
    │     pdf_page_to_image() ← 300 DPI
    │           │
    │     fix_rotation()
    │           │
    │     erase_colored_ink()
    │           │
    │     binarize()  [adaptive threshold]
    │           │
    │     remove_long_lines()
    │           │
    │     build_keep_mask()  [blob filter]
    │           │
    ▼           ▼
 pdfplumber   run_ocr()  [Tesseract LSTM]
    │           │
    └────┬──────┘
         │
  _fix_pharma_codes()
         │
  clean_extracted_text()
         │
  parse_text_structure()
         │
         ▼
   { header, body, footer }  ← per page
         │
         ▼
     result JSON
```

---

## 6. Journey — Errors, Setbacks & Fixes

### ❌ Setback 1 — `invoice_app.py` Was Completely Broken

**Problem:** The original `invoice_app.py` called two functions that did not exist:
```python
final, steps = preprocess_pipeline(img)   # ← does not exist
text = safe_ocr(final)                    # ← does not exist
```

The app crashed immediately on startup.

**Fix:** Full rewrite of `invoice_app.py`. Created `preprocess_scanned_page_steps()` in the extractor to expose intermediate images, and built the full Streamlit UI from scratch around the existing extractor functions.

---

### ❌ Setback 2 — Cleaning Was Destroying Letters

**Problem:** The `build_keep_mask()` blob filter was too strict. Many real characters were being removed before OCR could read them. Common casualties:
- Thin strokes: `l`, `1`, `i`, `:`
- Accent dots: `é`, `è`, `ê`, `à`
- Small characters: `°`, `'`

This caused downstream extraction errors — product names and quantities were missing letters or numbers.

**Root causes and fixes:**

| Parameter | Old value | New value | Effect |
|---|---|---|---|
| Min blob area | 15 | **6** | Keeps accent dots and i-dots |
| Max blob area | 15,000 | **30,000** | Keeps large connected characters |
| Fill ratio threshold | 0.12 | **0.07** | Keeps thin strokes |
| Stroke CV threshold | 1.5 | **2.5** | Accepts more letter shapes |
| Large blob fill | 0.15 | **0.08** | Keeps open chars `C`, `G`, `0` |

---

### ❌ Setback 3 — Colored Ink Removal Erased Text

**Problem:** `erase_colored_ink()` had a very low saturation threshold (25). On some documents, lightly colored ink that was actually important text was being turned white and lost before OCR.

**Fix:** Raised saturation minimum from 25 → **50**, value minimum from 40 → **60**. Reduced dilation kernel from 5×5 → **3×3**. Added a stricter dark pixel threshold (100 → **80**) so colored dark ink is forced to black instead of being erased.

---

### ❌ Setback 4 — `clean_extracted_text` Collapsed Real Designations

**Problem:** A regex rule was designed to collapse spaced-out OCR artifacts like `O M N I P H A R M` → `OMNIPHARM`. But with a threshold of only 3+ uppercase letters, it also collapsed things like:

```
B 30 CP → B30CP    (wrong)
5 MG → 5MG         (wrong)
```

These are product designation fragments that were being joined together incorrectly.

**Fix:** Raised threshold from 3+ → **6+** consecutive spaced uppercase letters before collapsing. Short sequences are now left untouched.

---

### ❌ Setback 5 — Systematic Product Code OCR Errors

**Problem:** Tesseract consistently misread characters in `PF`-prefixed product codes:

```
PFO00400001   (O misread as O, should be 0)
PFOO1S00016   (double O, S misread as S, should be 0015)
FF005500001   (P misread as F at low resolution)
§ 530,320     (§ misread instead of digit 5)
```

These errors propagated into the output JSON, making product matching impossible.

**Fix:** Wrote `_fix_pharma_codes()` — a targeted function that runs before the general text cleaning. It applies character corrections **only inside** PF/PE/PH code sequences (2-letter prefix + 7–12 alphanumeric), so normal words are never affected.

---

### ❌ Setback 6 — Footer Detection Cut Off Body Lines

**Problem:** `parse_text_structure()` scanned backwards from the end of the page looking for footer keywords (`total`, `tva`, `ttc`…). When it found a line that was NOT a footer keyword, it immediately `break`ed. This meant that if a single body line appeared after the total lines, the scanner stopped — and all previous footer lines were treated as body content, OR body lines near the bottom were classified as footer.

**Fix:** Replaced the `break`-on-first-non-match logic with a **set-based collector** that scans the last 12 lines, collects all footer candidates, then resolves the continuous footer block from the bottom up. Non-footer lines within the zone no longer abort the scan.

---

### ❌ Setback 7 — Multi-Page PDF Only Showed First Page in UI

**Problem:** The OCR text panel in `invoice_app.py` only processed the single page selected by the PDF slider. For a 3-page order document, you would only see page 1's text — and page 2 and 3 were invisible in the UI.

**Fix:** Replaced the single-page OCR call with a loop over all pages. Each page is preprocessed and OCR'd independently. Results are concatenated and also shown as per-page expandable sections.

---

## 7. Results

### Before vs After — Product Code Accuracy

| OCR Output (before) | After fix |
|---|---|
| `PFO00400001` | ✅ `PF000400001` |
| `PFOO1S00016` | ✅ `PF001500016` |
| `FF005500001` | ✅ `PF005500001` |
| `352464` (misread PCT) | ✅ `302464` (unchanged — 6-digit codes not touched) |
| `§ 530,320` | ✅ `5 530,320` |

### Before vs After — Cleaning Quality

| Issue | Before | After |
|---|---|---|
| Thin strokes (`l`, `1`, `:`) | Often removed | Preserved |
| Accent characters (`é`, `è`) | Frequently lost | Mostly preserved |
| Colored stamp erasure | Also erasing nearby text | Only erases non-dark colored regions |
| Letter-level OCR collapses | `B 30 CP` → `B30CP` | Threshold raised, short sequences left intact |

### What the UI Now Provides

| Feature | Before | After |
|---|---|---|
| Preprocessing visualizer | Crashed (missing functions) | ✅ 6-step pipeline with labels and descriptions |
| Before/After comparator | — | ✅ Any two steps selectable |
| OCR text | 1 page only | ✅ All pages, tabbed |
| JSON extraction | Raw JSON blob | ✅ Per-page line listing + download button |
| Error reporting | Silent crash | ✅ Full traceback shown in UI |

### Sample Output (Proforma — MEDIS, 3 pages)

```json
{
  "pdf_type": "scanned",
  "source_file": "distrimed medis.pdf",
  "total_pages": 3,
  "pages": [
    {
      "page_number": 1,
      "structure": {
        "header": ["DISTRI-MED | Code TVA: 989014 Y/P/M/000", "..."],
        "body": [
          "302730 216 ADEX LP 1.5MG B/30 CP",
          "302968 100 AMLODIPINE MEDIS 5MG B/30 CP",
          "302463 240 ATOR 10MG B/30 CP",
          "..."
        ],
        "footer": []
      }
    },
    { "page_number": 2, "structure": { ... } },
    { "page_number": 3, "structure": { ... } }
  ]
}
```

---

## Running the Application

### Prerequisites

```powershell
pip install opencv-python-headless pytesseract pymupdf pdfplumber streamlit numpy
```

Tesseract OCR must be installed and the path set in `invoice_extractor.py` line 13:
```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

### Launch

```powershell
cd "c:\Users\rladh\Desktop\9raya\PFE"
streamlit run invoice_app.py
```

Open browser at **http://localhost:8501**

---

*Documentation generated March 2026 — PFE Automated Invoice Intelligence System*
