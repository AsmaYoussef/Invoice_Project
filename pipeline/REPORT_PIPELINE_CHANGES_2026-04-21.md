# Pipeline & model improvements — implementation report (2026-04-21)

This document summarizes **useful changes that made the invoice extraction pipeline work more reliably**, especially around **field alignment / “field crush”**, **vendor-aware parsing**, **benchmarking**, and the **v2 canonical JSON** export. It also records **what went wrong**, **why**, and **how it was fixed**.

---

## 1. Executive summary

| Theme | What we did | Why it mattered |
|--------|-------------|-----------------|
| **Vendor awareness** | `vendor_profiles.py` with detection, header alias merging, hints into the table/regex path | Different suppliers use different column labels; mapping improves column alignment. |
| **AI assist (no client fork)** | `pipeline/ai/resolver.py` — structured prompts, Pydantic validation, evidence checks | Fills ambiguous document fields and line hints only when the model cites evidence present in OCR text. **`pipeline/client.py` was not modified.** |
| **Regression / quality metrics** | `benchmark_runner.py`, `regression_gate.py`, `empty_field_report.py`, `benchmarks/` assets | Lets you measure empty fields and “polluted designation” before/after changes. |
| **Field crush (legacy path)** | Stronger row grammars, designation recovery, qty plausibility, PF-style code normalization in `streamlit_ocr_app.py` | Reduces quantities, dates, and money leaking into `designation` in the **legacy** `line_items` UI path. |
| **Canonical v2 export** | New schema + per-family parsers + Streamlit wiring + v2-aware `empty_field_report` + tests | **Primary downloaded JSON** is now v2: one shape per invoice family, structure-first parsing from **body OCR**. |

---

## 2. Reliability layer (companion to v2)

These changes support the same goal: **correct columns and fewer empty critical fields**, independent of the v2 JSON shape.

### 2.1 Vendor profiles (`vendor_profiles.py`)

- **Profiles** for major families (e.g. Avenir, Omnipharm, Pharmasud, Modèle Proforma) with `match_tokens`, `doc_types`, `expected_columns`, and **`header_aliases`**.
- **`detect_vendor_profile`** — scores profiles from filename + header + text snippet.
- **`get_profile_hints`** — returns aliases and expected columns for downstream mapping.
- **`merge_header_aliases`** — merges profile aliases into the base header map used when reading tables / headers.
- **`detect_invoice_family`** (added for v2) — returns a **single routing key** for v2 parsers: `proforma_modele`, `bc_avenir`, `bc_omnipharm`, `bc_pharmasud`, or `unknown`, with a guard so “Modèle Proforma” does not fire without Proforma-like context.

### 2.2 AI resolver (`pipeline/ai/resolver.py`)

- Wraps the existing JSON client behind **`resolve_ambiguous_fields`**.
- Enforces **`value` + `evidence` + `confidence`**; drops hints if evidence is not a substring of the source text or confidence is low.
- **`LineItemHint`** whitelist for safe line-level fields (extended later for v2 — see §4).

### 2.3 Benchmarks and reports

- **`benchmark_runner.py`**, **`regression_gate.py`**, reference ground truth / predictions layout under **`pipeline/benchmarks/`**, **`bootstrap_predictions.py`** where applicable.
- **`empty_field_report.py`** — computes rates for legacy exports; **extended** for **`schema_version: 2`** (per-family critical empty rates and aggregates). Input files opened with **`utf-8-sig`** so UTF-8 **BOM** on Windows does not break `json.load`.

### 2.4 Streamlit pipeline (`streamlit_ocr_app.py`) — legacy line path

- Vendor-specific **row grammars**, **designation recovery** (pull qty / date / nb cartons out of noisy designation when plausible), **quantity plausibility** by doc type / profile, **PF / OCR code normalization** helpers.
- **LLM** used only when there are low-confidence document fields or unresolved legacy line items; accepted hints merged back with coercion + plausibility checks.

---

## 3. V2 canonical JSON and family parsers

### 3.1 Schema (`schema_v2.py`)

- **`schema_version: 2`**
- **`invoice_family`** — routing key from `detect_invoice_family`.
- **`document_metadata`** — Pydantic model aligned with cleaned header/totals fields (same spirit as the old `document` object).
- **`line_items`** — list of dicts; shape depends on family:
  - **Proforma:** `code_pct`, `code_article`, `designation_article`, optional `unite_mesure`, `quantite`, `prix_unitaire`, `montant`, `line_confidence`, `raw_line`.
  - **Simple BC (Avenir / Omnipharm):** `code`, `quantite`, `designation`, `line_confidence`, `raw_line`.
  - **Pharmasud:** `code_pct`, `designation`, `quantite_commande`, `nb_cartons`, `unite_carton`, `date_peremption`, `line_confidence`, `raw_line`.
  - **Unknown:** minimal `code` + `raw_line` fallback.

### 3.2 Shared OCR cleaning (`ocr_line_clean.py`)

- Strips noise (`()`, `$`, `°`, repeated junk patterns where applicable), collapses whitespace.
- **`normalize_code_token`** — PF-style repairs (e.g. `FF`→`PF`, digit substitutions in tail) so codes line up with supplier formats.
- **`parse_french_money_token`** — comma decimals and grouped thousands for trailer fields on Proforma.

### 3.3 Parsers (`pipeline/parsers/`)

| Module | Rule (short) |
|--------|----------------|
| **`v2_proforma.py`** | Outside-in: 6-digit-like `code_pct`, PF-like `code_article`, **rightmost trailer triplet** with strict money on PU + montant, middle = designation (+ optional small unit at end). |
| **`v2_simple_bc.py`** | Code at line start (`\d{4,7}` or letter+digit article patterns); **first plausible integer qty after code** (not “token 2”); remainder = designation. |
| **`v2_pharmasud.py`** | Find **`DD/MM/YYYY`** after light OCR repair on the line; split left/right of date; numbers left of date → qty / nb cartons; last number right of date → optional `unite_carton`; designation between code and numeric region. |
| **`__init__.py`** | **`parse_body_lines_v2(family, body_text)`** dispatches; unknown family uses a minimal code+line fallback. |

### 3.4 Assembly and LLM gap-fill (`v2_build.py` + resolver)

- **`build_v2_payload`** — builds the object exported as “clean JSON”.
- **`collect_v2_gap_line_targets`** — lists rows with **missing critical v2 fields** (e.g. Proforma: empty `prix_unitaire` / `montant`; BC: empty `quantite`; Pharmasud: empty `date_peremption` / `quantite_commande`) for a **second** resolver call.
- **`apply_v2_line_hints` / `merge_v2_resolver_hints`** — applies accepted hints only if evidence appears in **full OCR** and in the row’s **`raw_line`**; maps legacy names like `nb_crt` → **`nb_cartons`** where needed.

### 3.5 Streamlit integration

- After legacy merge + first LLM pass: build **`document_payload`**, **`invoice_family`**, parse **combined body** into **`v2_payload`**.
- If **`v2_gaps`** non-empty and the JSON client is available → **`resolve_ambiguous_fields`** with `v2_gap_lines` in the prompt context.
- **Download / JSON preview** use **v2** as the canonical export.
- UI: shows **`v2 · {invoice_family}`** and a **dataframe preview** of v2 `line_items` when product display is enabled.
- Audit JSON may include **`v2_llm_validation`** (second pass status and hints).

---

## 4. Problems, causes, and fixes

| # | Symptom / problem | Cause | Fix |
|---|---------------------|-------|-----|
| 1 | **Wrong Proforma qty / PU / montant** (e.g. qty became part of a money token) | Iterative “merge digit head + next money” glued **`12`** to **`1`** + **`234,56`**, producing a single wrong token and shifting the trailing triplet. | **Single-pass** merge only when head matches **`^\d{1,2}$`** and next token matches **`^\d{3},\d{2,3}$`** (true split French thousands). **Require the last two** trailer tokens to parse as **money** so the triplet is anchored on PU + montant. |
| 2 | **`AMP` pulled into `unite_mesure`** on Proforma | **`AMP`** was in a small “unit” set at end of line but also appears inside **product names** (ampoule). | Removed **`AMP`** from the end-of-line unit allowlist. |
| 3 | **`ModuleNotFoundError` / wrong imports** for new code when running Streamlit | App runs with **`pipeline/`** on `sys.path`, not the parent package **`PFE_AR`**, so **`pipeline.xxx`** imports fail for new modules. | New modules use **sibling imports** (`schema_v2`, `ocr_line_clean`, `parsers`); **`parsers`** package uses **relative** imports (`.v2_proforma`, …). |
| 4 | **`JSONDecodeError: Unexpected UTF-8 BOM`** when running `empty_field_report.py` on files saved from PowerShell / some editors | File starts with **BOM**; strict **`utf-8`** decode is not BOM-tolerant. | Open JSON with **`encoding="utf-8-sig"`**. |
| 5 | Streamlit or tests assume **`accepted_line_item_hints`** always present | Early return paths in the resolver returned only **`ok` / `status`** without an empty list. | All resolver exits return **`accepted_line_item_hints: []`** (and stubs aligned). |
| 6 | Noisy **v2 LLM gap** list | Rows with **no missing fields** but low confidence were still candidates. | **`collect_v2_gap_line_targets`** only emits rows with **non-empty `missing_fields`**. |
| 7 | **`fitz` / wrong Python** when running scripts from system Python | System interpreter missing venv packages. | Run scripts with **`.venv\Scripts\python.exe`** (Windows) from the project. |

---

## 5. Files checklist (high signal)

**Added**

- `pipeline/schema_v2.py`
- `pipeline/ocr_line_clean.py`
- `pipeline/v2_build.py`
- `pipeline/parsers/__init__.py`
- `pipeline/parsers/v2_proforma.py`
- `pipeline/parsers/v2_simple_bc.py`
- `pipeline/parsers/v2_pharmasud.py`
- `pipeline/tests/test_v2_parsers.py`
- (Earlier iteration) `pipeline/ai/resolver.py`, `pipeline/ai/__init__.py`, benchmark / bootstrap scripts under `pipeline/benchmarks/` as applicable to your tree

**Modified (representative)**

- `pipeline/streamlit_ocr_app.py` — legacy extraction improvements + **v2 export + UI + audit hook**
- `pipeline/vendor_profiles.py` — profiles + **`detect_invoice_family`**
- `pipeline/ai/resolver.py` — v2 prompt hints + expanded safe fields + consistent return shape
- `pipeline/empty_field_report.py` — **v1 + v2** analysis and aggregates

**Explicitly not modified (constraint)**

- `pipeline/client.py`

---

## 6. How to verify quickly

```powershell
cd path\to\PFE_AR\pipeline
..\.venv\Scripts\python.exe -m unittest tests.test_v2_parsers -v
```

- Run Streamlit, process a PDF, download **`*_data.json`**: root should show **`schema_version`: 2**, **`invoice_family`**, **`document_metadata`**, **`line_items`** with family-specific keys.
- Run **`empty_field_report.py`** on exported JSON files and inspect **`aggregate.v2`** for per-family critical empty rates.

---

## 7. Definition of success (from the product plan)

- Exported JSON matches **per-family** v2 structures and field names.
- **Field crush** is reduced: quantities and money are parsed into **typed columns** instead of living only inside free text (especially visible on v2 `line_items`).
- **Reports** can compare **v2** empty critical-field rates **by family** against older baselines.

---

*End of report.*
