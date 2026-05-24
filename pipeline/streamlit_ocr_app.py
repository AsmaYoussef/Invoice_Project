"""
Invoice OCR Pipeline — v4.6
════════════════════════════
New in v4.6 vs v4.5:
  • CRITICAL FIX: accent-stripping in _normalize_h (é→e, è→e, etc.)
    'Désignation' was becoming 'd signation' → column never mapped.
    Now uses unicodedata.normalize('NFKD') before ASCII encoding.
    Fixes designation extraction for ALL document types.
  • avenir_medis.pdf supported:
    - Columns: Code | Qté | Désignation
    - Doc number 1890/2023 (NNN > 12 rule)
    - MF 01232662F/P/M/000 normalised
    - Total H.T from footer bottom zone

Still present from v4.5:
  • JSON SPLIT: *_data.json (clean) vs *_audit.json (debug)
  • MDN-PRF-2308139 Proforma number recognised
  • Proforma footer: total_brut_ht, remise_pct, total_ht, tva, tva_detail,
    transport, timbre_fiscal, total_ttc — all accurate
  • Pharmasud columns: Qte Cmde / Nb Crt / Date P / U crt all stored
  • Omnipharm columns: Code / Qté / Promotion / Désignation
  • Dynamic columns: only columns present in the document shown
  • Fournisseur name card always shown
  • Quantity / date / year validation guards
"""

import streamlit as st
import cv2, numpy as np, pytesseract, pdfplumber, fitz
import re, json, tempfile, os, unicodedata
import time as _time
from pathlib import Path
from PIL import Image
from copy import deepcopy
import spacy
from rapidfuzz import fuzz, process as fuzz_process
import dateparser
from datetime import datetime

# Streamlit runs scripts with sys.path rooted at the script folder (`pipeline/`),
# so importing modules from the repo root needs an explicit path add.
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from database_integration import InvoiceDBHandler

db_handler = InvoiceDBHandler()

def save_result_to_db(result: dict) -> str:
    """
    Call this only after your pipeline creates `result`.
    Returns the inserted invoice id as a string.
    """
    new_db_id = db_handler.save_extraction(result)
    return str(new_db_id)
try:
    from pipeline.client import ask_structured_json, is_vision_enabled
    from pipeline.ai.line_cleaner import apply_gemini_line_cleanup
    from pipeline.ai.structural_gate import (
        apply_structural_realignment_gate,
        apply_structural_snapshot_to_v2_payload,
        is_structural_gate_enabled,
    )
except ImportError:
    try:
        from client import ask_structured_json, is_vision_enabled
        from ai.line_cleaner import apply_gemini_line_cleanup
        from ai.structural_gate import (
            apply_structural_realignment_gate,
            apply_structural_snapshot_to_v2_payload,
            is_structural_gate_enabled,
        )
    except Exception:
        ask_structured_json = None

        def is_vision_enabled():
            return False

        def apply_gemini_line_cleanup(lines, page_assets, **kwargs):
            return lines

        def apply_structural_realignment_gate(lines, page_assets, **kwargs):
            return lines, {"ok": False, "status": "unavailable"}, None

        def apply_structural_snapshot_to_v2_payload(v2_payload, snapshot, original_lines):
            return v2_payload

        def is_structural_gate_enabled():
            return False

try:
    from pipeline.ocr_line_clean import (
        apply_designation_cleanup_only,
        apply_local_designation_cleanup,
        extract_and_lock_quantite_only,
        line_has_quantite,
        lock_quantite,
        process_line_extract_then_clean,
        recover_lines_quantites_from_raw,
        _row_txt_has_qty_after_code,
    )
except ImportError:
    try:
        from ocr_line_clean import (
            apply_designation_cleanup_only,
            apply_local_designation_cleanup,
            extract_and_lock_quantite_only,
            line_has_quantite,
            lock_quantite,
            process_line_extract_then_clean,
            recover_lines_quantites_from_raw,
            _row_txt_has_qty_after_code,
        )
    except Exception:
        def recover_lines_quantites_from_raw(lines, **kwargs):
            return lines

        def apply_local_designation_cleanup(lines):
            return lines

        def apply_designation_cleanup_only(lines):
            return lines

        def process_line_extract_then_clean(item):
            return item

        def extract_and_lock_quantite_only(item):
            return item

        def lock_quantite(row, qty, **kwargs):
            return row

        def line_has_quantite(item):
            q = item.get("quantite")
            if q in (None, "", 0):
                return False
            try:
                return float(q) > 0
            except (TypeError, ValueError):
                return False

        def _row_txt_has_qty_after_code(raw_line, code):
            return False

try:
    from vendor_profiles import detect_invoice_family, get_profile_hints, merge_header_aliases
except Exception:
    def detect_invoice_family(*_args, **_kwargs):
        return "unknown"

    def get_profile_hints(*_args, **_kwargs):
        return {}

    def merge_header_aliases(base_aliases, _profile_hints):
        return base_aliases

try:
    from ai.resolver import resolve_ambiguous_fields
except Exception:
    def resolve_ambiguous_fields(*_args, **_kwargs):
        return {
            "ok": False,
            "status": "resolver_unavailable",
            "resolved": {},
            "raw": {},
            "accepted_line_item_hints": [],
            "line_item_hints": [],
        }

try:
    from v2_build import (
        build_v2_payload,
        collect_v2_gap_line_targets,
        merge_v2_quantities_into_product_lines,
        merge_v2_resolver_hints,
        mirror_v2_body_snapshot,
    )
except Exception:
    def build_v2_payload(_document_payload, _body_text, _invoice_family):
        return {"schema_version": 2, "invoice_family": "unknown", "document_metadata": {}, "line_items": []}

    def mirror_v2_body_snapshot(payload):
        return payload

    def collect_v2_gap_line_targets(*_a, **_k):
        return []

    def merge_v2_resolver_hints(payload, *_a, **_k):
        return payload

    def merge_v2_quantities_into_product_lines(legacy_lines, _v2_payload):
        return legacy_lines

try:
    from line_items_utils import legacy_line_merge_key
except Exception:

    def legacy_line_merge_key(item):
        c = str(item.get("code") or "").strip().upper()
        return (c, "", "", str(item.get("designation") or "")[:120], str(item.get("_row_txt") or "")[:140])

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if __name__ == '__main__':
    # ═══════════════════════════════════════════════════════════════
    # PAGE CONFIG
    # ═══════════════════════════════════════════════════════════════
    st.set_page_config(page_title="Invoice OCR Pipeline", page_icon="🔬",
                       layout="wide", initial_sidebar_state="expanded")
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;600;700&display=swap');
    html,body,[class*="css"]{font-family:'Syne',sans-serif;}
    code,.stCode,pre{font-family:'JetBrains Mono',monospace!important;}
    .stApp{background:#0f1117;color:#e8e8e2;}
    h1{font-family:'Syne';font-weight:700;letter-spacing:-1px;color:#f0f0ea;}
    h2,h3{font-family:'Syne';font-weight:600;color:#d4d4ce;}
    .info-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px;}
    .metric-card{background:#1a1d26;border:1px solid #2a2d3a;border-radius:8px;padding:14px 16px 12px;position:relative;min-height:72px;}
    .addr-card{grid-column:1/-1;}
    .metric-label{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;}
    .metric-value{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600;color:#7ee8a2;word-break:break-word;}
    .metric-value.addr-val{color:#7ec8e8;font-size:12px;}
    .metric-value.warn-val{color:#e8c87e;}
    .metric-value.empty-val{color:#333849;font-style:italic;}
    .conf-badge{position:absolute;top:10px;right:10px;font-family:'JetBrains Mono',monospace;font-size:9px;padding:2px 6px;border-radius:6px;font-weight:600;}
    .cb-high{background:#1a3a2a;color:#7ee8a2;border:1px solid #2a5a3a;}
    .cb-medium{background:#3a3a1a;color:#e8e87e;border:1px solid #5a5a2a;}
    .cb-low{background:#3a1a1a;color:#e87e7e;border:1px solid #5a2a2a;}
    .conf-hint{font-size:11px;color:#445;margin-bottom:12px;font-family:'JetBrains Mono';}
    .tag-bc{background:#1a3a2a;color:#7ee8a2;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a5a3a;}
    .tag-proforma{background:#1a2a3a;color:#7ec8e8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a4a5a;}
    .tag-facture{background:#3a2a1a;color:#e8c87e;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #5a4a2a;}
    .tag-stat{background:#2a1a3a;color:#c87ee8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #4a2a5a;}
    div[data-testid="stSidebar"]{background:#13151f;border-right:1px solid #1e2130;}
    .stButton>button{background:#7ee8a2;color:#0f1117;border:none;font-family:'Syne';font-weight:700;letter-spacing:0.5px;padding:10px 28px;border-radius:6px;width:100%;transition:all 0.2s;}
    .stButton>button:hover{background:#a0f0b8;transform:translateY(-1px);}
    .raw-text{background:#1a1d26;border:1px solid #2a2d3a;border-radius:8px;padding:16px;font-family:'JetBrains Mono';font-size:11px;color:#b0b0a8;max-height:400px;overflow-y:auto;white-space:pre-wrap;}
    .table-container{overflow-x:auto;}
    table{width:100%;border-collapse:collapse;font-size:12px;font-family:'JetBrains Mono';}
    th{background:#1e2130;color:#7ee8a2;padding:8px 12px;text-align:left;border-bottom:1px solid #2a2d3a;font-weight:600;}
    td{padding:7px 12px;border-bottom:1px solid #1e2130;color:#c8c8c2;vertical-align:top;}
    tr:hover td{background:#1a1d26;}
    .page-label{font-family:'Syne';font-size:12px;color:#555;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px 0;}
    .warn-box{background:#2a1f0a;border:1px solid #5a3a0a;border-radius:8px;padding:10px 16px;margin:8px 0;font-size:12px;color:#e8c87e;}
    .warn-box ul{margin:4px 0 0 16px;padding:0;}
    .pl-wrap{background:#0d0f17;border:1px solid #1e2130;border-radius:10px;padding:14px 16px;margin-bottom:12px;}
    .pl-title{font-family:'Syne';font-size:11px;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;}
    .pl-step{display:flex;align-items:flex-start;gap:10px;padding:7px 0;border-bottom:1px solid #141720;}
    .pl-step:last-child{border-bottom:none;}
    .pl-icon{font-size:13px;flex-shrink:0;width:18px;text-align:center;margin-top:1px;}
    .pl-info{flex:1;min-width:0;}
    .pl-name{font-family:'Syne';font-size:12px;}
    .pl-detail{font-family:'JetBrains Mono';font-size:10px;color:#445;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .pl-time{font-family:'JetBrains Mono';font-size:10px;color:#445;flex-shrink:0;padding-left:8px;align-self:center;}
    .s-pending .pl-name{color:#383c50;}.s-running .pl-name{color:#7ee8a2;}
    .s-done .pl-name{color:#c8c8c2;}.s-skip .pl-name{color:#333849;font-style:italic;}
    .s-warn .pl-name{color:#e8c87e;}
    </style>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# PIPELINE LOG
# ═══════════════════════════════════════════════════════════════
_STEPS=[("load","📂","Load file"),("detect","🔍","Detect PDF type"),
        ("preprocess","🧹","Preprocess image(s)"),("ocr","🔤","OCR text extraction"),
        ("pdfplumber","📊","pdfplumber tables"),("regex","🔎","Regex baseline extraction"),
        ("nlp","🧠","NLP enrichment"),("products","📦","Product line extraction"),
        ("done","✅","Pipeline complete")]

def _log_init():
    st.session_state["_pl"]={k:{"status":"pending","detail":"","t":""} for k,*_ in _STEPS}

def _log_set(key,status,detail="",t0=0.0):
    if "_pl" not in st.session_state: _log_init()
    elapsed=""
    if status=="done" and t0:
        ms=int((_time.time()-t0)*1000)
        elapsed=f"{ms}ms" if ms<1000 else f"{ms/1000:.1f}s"
    st.session_state["_pl"][key]={"status":status,"detail":detail,"t":elapsed}

def _log_render(ph):
    if "_pl" not in st.session_state: return
    pl=st.session_state["_pl"]
    icons={"pending":"○","running":"⏳","done":"✓","skip":"–","warn":"⚠"}
    html="<div class='pl-wrap'><div class='pl-title'>⚡ Pipeline</div>"
    for key,_,label in _STEPS:
        s=pl.get(key,{"status":"pending","detail":"","t":""})
        st_=s["status"]
        html+=(f"<div class='pl-step s-{st_}'><span class='pl-icon'>{icons.get(st_,'○')}</span>"
               f"<div class='pl-info'><div class='pl-name'>{label}</div>"
               +(f"<div class='pl-detail'>{s['detail']}</div>" if s['detail'] else "")
               +"</div>"+(f"<span class='pl-time'>{s['t']}</span>" if s['t'] else "")+"</div>")
    html+="</div>"
    ph.markdown(html,unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# NLP MODEL
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def load_nlp():
    for m in ("fr_core_news_sm","en_core_web_sm"):
        try: return spacy.load(m),m
        except OSError: pass
    return spacy.blank("fr"),"blank_fr"

# ═══════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════
def _to_float(s):
    if not s: return None
    s=str(s).strip(); s=re.sub(r'[^\d,.]','',s)
    if not s: return None
    if ',' in s and '.' in s:
        s=s.replace(',','') if s.rfind('.')>s.rfind(',') else s.replace('.','').replace(',','.')
    elif ',' in s:
        p=s.split(',')
        s=s.replace(',','.') if len(p)==2 and len(p[1])<=3 else s.replace(',','')
    try: return round(float(s),3)
    except: return None

def _to_float_soft(v):
    try: return _to_float(str(v))
    except: return None

def _is_date_like(s):
    s=str(s or "").strip()
    if re.match(r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}$',s): return True
    if re.match(r'^\d{6,8}$',s): return True
    return False

def _is_qty_valid(val,doc_type=""):
    if val is None: return False
    try: f=float(val)
    except: return False
    if f<=0 or f>500000: return False
    if 1900<=f<=2100: return False
    if ("proforma" in doc_type.lower() or "bon de commande" in doc_type.lower()) and f>50000:
        return False
    return True

def _is_qty_plausible(val,designation="",doc_type="",profile_key=""):
    if not _is_qty_valid(val,doc_type=doc_type):
        return False
    try: f=float(val)
    except: return False
    soft_cap=6000.0
    if "proforma" in str(doc_type or "").lower():
        soft_cap=10000.0
    if profile_key=="pharmasud_medis":
        soft_cap=5000.0
    if f>soft_cap:
        return False
    d=str(designation or "").lower()
    if d and re.search(r'(total|montant|ttc|ht)',d):
        return False
    return True

def _normalize_code_token(token):
    t=re.sub(r'[^A-Za-z0-9]','',str(token or "").upper())
    if not t:
        return ""
    t=t.replace("§","5")
    if t.startswith("FF"):
        t="PF"+t[2:]
    if t.startswith("PFO"):
        t="PF0"+t[3:]
    if t.startswith("PF"):
        head="PF"; tail=t[2:]
        tail=tail.replace("O","0").replace("I","1").replace("S","5").replace("B","8")
        return head+tail
    return t

def _clean_designation(s, quantite=None):
    try:
        from ocr_line_clean import sanitize_pharma_designation
        return sanitize_pharma_designation(str(s or ""), quantite)
    except ImportError:
        try:
            from pipeline.ocr_line_clean import sanitize_pharma_designation
            return sanitize_pharma_designation(str(s or ""), quantite)
        except ImportError:
            t = str(s or "").strip()
            t = re.sub(r'^[\-\*\!\~\=\+\#\|]+\s*', '', t).strip()
            t = re.sub(r'[\!\~\=\*\#\|]+$', '', t).strip()
            return re.sub(r'\s{2,}', ' ', t)

def _normalize_h(s):
    """FIX v4.6: NFKD unicode decomposition → ASCII so é→e, à→a, etc."""
    x=str(s or "").lower().strip()
    x=unicodedata.normalize('NFKD',x).encode('ascii','ignore').decode('ascii')
    x=re.sub(r'[^a-z0-9\s]',' ',x)
    x=re.sub(r'\s+',' ',x).strip()
    return x

def _coerce_line_item_value(field,value):
    raw=str(value or "").strip()
    if not raw:
        return ""
    if field in {"quantite","nb_crt","u_crt","prix_unitaire","montant"}:
        fv=_to_float_soft(raw)
        return fv if fv is not None else ""
    if field=="date_peremption":
        candidate=_sanitize_date_candidate(raw)
        norm,is_valid,_=_validate_date(candidate)
        return norm if is_valid else ""
    if field in {"code","code_article"}:
        return _normalize_code_token(raw)
    return raw

def _conf_badge_html(conf):
    pct=int(conf*100)
    cls="cb-high" if conf>=0.80 else "cb-medium" if conf>=0.55 else "cb-low"
    return f"<span class='conf-badge {cls}'>{pct}%</span>"

# ═══════════════════════════════════════════════════════════════
# FOURNISSEUR NAME
# ═══════════════════════════════════════════════════════════════
_COMPANY_KW=re.compile(
    r'\b(sarl|s\.a\.r\.l|s\.a\.|s\.a\b|spa|suarl|sas|ste\b|soci[eé]t[eé]|'
    r'repartition|r[eé]partiteur|grossiste|laboratoire|pharma|distribution|'
    r'm[eé]dicament|medical|import|export|commerce|groupe|holding|avenir|rekik)\b',
    re.IGNORECASE)

def extract_fournisseur_name(header_text):
    lines=[l.strip() for l in header_text.splitlines() if l.strip()]
    STOP=re.compile(
        r'^(route|rue|avenue|av\.|bd\.|date|tel|fax|m\.f|r\.c|page|code|email'
        r'|sfax|tunis|nabeul|sousse|sfax le|edite|prepare|medis\b)',re.IGNORECASE)
    for line in lines[:12]:
        if _COMPANY_KW.search(line) and not STOP.match(line):
            return line[:120].strip()
    for line in lines[:6]:
        if STOP.match(line): continue
        words=line.split()
        if len(words)>=2 and re.search(r'[A-Za-z]{3,}',line):
            if not re.match(r'^[A-Z]{2,4}\d',line) and not re.match(r'^\d',line):
                return line[:120].strip()
    return ""

# ═══════════════════════════════════════════════════════════════
# PROFORMA FOOTER
# ═══════════════════════════════════════════════════════════════
def extract_proforma_summary(text):
    result={}
    def _grab(pattern):
        m=re.search(pattern,text,re.IGNORECASE|re.DOTALL)
        if not m: return None
        nums=re.findall(r'\d[\d\s]*[,\.]\d{2,3}|\d{4,}',m.group(1))
        for raw in reversed(nums):
            v=_to_float(raw)
            if v is not None and v>=0: return v
        return None

    v=_grab(r'Total\s+Brut\s+HT\s*[:\s]+([\d\s,\.]+)')
    if v and v>100: result['total_brut_ht']=v
    m=re.search(r'Total\s+Remis[e\xe9]\s*[:\s]*\(?\s*(\d+[,\.]?\d*)\s*%?\s*\)?',text,re.I)
    if m:
        rv=_to_float(m.group(1))
        if rv is not None: result['remise_pct']=rv
    v=_grab(r'Total\s+Net\s+HT\s*[:\s]+([\d\s,\.]+)')
    if v and v>100: result['total_ht']=v
    for line in text.splitlines():
        ln=line.strip()
        if re.match(r'^TVA\s*[:\-]',ln,re.I):
            if re.search(r'\b(base|valeur|type)\b',ln,re.I): continue
            nums=re.findall(r'\d[\d\s]*[,\.]\d{2,3}',ln)
            for raw in reversed(nums):
                v2=_to_float(raw)
                if v2 and v2>50: result['tva']=v2; break
            if 'tva' in result: break
    tva_rows=[]
    for m in re.finditer(r'%\s+(\d+[,\.]\d{1,2})\s+([\d\s,\.]+)\s+([\d\s,\.]+)',text):
        rate=_to_float(m.group(1)); base=_to_float(re.sub(r'\s','',m.group(2))); val=_to_float(re.sub(r'\s','',m.group(3)))
        if rate is not None and base is not None and val is not None:
            tva_rows.append({"taux":rate,"base":base,"valeur":val})
    if tva_rows:
        result['tva_detail']=tva_rows
        if 'tva' not in result:
            total_tva=sum(r['valeur'] for r in tva_rows)
            if total_tva>0: result['tva']=round(total_tva,3)
    v=_grab(r'Transport\s*[:\s]+([\d\s,\.]+)')
    if v is not None: result['transport']=v
    v=_grab(r'Timbre\s+Fiscal\s*[:\s]+([\d\s,\.]+)')
    if v is not None: result['timbre_fiscal']=v
    v=_grab(r'Total\s+TT[Cc]\s*[:\s]+([\d\s,\.]+)')
    if v and v>100: result['total_ttc']=v
    return result

# ═══════════════════════════════════════════════════════════════
# COLUMN SCHEMA
# ═══════════════════════════════════════════════════════════════
_HEADER_SYNONYMS={
    "code_pct":["code pct","code ptc","pct","code produit","code","code article local","no article","ref"],
    "code_article":["code article","article code","ref article","reference article","code frs","code fourn"],
    "designation":["designation","designation article","designation produit","libelle","article","produit","desig"],
    "unit":["un","u","unite","unit","u n","conditionnement","cond"],
    "quantity":[
        "qte","qté","qty","quantite","quantité","quantity",
        "qte cmde","qtecmde","qte commande","qte ord","qté cmde",
        "quantite commande","quantité commandée","qte.",
    ],
    "nb_crt":["nb crt","nb  crt","nombre cartons","nb carton","nbre crt","nbcrt"],
    "unit_price":["prix unitaire","p u","prix u","pu","unit price","prix","pu ht"],
    "amount":["montant","mt","total ligne","amount","prix total","montant ht","mnt"],
    "date":["date p","date peremption","date limite","dluo","date exp","expiry","peremption"],
    "u_crt":["u crt","u  crt","unite carton","unites par carton","ucrt"],
    "promotion":["promotion","promo"],
}
_OUTPUT_ORDER=["code_pct","code_article","code","designation","unite","quantite","nb_crt","u_crt","prix_unitaire","montant","date_peremption","promotion"]
_COL_LABELS={"code_pct":"Code PCT","code_article":"Code Article","code":"Code (legacy)","designation":"Désignation","unite":"U.N.","quantite":"Qté","nb_crt":"Nb Crt","u_crt":"U Crt","prix_unitaire":"Prix Unitaire","montant":"Montant","date_peremption":"Date P","promotion":"Promotion"}
_CANON_TO_KEY={"code_pct":"code_pct","code_article":"code_article","designation":"designation","unit":"unite","quantity":"quantite","unit_price":"prix_unitaire","amount":"montant","date":"date_peremption","u_crt":"u_crt","nb_crt":"nb_crt","promotion":"promotion"}
_CANON_EXPECTED_KIND={
    "code_pct":"code","code_article":"code","designation":"text","unit":"unit","quantity":"integer","nb_crt":"integer","u_crt":"integer","unit_price":"money","amount":"money","date":"date","promotion":"text"
}

def _score_header(hn,syn):
    if not hn or not syn: return 0.0
    if hn==syn: return 1.0
    if syn in hn: return 0.85
    h=set(hn.split()); s=set(syn.split())
    inter=len(h&s); base=inter/max(1,len(s)) if inter else 0.0
    return base

def _cell_type_score(value,kind):
    txt=str(value or "").strip()
    if not txt: return 0.0
    if kind=="code":
        if re.fullmatch(r"[A-Z]{2,4}\d{2,12}|\d{4,6}", txt, re.I):
            return 1.0
        if re.fullmatch(r"\d{5,8}", txt):
            return 0.95
        return 0.2
    if kind=="integer":
        return 1.0 if re.fullmatch(r'\d{1,6}',txt) else 0.3 if _to_float_soft(txt) is not None else 0.0
    if kind=="money":
        return 1.0 if re.fullmatch(r'\d[\d\s]*[,\.]\d{2,3}',txt) else 0.5 if _to_float_soft(txt) is not None else 0.0
    if kind=="date":
        return 1.0 if _is_date_like(txt) else 0.0
    if kind=="unit":
        return 0.9 if re.fullmatch(r'[A-Za-z]{1,5}',txt) else 0.2
    if kind=="text":
        return 1.0 if re.search(r'[A-Za-z]{3,}',txt) else 0.2
    return 0.0

_BACKFILL_MIN_SCORE={"code_pct":0.55,"code_article":0.55}

def _map_headers(headers,sample_rows=None,profile_hints=None):
    col_map={}; dbg={}; candidates=[]
    sample_rows=sample_rows or []
    profile_hints=profile_hints or {}
    local_synonyms=merge_header_aliases(_HEADER_SYNONYMS,profile_hints)
    expected_order=profile_hints.get("expected_columns",[])
    for idx,h in enumerate(headers):
        hn=_normalize_h(h)
        per_col=[]
        for canon,syns in local_synonyms.items():
            best=max((_score_header(hn,_normalize_h(syn)) for syn in syns), default=0.0)
            if canon in expected_order:
                expected_pos=expected_order.index(canon)
                pos_bonus=max(0.0,0.08-(abs(expected_pos-idx)*0.02))
                best+=pos_bonus
            if sample_rows and best>0:
                kind=_CANON_EXPECTED_KIND.get(canon,"text")
                row_hits=0
                for row in sample_rows:
                    if idx<len(row):
                        row_hits+=_cell_type_score(row[idx],kind)
                best+=(min(0.12,row_hits/max(1,len(sample_rows))*0.04))
            per_col.append((canon,round(best,4)))
        per_col=sorted(per_col,key=lambda x:x[1],reverse=True)
        candidates.append({"index":idx,"header":h,"candidates":per_col[:4]})
    used=set()
    for entry in candidates:
        chosen=""
        chosen_score=0.0
        for canon,score in entry["candidates"]:
            if canon in used or score<0.42:
                continue
            chosen=canon
            chosen_score=score
            break
        dbg[entry["index"]]={"raw":entry["header"],"normalized":_normalize_h(entry["header"]),"canonical":chosen,"score":round(chosen_score,3),"candidates":entry["candidates"]}
        if chosen:
            col_map[chosen]=entry["index"]
            used.add(chosen)
    dbg["_profile_hint"]=profile_hints.get("profile_key","")
    dbg["_profile_confidence"]=profile_hints.get("confidence",0.0)
    return col_map,dbg

# ═══════════════════════════════════════════════════════════════
# TABLE LINE ITEM EXTRACTION
# ═══════════════════════════════════════════════════════════════
def _is_valid_item_code(token,doc_type="",row_text=""):
    t=str(token or "").strip().upper()
    if re.fullmatch(r'[A-Z]{2,4}\d{2,12}',t): return True
    if re.fullmatch(r'\d{4,6}',t): return True
    if re.fullmatch(r'[A-Z]{2,3}\d{3,}',t): return True
    if re.fullmatch(r'CAM\d{3,}',t): return True
    return False

def _realign_row(row,col_map):
    aligned={}
    consumed=set()
    for canon,idx in (col_map or {}).items():
        if idx is not None and idx<len(row):
            aligned[canon]=str(row[idx] or "").strip()
            consumed.add(idx)
    available=[(i,str(v or "").strip()) for i,v in enumerate(row) if i not in consumed and str(v or "").strip()]
    for canon in col_map:
        if str(aligned.get(canon,"")).strip():
            continue
        kind=_CANON_EXPECTED_KIND.get(canon,"text")
        best_idx=-1; best_score=0.0; best_val=""
        for i,val in available:
            sc=_cell_type_score(val,kind)
            if sc>best_score:
                best_score=sc; best_idx=i; best_val=val
        min_sc=_BACKFILL_MIN_SCORE.get(canon,0.72)
        if best_idx>=0 and best_score>=min_sc:
            aligned[canon]=best_val
            available=[(i,v) for i,v in available if i!=best_idx]
    aligned["_alignment_confidence"]=round(sum(_cell_type_score(aligned.get(c,""),_CANON_EXPECTED_KIND.get(c,"text")) for c in col_map)/max(1,len(col_map)),3)
    return aligned

def extract_line_items_from_tables(tables,doc_type="",profile_hints=None):
    items=[]; audit={"detected_headers":[],"column_map":{},"row_rejections":[],"row_alignment":[],"structured_item_count":0,"detected_schema":set()}
    seen=set()
    profile_key=str((profile_hints or {}).get("profile_key","") or "")
    for t_idx,table in enumerate(tables or []):
        if not table or len(table)<2: continue
        headers=[str(x or "").strip() for x in table[0]]
        col_map,dbg=_map_headers(headers,sample_rows=table[1:5],profile_hints=profile_hints)
        if not col_map: continue
        audit["detected_headers"].append({"table_index":t_idx,"headers":headers,"header_debug":dbg})
        audit["column_map"][str(t_idx)]={k:int(v) for k,v in col_map.items()}
        audit["detected_schema"].update(col_map.keys())
        prev_idx=-1
        last_pct=""
        for r_idx,row in enumerate(table[1:],start=1):
            if not any(str(c or "").strip() for c in row): continue
            row_map=_realign_row(row,col_map)
            audit["row_alignment"].append({"table_index":t_idx,"row_index":r_idx,"alignment_confidence":row_map.get("_alignment_confidence",0.0)})
            def get(canon):
                return str(row_map.get(canon,"") or "").strip()
            row_txt=" ".join(str(c or "") for c in row)
            pct_cell=get("code_pct")
            art_cell=get("code_article")
            inherited_pct=False
            if not pct_cell and art_cell and last_pct:
                pct_cell=last_pct
                inherited_pct=True
            code=pct_cell or art_cell
            if not code:
                m=re.search(r'\b([A-Z]{2,4}\d{2,12}|\d{4,8})\b',row_txt,re.I)
                code=m.group(1).upper() if m else ""
            designation=str(row_map.get("designation") or "").strip()
            if not _is_valid_item_code(code,doc_type=doc_type,row_text=row_txt):
                if prev_idx>=0 and designation and len(designation)>=3 and not re.search(r'\d[\d\s]*[,\.]\d{2,3}',designation):
                    prev_desc=str(items[prev_idx].get("designation","")).strip()
                    items[prev_idx]["designation"]=(prev_desc+" "+designation).strip() if prev_desc else designation
                    audit["row_rejections"].append({"table_index":t_idx,"row_index":r_idx,"reason":"continuation_merged"})
                else:
                    audit["row_rejections"].append({"table_index":t_idx,"row_index":r_idx,"reason":"invalid_code"})
                continue
            item={"code":code,"_field_source":{"code":"table_structured"},"_field_confidence":{"code":0.95}}
            if pct_cell:
                item["code_pct"]=pct_cell
                item["_field_source"]["code_pct"]="inherited_pct" if inherited_pct else "table_structured"
                item["_field_confidence"]["code_pct"]=0.65 if inherited_pct else 0.92
            if art_cell:
                item["code_article"]=art_cell
                item["_field_source"]["code_article"]="table_structured"
                item["_field_confidence"]["code_article"]=0.9
            if designation and len(designation) >= 2:
                item["designation"] = designation
            else:
                tail = re.sub(r"^\s*" + re.escape(str(code)) + r"\b", "", row_txt, flags=re.I).strip()
                if len(tail) >= 3:
                    item["designation"] = tail
            if item.get("designation"):
                item["_field_source"]["designation"] = "table_structured"
                item["_field_confidence"]["designation"] = 0.85
            un=get("unit")
            if un: item["unite"]=un
            raw_qty=get("quantity")
            if raw_qty and not _is_date_like(raw_qty):
                q=_to_float_soft(raw_qty)
                if _is_qty_plausible(q,designation=item.get("designation",""),doc_type=doc_type,profile_key=profile_key):
                    item=lock_quantite(item, q, source="table_structured", confidence=0.88)
                else: audit["row_rejections"].append({"table_index":t_idx,"row_index":r_idx,"code":code,"reason":"invalid_qty","raw_qty":raw_qty})
            if "nb_crt" in col_map:
                raw_nb=get("nb_crt")
                if raw_nb and not _is_date_like(raw_nb):
                    nb=_to_float_soft(raw_nb)
                    if nb and 0<nb<100000: item["nb_crt"]=nb; item["_field_source"]["nb_crt"]="table_structured"; item["_field_confidence"]["nb_crt"]=0.84
            if "u_crt" in col_map:
                raw_uc=get("u_crt")
                if raw_uc:
                    uc=_to_float_soft(raw_uc)
                    if uc and 0<uc<100000: item["u_crt"]=uc; item["_field_source"]["u_crt"]="table_structured"; item["_field_confidence"]["u_crt"]=0.84
            if "date" in col_map:
                raw_dt=get("date")
                if raw_dt: item["date_peremption"]=raw_dt; item["_field_source"]["date_peremption"]="table_structured"; item["_field_confidence"]["date_peremption"]=0.8
            if "promotion" in col_map:
                promo=get("promotion")
                if promo: item["promotion"]=promo; item["_field_source"]["promotion"]="table_structured"; item["_field_confidence"]["promotion"]=0.8
            pu=_to_float_soft(get("unit_price")); mt=_to_float_soft(get("amount"))
            if pu and pu>0: item["prix_unitaire"]=pu; item["_field_source"]["prix_unitaire"]="table_structured"; item["_field_confidence"]["prix_unitaire"]=0.9
            if mt and mt>0: item["montant"]=mt; item["_field_source"]["montant"]="table_structured"; item["_field_confidence"]["montant"]=0.9
            item["_row_txt"] = row_txt
            row_key = legacy_line_merge_key(item)
            if row_key in seen:
                audit["row_rejections"].append({"table_index":t_idx,"row_index":r_idx,"reason":"duplicate_row_key"})
                continue
            seen.add(row_key)
            items.append(item)
            prev_idx = len(items) - 1
            src_row_pct=str(row_map.get("code_pct") or "").strip()
            if src_row_pct:
                last_pct=src_row_pct
    audit["structured_item_count"]=len(items)
    return items,audit

def merge_line_items(primary,fallback):
    merged=[]
    fb_list=[deepcopy(x) for x in (fallback or [])]
    used_fb=[False]*len(fb_list)

    def _pick_fallback(p):
        pk=legacy_line_merge_key(p)
        for i,x in enumerate(fb_list):
            if used_fb[i]:
                continue
            if legacy_line_merge_key(x)==pk:
                return i
        pc=str(p.get("code") or "").strip().upper()
        if not pc:
            return None
        for i,x in enumerate(fb_list):
            if used_fb[i]:
                continue
            if str(x.get("code") or "").strip().upper()==pc:
                return i
        return None

    for p in primary or []:
        idx=_pick_fallback(p)
        base=deepcopy(fb_list[idx]) if idx is not None else {}
        if idx is not None:
            used_fb[idx]=True
        p_src=p.get("_field_source",{}); p_conf=p.get("_field_confidence",{})
        b_src=base.get("_field_source",{}); b_conf=base.get("_field_confidence",{})
        keys=set(base.keys())|set(p.keys())
        for k in keys:
            if k.startswith("_"):
                continue
            p_v=p.get(k,None); b_v=base.get(k,None)
            p_score=float(p_conf.get(k,0.7 if str(p_v or "").strip() else 0.0))
            b_score=float(b_conf.get(k,0.65 if str(b_v or "").strip() else 0.0))
            if str(p_v or "").strip() and (not str(b_v or "").strip() or p_score>=b_score):
                base[k]=p_v; b_src[k]=p_src.get(k,"primary"); b_conf[k]=p_score
            elif str(b_v or "").strip():
                base[k]=b_v; b_src[k]=b_src.get(k,"fallback"); b_conf[k]=b_score
        base["_field_source"]=b_src
        base["_field_confidence"]=b_conf
        if idx is not None and not line_has_quantite(base):
            fb_row = fb_list[idx]
            fb_code = str(fb_row.get("code") or "").strip()
            fb_raw = str(fb_row.get("_row_txt") or "").strip()
            base_raw = str(base.get("_row_txt") or "").strip()
            if fb_raw and fb_code:
                fb_has_qty = _row_txt_has_qty_after_code(fb_raw, fb_code)
                base_has_qty = _row_txt_has_qty_after_code(base_raw, fb_code) if base_raw else False
                if fb_has_qty and (not base_raw or not base_has_qty or len(fb_raw) > len(base_raw)):
                    base["_row_txt"] = fb_raw
            if line_has_quantite(fb_row):
                fb_qty = fb_row.get("quantite")
                base = lock_quantite(
                    base,
                    fb_qty,
                    source=(fb_row.get("_field_source") or {}).get("quantite", "fallback_regex"),
                    confidence=float((fb_row.get("_field_confidence") or {}).get("quantite", 0.86)),
                )
                b_src["quantite"] = (fb_row.get("_field_source") or {}).get(
                    "quantite", "fallback_regex"
                )
                b_conf["quantite"] = float(
                    (fb_row.get("_field_confidence") or {}).get("quantite", 0.86)
                )
            elif fb_row.get("_quantite_locked"):
                base["_quantite_locked"] = True
                if fb_row.get("qty") not in (None, ""):
                    base["qty"] = fb_row.get("qty")
        merged.append(base)
    for i,f in enumerate(fb_list):
        if used_fb[i]:
            continue
        merged.append(f)
    return merged

def normalize_line_items_for_json(items,detected_schema=None):
    if not items: return []
    always={"code","designation","quantite"}
    if detected_schema:
        allowed=always.copy()
        for canon in detected_schema:
            allowed.add(_CANON_TO_KEY.get(canon,canon))
        for item in items:
            for k,v in item.items():
                if k.startswith("_"):
                    continue
                if str(v).strip() not in("", "None"):
                    allowed.add(k)
    else:
        meta={"qty_source","qty_to_order","quantity"}
        present=set()
        for item in items:
            for k,v in item.items():
                if k in meta or k.startswith("_"): continue
                if str(v).strip() not in("","None"): present.add(k)
        allowed=present|always
    schema=[k for k in _OUTPUT_ORDER if k in allowed]
    for k in sorted(allowed):
        if k not in schema:
            schema.append(k)
    normalized=[]
    for item in items:
        row={k:item.get(k,"") for k in schema}
        if item.get("_field_source"):
            row["_field_source"]=item.get("_field_source",{})
        if item.get("_field_confidence"):
            row["_field_confidence"]=item.get("_field_confidence",{})
        if item.get("_row_txt"):
            row["_row_txt"]=item.get("_row_txt")
        if item.get("_quantite_locked"):
            row["_quantite_locked"]=item.get("_quantite_locked")
            row["quantite"]=item.get("quantite", row.get("quantite", ""))
        elif item.get("quantite") not in ("", None):
            row["quantite"]=item.get("quantite")
        qv=row.get("quantite","")
        if qv not in("",None) and not row.get("_quantite_locked"):
            try:
                qf=float(qv)
                if not _is_qty_plausible(qf,designation=row.get("designation","")): row["quantite"]=""
            except: row["quantite"]=""
        elif row.get("_quantite_locked") and qv not in ("", None):
            row["qty"] = row.get("qty", row.get("quantite"))
        normalized.append(row)
    return normalized

# ═══════════════════════════════════════════════════════════════
# DOCUMENT PAYLOAD
# ═══════════════════════════════════════════════════════════════
def build_document_payload(extracted_info):
    doc={"type":extracted_info.get("type","") or "","numero":extracted_info.get("numero","") or "","date":extracted_info.get("date","") or "","fournisseur_nom":extracted_info.get("fournisseur_nom","") or "","supplier_mf":extracted_info.get("supplier_mf","") or "","client_mf":extracted_info.get("client_mf","") or "","tel":extracted_info.get("tel","") or "","fax":extracted_info.get("fax","") or "","email":extracted_info.get("email","") or "","rc":extracted_info.get("rc","") or "","adresse":extracted_info.get("adresse","") or "","total_brut_ht":extracted_info.get("total_brut_ht",None),"remise_pct":extracted_info.get("remise_pct",None),"total_ht":extracted_info.get("total_ht",None),"tva":extracted_info.get("tva",None),"tva_detail":extracted_info.get("tva_detail",None),"transport":extracted_info.get("transport",None),"timbre_fiscal":extracted_info.get("timbre_fiscal",None),"total_ttc":extracted_info.get("total_ttc",None)}
    clean={}
    for k,v in doc.items():
        if v is None or v=="" or v==[]: continue
        clean[k]=v
    if "type" not in clean: clean["type"]=""
    return clean

def build_clean_json(document_payload,line_items):
    return {"document":document_payload,"line_items":line_items}

def build_audit_json(confidence,warnings_nlp,extraction_trace,table_extraction_audit,rejected_candidates,llm_validation,promotion_decisions,nlp_model_name,v2_llm_validation=None,structural_gate=None):
    audit={"confidence":confidence,"validation_warnings":warnings_nlp,"extraction_trace":extraction_trace,"table_extraction":table_extraction_audit,"rejected_candidates":rejected_candidates,"llm_validation":llm_validation,"promotion_decisions":promotion_decisions,"nlp_model":nlp_model_name}
    if v2_llm_validation is not None:
        audit["v2_llm_validation"]=v2_llm_validation
    if structural_gate is not None:
        audit["structural_gate"]=structural_gate
    return audit

# ═══════════════════════════════════════════════════════════════
# PREPROCESSING
# ═══════════════════════════════════════════════════════════════
def fix_rotation(img_bgr):
    try:
        gray_temp=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY)
        osd=pytesseract.image_to_osd(gray_temp,config="--psm 0 -c min_characters_to_try=5")
        angle_m=re.search(r"Rotate: (\d+)",osd); conf_m=re.search(r"Orientation confidence: ([\d\.]+)",osd)
        if angle_m and (float(conf_m.group(1)) if conf_m else 0)>=2.0:
            a=int(angle_m.group(1))
            if a==90: img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif a==180: img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_180)
            elif a==270: img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_90_CLOCKWISE)
    except: pass
    return img_bgr

def erase_colored_ink(img_bgr):
    hsv=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2HSV); gray=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY); result=img_bgr.copy()
    cm=cv2.inRange(hsv,np.array([0,25,40]),np.array([180,255,255])); k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5)); cm=cv2.dilate(cm,k,iterations=1)
    dark=(gray<100); result[(cm>0)&~dark]=[230,230,230]; result[(cm>0)&dark]=[0,0,0]
    return result

def binarize(gray):
    return cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,blockSize=25,C=8)

def remove_long_lines(binary):
    inv=cv2.bitwise_not(binary)
    h_k=cv2.getStructuringElement(cv2.MORPH_RECT,(80,1)); v_k=cv2.getStructuringElement(cv2.MORPH_RECT,(1,80))
    lm=cv2.add(cv2.morphologyEx(inv,cv2.MORPH_OPEN,h_k),cv2.morphologyEx(inv,cv2.MORPH_OPEN,v_k))
    nl,labels,stats,_=cv2.connectedComponentsWithStats(inv,8); tp=np.zeros_like(binary)
    for i in range(1,nl):
        bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]; ar=stats[i,cv2.CC_STAT_AREA]
        if 5<=bw<=120 and 5<=bh<=120 and 20<=ar<=8000: tp[labels==i]=255
    pk=cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)); tp=cv2.dilate(tp,pk,iterations=1)
    safe=cv2.bitwise_and(lm,cv2.bitwise_not(tp)); inv[safe>0]=0
    return cv2.bitwise_not(inv)

def stroke_cv(blob):
    ek=cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3)); cur,counts=blob.copy(),[]
    for _ in range(15):
        cur=cv2.erode(cur,ek); n=cv2.countNonZero(cur); counts.append(n)
        if n==0: break
    if len(counts)<2: return 999.0
    nz=np.array(counts,dtype=float); nz=nz[nz>0]
    return float(np.std(nz)/(np.mean(nz)+1e-5)) if len(nz) else 999.0

def build_keep_mask(binary):
    inv=cv2.bitwise_not(binary); nl,labels,stats,_=cv2.connectedComponentsWithStats(inv,8); km=np.zeros_like(binary)
    for i in range(1,nl):
        bx=stats[i,cv2.CC_STAT_LEFT]; by=stats[i,cv2.CC_STAT_TOP]; bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]
        area=stats[i,cv2.CC_STAT_AREA]; asp=max(bw,bh)/(min(bw,bh)+1e-5)
        if area<15 or area>15000: continue
        if asp>20 and area>200: continue
        if area<80: km[labels==i]=255; continue
        if area>3000:
            if area/(bw*bh+1e-5)>0.15: km[labels==i]=255
            continue
        if area/(bw*bh+1e-5)<0.12: continue
        blob=(labels[by:by+bh,bx:bx+bw]==i).astype(np.uint8)*255
        if stroke_cv(blob)<1.5: km[labels==i]=255
    return km

def enhance_kept_text(binary,km):
    ek=cv2.getStructuringElement(cv2.MORPH_RECT,(2,2)); km=cv2.dilate(km,ek,iterations=1)
    r=np.full_like(binary,255); r[km>0]=0
    return r

# ═══════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════
def ocr_full_page(img):
    return pytesseract.image_to_string(img,lang="fra+eng",config="--psm 6 --oem 1").strip()

def ocr_header_zone(img):
    h=img.shape[0]
    return pytesseract.image_to_string(img[:int(h*0.30),:],lang="fra+eng",config="--psm 4 --oem 1").strip()

def ocr_header_layout_lines(img):
    h,w=img.shape[:2]; header=img[:int(h*0.30),:]
    data=pytesseract.image_to_data(header,lang="fra+eng",config="--psm 4 --oem 1",output_type=pytesseract.Output.DICT)
    groups={}
    for i in range(len(data.get("text",[]))):
        txt=(data["text"][i] or "").strip()
        if not txt: continue
        key=(data["block_num"][i],data["par_num"][i],data["line_num"][i])
        left=int(data["left"][i]); wid=int(data["width"][i])
        g=groups.setdefault(key,{"parts":[],"left":left,"right":left+wid})
        g["parts"].append((left,txt)); g["left"]=min(g["left"],left); g["right"]=max(g["right"],left+wid)
    out=[]
    for g in groups.values():
        parts=[t for _,t in sorted(g["parts"],key=lambda x:x[0])]
        text_line=" ".join(parts).strip()
        if not text_line: continue
        x_center=(g["left"]+g["right"])/2.0
        out.append({"text":text_line,"x_norm":round(x_center/max(1,w),4),"left":g["left"],"right":g["right"]})
    return sorted(out,key=lambda x:(x["x_norm"],x["left"]))

def ocr_body_zone(img):
    h=img.shape[0]
    return pytesseract.image_to_string(img[int(h*0.22):int(h*0.92),:],lang="fra+eng",config="--psm 6 --oem 1").strip()

def clean_ocr_text(text):
    text=re.sub(r'\(cid:\d+\)','',text)
    text=re.sub(r'(?<!\w)([A-Z] ){3,}([A-Z])(?!\w)',lambda m:m.group(0).replace(' ',''),text)
    text=re.sub(r'(?<!\w)((?:[A-Z0-9] ){4,}[A-Z0-9])(?!\w)',lambda m:m.group(0).replace(' ',''),text)
    text=re.sub(r'(?<=\d)l(?=\d)','1',text); text=re.sub(r'(?<=\d)I(?=\d)','1',text)
    text=re.sub(r'(\d)°o',r'\g<1>0',text); text=re.sub(r'(\d)°(?=\d)',r'\g<1>0',text)
    text=re.sub(r'(?<=[A-Za-z0-9])\|(?=[A-Za-z0-9])',' ',text)
    text=re.sub(r'^\s*\|\s*$','',text,flags=re.MULTILINE)
    text=re.sub(r'(?i)\b(on de commande)\b','Bon de commande',text)
    text=re.sub(r'(?i)\b(on de livraison)\b','Bon de livraison',text)
    text=re.sub(r'[=~_—]{2,}',' ',text); text=re.sub(r'[ \t]{2,}',' ',text)
    lines=[]
    for line in text.splitlines():
        s=line.strip()
        if not s: lines.append(''); continue
        alnum=len(re.findall(r'[A-Za-z0-9]',s)); total=len(s)
        if alnum<3: continue
        if 1-alnum/(total+1e-5)>0.60: continue
        if not re.search(r'[A-Za-z]{3,}|\d',s): continue
        lines.append(s)
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
# PDFPLUMBER
# ═══════════════════════════════════════════════════════════════
def extract_tables_pdfplumber(pdf_path):
    strategies=[{"vertical_strategy":"lines","horizontal_strategy":"lines","intersection_tolerance":5},{"vertical_strategy":"lines","horizontal_strategy":"lines","intersection_tolerance":10},{"vertical_strategy":"text","horizontal_strategy":"lines","intersection_tolerance":5},{"vertical_strategy":"lines","horizontal_strategy":"text","intersection_tolerance":5},{"vertical_strategy":"text","horizontal_strategy":"text","intersection_tolerance":3}]
    all_tables=[]
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_tables=None
            for strat in strategies:
                try:
                    tbls=page.extract_tables(strat)
                    if tbls and any(len(t)>=3 for t in tbls): page_tables=tbls; break
                except: continue
            for table in (page_tables or []):
                clean=[]
                for row in table:
                    r=[str(c or '').strip() for c in row]
                    if any(c for c in r): clean.append(r)
                if clean: all_tables.append(clean)
    return all_tables

def detect_pdf_native(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        total=sum(len((p.extract_text() or '').strip()) for p in pdf.pages)
    return total>100

# ═══════════════════════════════════════════════════════════════
# REGEX BASELINE
# ═══════════════════════════════════════════════════════════════
DOC_TYPES={"Proforma":["proforma","b.c. interne","incoterms","date/heure livraison","bcm-"],"Bon de Commande":["bon de commande","commande fournisseur","bcn-","bc n°","bon de commande n°"],"Facture":["facture","invoice","facture numéro"],"Statistiques":["statistique","quantitatif des ventes","stat. ventes","quantité proposée","moyenne des ventes"],"Chiffre d'Affaires":["chiffre d'affaire","ventes et chiffre"]}

def detect_doc_type(text):
    tl=text.lower()
    for dtype,kws in DOC_TYPES.items():
        if any(k in tl for k in kws): return dtype
    return "Document"

_ADDR_ANCHOR=re.compile(r'\b(route|rue|avenue|av\.?|bd\.?|boulevard|cit[eé]|zone\s+ind|lot\s+n?[°o]?|lotissement|impasse|r[eé]sidence|quartier|km\s*\d|n[°o]\s*\d{1,4}\s+(?:rue|route|av))\b',re.IGNORECASE)

def extract_address(header_text):
    lines=[l.strip() for l in header_text.splitlines() if l.strip()]
    STOP=re.compile(r'^(tel|t[eé]l|fax|m\.?f|r\.?c|sfax|tunis|nabeul|sousse|monastir|date|page|code|email|pr[eé]par|[eé]dit[eé]|bon\s+de|facture|proforma|commande|medis|omnipharm|pharma|distribution|laboratoire|code\s+frs|code\s+pct|sfax\s+le|page\s+n)',re.IGNORECASE)
    for i,line in enumerate(lines):
        if not _ADDR_ANCHOR.search(line): continue
        block=[line]
        if i+1<len(lines):
            nxt=lines[i+1]
            if not STOP.match(nxt) and 4<len(nxt)<100: block.append(nxt)
        result=" — ".join(block)
        if re.search(r'\b(tel|t[eé]l|fax|email|@)\b',result,re.I): continue
        return result[:120].rstrip(" —")
    return ""

def _normalize_mf(raw):
    if not raw: return "",False
    cleaned=re.sub(r'[^A-Za-z0-9]','',raw).upper()
    m=re.match(r'^([0-9]{6,8})([A-Z])([A-Z])([A-Z])([0-9]{3})$',cleaned)
    if not m:
        cleaned2=cleaned.replace('O','0').replace('I','1').replace('L','1')
        m=re.match(r'^([0-9]{6,8})([A-Z])([A-Z])([A-Z])([0-9]{3})$',cleaned2)
        if m: cleaned=cleaned2
        else: return "",False
    d1,l1,l2,l3,d2=m.groups()
    if not(6<=len(d1)<=8 and len(d2)==3): return "",False
    return f"{d1}{l1}/{l2}/{l3}/{d2}",False

def _resolve_mf_roles(header_text,full_text,header_layout_lines=None):
    MF_PAT=re.compile(r'(?:m\.?\s*f\.?\s*[:\-]\s*)?([0-9A-Z]{6,})[/\\|\s\-]*([A-Z])[/\\|\s\-]*([A-Z])[/\\|\s\-]*([A-Z])[/\\|\s\-]*([0-9]{3,4})\b',re.IGNORECASE)
    candidates=[]
    for line in header_text.splitlines():
        ln=line.strip()
        for m in MF_PAT.finditer(ln):
            raw="".join(m.groups()); norm,_=_normalize_mf(raw)
            if not norm: continue
            at_start=bool(re.match(r'^\s*m\.?\s*f\.?\s*[:\-]',ln,re.I))
            rel_pos=m.start()/max(1,len(ln))
            candidates.append({"value":norm,"at_start":at_start,"rel_pos":rel_pos,"line":ln})
    if not candidates: return "","",[]
    supplier_cands=[c for c in candidates if c["at_start"] or c["rel_pos"]<0.45]
    client_cands=[c for c in candidates if not c["at_start"] and c["rel_pos"]>=0.45]
    supplier_mf=min(supplier_cands,key=lambda x:x["rel_pos"])["value"] if supplier_cands else ""
    client_mf=max(client_cands,key=lambda x:x["rel_pos"])["value"] if client_cands else ""
    if not client_mf and len(candidates)>=2:
        others=[c for c in candidates if c["value"]!=supplier_mf]
        if others: client_mf=max(others,key=lambda x:x["rel_pos"])["value"]
    return supplier_mf,client_mf,candidates

def _extract_numero(text):
    lines=[ln.strip() for ln in text.splitlines()]
    # 1. Line after heading
    for i,ln in enumerate(lines):
        if re.search(r'bon\s+de\s+commande|proforma|commande\b|facture',ln,re.I):
            for j in(i+1,i+2):
                if j>=len(lines): continue
                m=re.search(r'\b(\d{3,6}\s*/\s*\d{4})\b',lines[j])
                if m:
                    cand=re.sub(r'\s+','',m.group(1)); parts=cand.split('/')
                    if len(parts)==2 and int(parts[0])>12: return cand
                m=re.search(r'\b([A-Z]{2,8}-[A-Z]{2,8}-[A-Z0-9]{4,12})\b',lines[j],re.I)
                if m: return m.group(1).upper()
    # 2. Proforma N°
    m=re.search(r'PROFORMA\s+N[°o][:\s]*([A-Z0-9][\w\-]{4,25})',text,re.I)
    if m:
        cand=re.sub(r'\s+','',m.group(1)).strip(".,;:")
        if len(cand)>=4: return cand
    # 3. BCN/BCM
    for pat in(r'\b(BCN-[A-Z0-9]{2}-\d{4})\b',r'\b(BCM-[A-Z0-9]{2}-\d{4})\b',r'\b(BCM-\d{2}-\d{4})\b',r'\b(BCN\d{2}-\d{4})\b'):
        m=re.search(pat,text,re.IGNORECASE)
        if m: return m.group(1).upper()
    # 4. MDN-PRF style
    m=re.search(r'\b([A-Z]{2,8}-[A-Z]{2,8}-\d{6,12})\b',text,re.I)
    if m: return m.group(1).upper()
    # 5. Bon de commande N°
    m=re.search(r'Bon\s+de\s+commande\s+N[°o][°\.\s:]*\s*(\w[\w\-]{2,20})',text,re.I)
    if m:
        cand=re.sub(r'\s+','',m.group(1)).strip(".,;:")
        if len(cand)>=3: return cand
    # 6. Bare NNN/YYYY
    for m in re.finditer(r'\b(\d{3,6})\s*/\s*(\d{4})\b',text):
        d,y=m.group(1),m.group(2)
        if int(d)>12: return f"{d}/{y}"
    return ""

def extract_info(text,header_text,header_layout_lines=None):
    info={}; trace={"mf_candidates":[],"amount_candidates":{},"selected":{},"rejections":[]}
    info["type"]=detect_doc_type(text)
    numero=_extract_numero(text)
    if numero: info["numero"]=numero; trace["selected"]["numero"]=numero
    m=re.search(r'Date\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',text,re.I)
    if not m: m=re.search(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b',text)
    if m: info["date"]=m.group(1)
    supplier_mf,client_mf,mf_cands=_resolve_mf_roles(header_text,text,header_layout_lines)
    trace["mf_candidates"]=mf_cands[:8]
    if supplier_mf: info["supplier_mf"]=supplier_mf; info["matricule_fiscal"]=supplier_mf
    if client_mf: info["client_mf"]=client_mf
    fournisseur_nom=extract_fournisseur_name(header_text)
    if fournisseur_nom: info["fournisseur_nom"]=fournisseur_nom
    m=re.search(r'T[eé]l[:\.\s/]*(\+?\d[\d\s\.\-]{6,20}\d)',text,re.I)
    if m:
        digits=re.sub(r'\D','',m.group(1))
        if digits.startswith("216") and len(digits)>8: digits=digits[-8:]
        if len(digits) in(8,10,11): info["tel"]=digits
    m=re.search(r'Fax[:\.\s]*([\d][\d\s\.\-]{6,20}\d)',text,re.I)
    if m:
        digits=re.sub(r'\D','',m.group(1))
        if len(digits) in(8,10,11): info["fax"]=digits
    m=re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}',text)
    if m: info["email"]=m.group(0)
    m=re.search(r'R\.?C\.?\s*[:\-]?\s*([A-Z][A-Z0-9]{5,14})',text,re.I)
    if m: info["rc"]=m.group(1)
    addr=extract_address(header_text)
    if addr: info["adresse"]=addr
    return {k:v for k,v in info.items() if v},trace

def _extract_totals(all_full_texts,info,doc_type):
    result=dict(info); full="\n".join(all_full_texts)
    if "proforma" in doc_type.lower():
        summary=extract_proforma_summary(full)
        result.update({k:v for k,v in summary.items() if v is not None})
        return result
    _NUM=re.compile(r'\d[\d\s]*[,\.]\d{2,3}|\d{4,}')
    def _first_val(line,minimum=500.0):
        for raw in _NUM.findall(line):
            v=_to_float(raw)
            if v and v>=minimum and not(1900<=v<=2100): return v
        return None
    bottom_lines=[]
    for pg in all_full_texts:
        plines=[l for l in pg.splitlines() if l.strip()]
        bottom_lines.extend(plines[-80:])
    for ln in bottom_lines:
        s=ln.strip()
        if not s: continue
        if "total_ht" not in result and re.match(r'^(Total\s+Net\s+HT|Total\s+HT|Montant\s+HT|Total\s+H\.T)',s,re.I):
            v=_first_val(s,500)
            if v: result["total_ht"]=v
        if "tva" not in result and re.match(r'^TVA\s*[:\-]',s,re.I):
            if not re.search(r'\b(base|valeur|type)\b',s,re.I):
                v=_first_val(s,100)
                if v: result["tva"]=v
        if "total_ttc" not in result and re.match(r'^Total\s+TT?C|^Net\s+[àa]\s+payer',s,re.I):
            v=_first_val(s,500)
            if v: result["total_ttc"]=v
    return result

_VENDOR_ROW_GRAMMARS={
    "pharmasud_medis":[
        re.compile(r'^(?P<designation>.+?)\s*[|]\s*(?P<quantite>\d{1,5})\s*[|]\s*(?P<date_peremption>[0-9OIlS]{2}[\/\-.][0-9OIlS]{2}[\/\-.][0-9OIlS]{4})\s*[|]?\s*(?P<nb_crt>\d{1,5})?\s*$',re.I),
        re.compile(r'^(?P<designation>.+?)\s+(?P<quantite>\d{2,5})\s+(?P<date_peremption>[0-9OIlS]{2}[\/\-.][0-9OIlS]{2}[\/\-.][0-9OIlS]{4})\s*(?P<nb_crt>\d{1,5})?$',re.I),
    ],
    "omnipharm_medis":[
        re.compile(r'^(?P<quantite>\d{1,5})\s+(?P<designation>.+)$',re.I),
    ],
    "avenir_medis":[
        re.compile(
            r'^(?P<quantite>\d{1,5})\s+(?:[Xx×]\s*)?(?P<designation>.+)$',
            re.I,
        ),
        re.compile(r'^(?P<quantite>\d{1,5})\s+(?P<designation>.+)$', re.I),
    ],
    "modele_proforma":[
        re.compile(r'^(?P<code_article>[A-Z0-9]{7,14})\s*[-]?\s*(?P<designation>.+?)\s+(?P<quantite>\d{1,5}(?:[,.]\d{1,3})?)\s*$',re.I),
        re.compile(r'^(?P<designation>.+?)\s+(?P<quantite>\d{1,5}(?:[,.]\d{1,3})?)\s*$',re.I),
    ],
}

def _sanitize_date_candidate(raw):
    txt=str(raw or "").strip()
    if not txt:
        return ""
    txt=txt.replace("O","0").replace("I","1").replace("l","1").replace("S","5")
    txt=txt.replace(".", "/").replace("-", "/")
    return txt

def _parse_with_vendor_grammars(rest,profile_key=""):
    grammars=_VENDOR_ROW_GRAMMARS.get(profile_key,[])
    for g in grammars:
        m=g.match(rest)
        if not m:
            continue
        payload={k:str(v).strip() for k,v in m.groupdict().items() if v is not None and str(v).strip()}
        payload["_confidence"]=0.84
        return payload
    return {}

def _recover_fields_from_designation(item,doc_type="",profile_key=""):
    try:
        from ocr_line_clean import recover_line_quantity
        item = recover_line_quantity(item)
    except ImportError:
        try:
            from pipeline.ocr_line_clean import recover_line_quantity
            item = recover_line_quantity(item)
        except ImportError:
            pass
    designation=str(item.get("designation","") or "").strip()
    if not designation:
        return item
    d=designation
    if not item.get("quantite"):
        try:
            from ocr_line_clean import extract_qty_from_text_segment
        except ImportError:
            from pipeline.ocr_line_clean import extract_qty_from_text_segment
        qty_s, remain = extract_qty_from_text_segment(d)
        if qty_s:
            q = _to_float_soft(qty_s)
            if q and _is_qty_plausible(q, designation=remain, doc_type=doc_type, profile_key=profile_key):
                item["quantite"] = float(q)
                d = remain
                src = dict(item.get("_field_source") or {})
                fconf = dict(item.get("_field_confidence") or {})
                src["quantite"] = src.get("quantite") or "qty_recovered_designation"
                fconf["quantite"] = max(float(fconf.get("quantite") or 0), 0.84)
                item["_field_source"] = src
                item["_field_confidence"] = fconf
        else:
            m=re.match(r'^\s*(\d{1,5})(?:[,.]\d+)?\s+(.+)$',d)
            if m:
                q=_to_float_soft(m.group(1))
                if _is_qty_plausible(q,designation=m.group(2),doc_type=doc_type,profile_key=profile_key):
                    item["quantite"]=float(q)
                    d=m.group(2).strip()
    if not item.get("date_peremption"):
        dm=re.search(r'([0-9OIlS]{2}[\/\-.][0-9OIlS]{2}[\/\-.][0-9OIlS]{4})',d)
        if dm:
            candidate=_sanitize_date_candidate(dm.group(1))
            norm,is_valid,_=_validate_date(candidate)
            if is_valid:
                item["date_peremption"]=norm
                d=d.replace(dm.group(1)," ").strip()
    if not item.get("nb_crt"):
        nm=re.search(r'[| ]+(\d{1,4})\s*$',d)
        if nm:
            nb=_to_float_soft(nm.group(1))
            if nb and 0<nb<2000:
                item["nb_crt"]=nb
                d=d[:nm.start()].strip()
    # Final cleanup: strip noise separators while preserving medicine name.
    d=re.sub(r'\s*[|]+\s*',' ',d)
    d=re.sub(r'\s{2,}',' ',d).strip(" -_|")
    item["designation"]=d
    return item

def extract_product_lines(text,doc_type="",profile_hints=None):
    items=[]; seen=set()
    profile_hints=profile_hints or {}
    profile_key=str(profile_hints.get("profile_key","") or "")
    CODE_PCT=re.compile(r'^([A-Z]{2,4}\d{2,12}|\d{4,6})',re.IGNORECASE)
    CODE_ART=re.compile(r'^([A-Z]{2,4}\d{5,12})\b',re.IGNORECASE)
    for raw_line in text.splitlines():
        line=raw_line.strip()
        if not line: continue
        line=re.sub(r'^[\|.\-\s]+','',line).strip()
        if not line or len(line)<5: continue
        m_code=CODE_PCT.match(line)
        if not m_code: continue
        code=_normalize_code_token(m_code.group(1))
        if not _is_valid_item_code(code,doc_type=doc_type,row_text=line): continue
        rest=line[len(m_code.group(0)):].strip()
        if len(rest)<2: continue
        code_article=""
        m_art=CODE_ART.match(rest)
        if m_art:
            code_article=_normalize_code_token(m_art.group(1))
            rest=rest[len(m_art.group(1)):].strip().lstrip('-').strip()
        rest=re.sub(r"^[\|\.'\"()\[\]\-_\s]+",'',rest).strip()
        if not rest: continue
        parsed=_parse_with_vendor_grammars(rest,profile_key=profile_key)
        designation=parsed.get("designation","")
        qty=_to_float_soft(parsed.get("quantite","")) if parsed.get("quantite") else None
        if qty is None:
            try:
                from ocr_line_clean import extract_qty_from_text_segment
            except ImportError:
                from pipeline.ocr_line_clean import extract_qty_from_text_segment
            qty_s, rest_after = extract_qty_from_text_segment(rest)
            if qty_s:
                q_try = _to_float_soft(qty_s)
                if q_try and _is_qty_plausible(q_try, designation=rest_after, doc_type=doc_type, profile_key=profile_key):
                    qty = q_try
                    if not designation:
                        designation = rest_after
        if not designation:
            price_m=re.search(r'\b\d{1,6}[,\.]\d{2,3}\b',rest)
            text_part=rest[:price_m.start()].strip() if price_m else rest
            tokens=text_part.split(); num_tail=[]; i=len(tokens)-1
            while i>=0:
                t=tokens[i]
                if re.match(r'^\d{1,5}$',t) and not _is_date_like(t): num_tail.insert(0,int(t)); i-=1
                else: break
            designation=" ".join(tokens[:i+1]).strip()
            if qty is None and num_tail:
                cand=float(num_tail[0])
                if _is_qty_plausible(cand,designation=designation,doc_type=doc_type,profile_key=profile_key):
                    qty=cand
        if not designation or len(designation)<3: continue
        item={"code":code,"designation":designation,"_field_source":{"code":"ocr_fallback","designation":"ocr_fallback"},"_field_confidence":{"code":0.85,"designation":0.7}}
        cu=code.upper()
        if re.fullmatch(r"\d{4,8}", cu):
            item["code_pct"]=code
            item["_field_source"]["code_pct"]="ocr_fallback"
            item["_field_confidence"]["code_pct"]=0.86
        elif re.match(r"^PF", cu) or (len(cu) >= 9 and re.match(r"^[A-Z]{2,4}\d{5,12}$", cu)):
            item["code_article"]=code
            item["_field_source"]["code_article"]="ocr_fallback"
            item["_field_confidence"]["code_article"]=0.82
            m6=re.search(r"\b(\d{5,8})\b", line)
            if m6:
                item["code_pct"]=m6.group(1)[:8]
                item["_field_source"]["code_pct"]="ocr_fallback"
                item["_field_confidence"]["code_pct"]=0.68
        item["code"]=str(item.get("code_pct") or item.get("code_article") or code).strip() or code
        if code_article and _is_valid_item_code(code_article,doc_type=doc_type,row_text=line):
            item["code_article"]=code_article
            item["_field_source"]["code_article"]="ocr_fallback"
            item["_field_confidence"]["code_article"]=0.72
        if qty is not None and _is_qty_plausible(qty,designation=designation,doc_type=doc_type,profile_key=profile_key):
            item=lock_quantite(item, qty, source="ocr_fallback", confidence=0.85)
        if parsed.get("date_peremption"):
            candidate=_sanitize_date_candidate(parsed.get("date_peremption"))
            norm,is_valid,_=_validate_date(candidate)
            if is_valid:
                item["date_peremption"]=norm
                item["_field_source"]["date_peremption"]="ocr_fallback"
                item["_field_confidence"]["date_peremption"]=0.7
        if parsed.get("nb_crt"):
            nb=_to_float_soft(parsed.get("nb_crt"))
            if nb and 0<nb<2000:
                item["nb_crt"]=nb
                item["_field_source"]["nb_crt"]="ocr_fallback"
                item["_field_confidence"]["nb_crt"]=0.7
        item["_row_txt"] = line
        if not item.get("date_peremption"):
            d=str(item.get("designation","") or "")
            dm=re.search(r'([0-9OIlS]{2}[\/\-.][0-9OIlS]{2}[\/\-.][0-9OIlS]{4})',d)
            if dm:
                candidate=_sanitize_date_candidate(dm.group(1))
                norm,is_valid,_=_validate_date(candidate)
                if is_valid:
                    item["date_peremption"]=norm
                    item["designation"]=d.replace(dm.group(1)," ").strip()
        item = extract_and_lock_quantite_only(item)
        if not item.get("designation"):
            continue
        mk=legacy_line_merge_key(item)
        if mk in seen:
            continue
        seen.add(mk)
        items.append(item)
    return items,[]

# ═══════════════════════════════════════════════════════════════
# NLP LAYER
# ═══════════════════════════════════════════════════════════════
_DOC_TYPE_LABELS={"Proforma":["proforma","bc interne","incoterms","pro forma"],"Bon de Commande":["bon de commande","commande fournisseur","bcn","bon commande"],"Facture":["facture","invoice","facture numero"],"Statistiques":["statistique","quantitatif des ventes","stat ventes"],"Chiffre d'Affaires":["chiffre affaire","ventes et chiffre"]}

def _fuzzy_doc_type(text):
    snippet=re.sub(r'[^\w\s]',' ',text[:400].lower())
    best_type,best_score="Document",0.0
    for dtype,labels in _DOC_TYPE_LABELS.items():
        for label in labels:
            score=fuzz.partial_ratio(label,snippet)/100.0
            if score>best_score: best_score=score; best_type=dtype
    return best_type,round(best_score,2)

def _validate_date(date_str):
    if not date_str: return date_str,False,"No date"
    parts=re.split(r'[/\-\.]',date_str.strip())
    if len(parts)==3:
        try:
            d,m=int(parts[0]),int(parts[1])
            if d>31: return date_str,False,f"Invalid day {d}"
            if m>12:
                if d<=12:
                    fixed=f"{parts[1]}/{parts[0]}/{parts[2]}"
                    return fixed,True,f"Day/month swapped → {fixed}"
                return date_str,False,f"Invalid month {m}"
        except ValueError: pass
    parsed=dateparser.parse(date_str,settings={"PREFER_DAY_OF_MONTH":"first","DATE_ORDER":"DMY","RETURN_AS_TIMEZONE_AWARE":False})
    if not parsed: return date_str,False,f"Cannot parse '{date_str}'"
    if parsed.year>datetime.now().year+1: return date_str,False,"Future date"
    return parsed.strftime("%d/%m/%Y"),True,""

def _spacy_extract(text,nlp):
    doc=nlp(text[:3000]); ents={"DATE":[],"MONEY":[],"ORG":[],"LOC":[],"PER":[]}
    for ent in doc.ents:
        if ent.label_ in ents: ents[ent.label_].append(ent.text.strip())
    return ents

def nlp_enrich(regex_info,text,header_text,nlp):
    enriched=dict(regex_info); confidence={}; warnings=[]
    nlp_type,type_conf=_fuzzy_doc_type(text)
    regex_type=regex_info.get("type","Document")
    if regex_type=="Document" and nlp_type!="Document": enriched["type"]=nlp_type; confidence["type"]=type_conf
    elif nlp_type==regex_type: confidence["type"]=max(type_conf,0.90)
    else:
        confidence["type"]=type_conf
        if type_conf>0.80 and nlp_type!="Document": enriched["type"]=nlp_type
    raw_date=regex_info.get("date","")
    if not raw_date:
        ents=_spacy_extract(text,nlp)
        for ed in ents.get("DATE",[]):
            if re.search(r'\d{4}|\d{1,2}[/\-\.]\d{1,2}',ed): raw_date=ed; break
    if raw_date:
        normed,is_valid,warn_msg=_validate_date(raw_date)
        if is_valid:
            enriched["date"]=normed; confidence["date"]=0.92 if normed!=raw_date else 0.95
            if normed!=raw_date: warnings.append(f"Date corrected: '{raw_date}' → '{normed}'")
        else: confidence["date"]=0.30; warnings.append(f"Date: {warn_msg}"); enriched["date"]=raw_date
    else: confidence["date"]=0.0
    for field in("total_ht","tva","total_ttc","total_brut_ht","transport","timbre_fiscal"):
        confidence[field]=0.90 if regex_info.get(field) is not None else 0.0
    numero=enriched.get("numero","")
    if numero:
        if re.match(r'^(BCN|BCM|FAC|PRO|CMD|INV)[\-/]\w{2}[\-/]\d{4}$',numero,re.I): confidence["numero"]=0.97
        elif re.match(r'^[A-Z]{2,8}-[A-Z]{2,8}-\d{4,12}$',numero): confidence["numero"]=0.95
        elif re.match(r'^\d{3,6}/\d{4}$',numero): confidence["numero"]=0.90
        else: confidence["numero"]=0.70
    else: confidence["numero"]=0.0
    for mf_key in("supplier_mf","client_mf","matricule_fiscal"):
        mf=enriched.get(mf_key,"")
        if mf:
            if re.match(r'^\d{6,8}[A-Z]/[A-Z]/[A-Z]/\d{3}$',mf): confidence[mf_key]=0.98
            else: confidence[mf_key]=0.55; warnings.append(f"{mf_key} unusual: '{mf}'")
        else: confidence[mf_key]=0.0
    tel=enriched.get("tel","")
    if tel:
        digs=re.sub(r'\D','',tel)
        confidence["tel"]=0.95 if len(digs)==8 else 0.80 if len(digs) in(10,11) else 0.50
    else: confidence["tel"]=0.0
    if enriched.get("email"): confidence["email"]=0.97 if re.match(r'^[\w\.\-]+@[\w\.\-]+\.\w{2,6}$',enriched["email"]) else 0.50
    if not enriched.get("adresse"):
        ents=_spacy_extract(text,nlp); locs=ents.get("LOC",[])
        if locs: enriched["adresse"]=" — ".join(locs[:2]); confidence["adresse"]=0.60
    else: confidence["adresse"]=0.75
    for key in enriched:
        if key not in confidence: confidence[key]=0.70
    return enriched,confidence,warnings

# ═══════════════════════════════════════════════════════════════
# PDF → IMAGE
# ═══════════════════════════════════════════════════════════════
def pdf_page_to_image(pdf_path,page_index,dpi=200):
    doc=fitz.open(pdf_path); page=doc[page_index]; mat=fitz.Matrix(dpi/72,dpi/72); pix=page.get_pixmap(matrix=mat,alpha=False)
    img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
    return cv2.cvtColor(img,cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)

def extract_invoice_from_file(
    file_path,
    *,
    original_filename=None,
    use_fix_rotation=True,
    use_erase_color=True,
    use_remove_lines=True,
    use_keep_mask=True,
    dpi_choice=200,
    split_zones=True,
    show_tables=True,
    show_products=True,
    use_nlp=True,
    include_debug_images=False,
):
    """
    Run the full OCR / extraction pipeline on a PDF or image path.
    Safe to import from FastAPI (no Streamlit UI). Mirrors sidebar defaults.
    """
    path = Path(file_path)
    display_name = original_filename or path.name
    is_pdf = path.suffix.lower() == ".pdf"
    nlp_model, nlp_model_name = load_nlp()
    tmp_path = str(path.resolve())

    if is_pdf:
        is_native = detect_pdf_native(tmp_path)
        doc_fitz = fitz.open(tmp_path)
        total_pages = len(doc_fitz)
        doc_fitz.close()
    else:
        is_native = False
        total_pages = 1

    all_header_texts = []
    all_body_texts = []
    all_full_texts = []
    all_orig_imgs = []
    all_clean_imgs = []
    all_header_clean_imgs = []
    all_header_layout_lines = []
    all_product_lines = []
    seen_line_keys = set()
    page_assets = []

    with open(tmp_path, "rb") as _bf:
        file_bytes = _bf.read()

    for page_i in range(total_pages):
        if is_pdf:
            img_bgr = pdf_page_to_image(tmp_path, page_i, dpi=dpi_choice)
        else:
            fb = np.frombuffer(file_bytes, dtype=np.uint8)
            img_bgr = cv2.imdecode(fb, 1)
            if img_bgr is None:
                raise ValueError(f"Could not decode image file: {display_name}")

        if include_debug_images:
            all_orig_imgs.append(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))

        work = img_bgr.copy()
        if use_fix_rotation:
            work = fix_rotation(work)
        if use_erase_color:
            work = erase_colored_ink(work)
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        binary = binarize(gray)
        header_binary = binary.copy()
        header_clean = enhance_kept_text(header_binary, build_keep_mask(header_binary)) if use_keep_mask else header_binary
        if use_remove_lines:
            binary = remove_long_lines(binary)
        clean = enhance_kept_text(binary, build_keep_mask(binary)) if use_keep_mask else binary

        if include_debug_images:
            all_clean_imgs.append(clean)
            all_header_clean_imgs.append(header_clean)

        if split_zones:
            h_text_soft = clean_ocr_text(ocr_header_zone(header_clean))
            h_text_std = clean_ocr_text(ocr_header_zone(clean))
            h_text = clean_ocr_text((h_text_soft + "\n" + h_text_std).strip())
            if page_i == 0:
                all_header_layout_lines = ocr_header_layout_lines(header_clean)
            b_text = clean_ocr_text(ocr_body_zone(clean))
            f_text = clean_ocr_text((h_text + "\n" + b_text).strip())
        else:
            f_text = clean_ocr_text(ocr_full_page(clean))
            h_text = b_text = f_text

        all_header_texts.append(h_text)
        all_body_texts.append(b_text)
        all_full_texts.append(f_text)

        if is_vision_enabled():
            page_assets.append(
                {
                    "image_rgb": cv2.cvtColor(work, cv2.COLOR_BGR2RGB),
                    "body_text": b_text,
                }
            )

        if show_products:
            page_doc_type = detect_doc_type((h_text or "") + "\n" + (b_text or ""))
            page_profile_hints = get_profile_hints(
                source_file=display_name,
                doc_type=page_doc_type,
                header_text=h_text,
                full_text=b_text,
            )
            page_items, _ = extract_product_lines(b_text, doc_type=page_doc_type, profile_hints=page_profile_hints)
            for item in page_items:
                code = item.get("code", "")
                probe = dict(item)
                probe["_row_txt"] = f"p{page_i}|{code}|{str(item.get('designation', ''))[:100]}"
                lk = legacy_line_merge_key(probe)
                if code and lk not in seen_line_keys:
                    seen_line_keys.add(lk)
                    all_product_lines.append(item)
                elif not code:
                    all_product_lines.append(item)

    combined_full = "\n\n".join(all_full_texts)
    combined_header = "\n\n".join(all_header_texts)
    predicted_doc_type = detect_doc_type(combined_full)
    profile_hints = get_profile_hints(
        source_file=display_name,
        doc_type=predicted_doc_type,
        header_text=combined_header,
        full_text=combined_full,
    )
    plumber_tables = []
    table_extraction_audit = {
        "detected_headers": [],
        "column_map": {},
        "row_rejections": [],
        "row_alignment": [],
        "structured_item_count": 0,
        "detected_schema": set(),
        "strategy": "fallback_regex_only",
        "profile_hint": profile_hints.get("profile_key", ""),
    }
    if is_pdf and is_native and show_tables:
        plumber_tables = extract_tables_pdfplumber(tmp_path)
    if plumber_tables:
        structured_items, table_extraction_audit = extract_line_items_from_tables(
            plumber_tables, doc_type=predicted_doc_type, profile_hints=profile_hints
        )
        if structured_items:
            all_product_lines = merge_line_items(structured_items, all_product_lines)
            table_extraction_audit["strategy"] = "structured_primary"

    invoice_family_early = detect_invoice_family(
        display_name, combined_header, combined_full, doc_type=predicted_doc_type
    )
    combined_body_early = "\n".join(all_body_texts) if all_body_texts else combined_full
    v2_body_snapshot = build_v2_payload(
        {"type": predicted_doc_type or ""},
        combined_body_early,
        invoice_family_early,
    )
    v2_body_snapshot = mirror_v2_body_snapshot(v2_body_snapshot)
    all_product_lines = merge_v2_quantities_into_product_lines(all_product_lines, v2_body_snapshot)
    try:
        all_product_lines = recover_lines_quantites_from_raw(
            all_product_lines, combined_body=combined_body_early
        )
    except Exception:
        pass

    structural_audit = {"ok": False, "status": "skipped", "rows_corrected": 0, "metadata_corrected": False}
    structural_snapshot = None
    structural_meta_stub = {
        "type": predicted_doc_type or "",
        "numero": "",
        "date": "",
        "fournisseur_nom": "",
    }
    if all_product_lines and page_assets and is_structural_gate_enabled():
        try:
            all_product_lines, structural_audit, structural_snapshot = apply_structural_realignment_gate(
                all_product_lines,
                page_assets,
                document_metadata=structural_meta_stub,
                doc_type=predicted_doc_type,
                invoice_family=invoice_family_early,
                header_text=combined_header,
                body_text=combined_body_early,
            )
        except Exception as exc:
            structural_audit = {
                "ok": False,
                "status": "error",
                "error": str(exc),
                "rows_corrected": 0,
                "metadata_corrected": False,
            }
    elif all_product_lines and page_assets and is_vision_enabled():
        import os as _os
        if _os.environ.get("GEMINI_LINE_CLEAN_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                all_product_lines = apply_gemini_line_cleanup(
                    all_product_lines,
                    page_assets,
                    doc_type=predicted_doc_type,
                    invoice_family=invoice_family_early,
                )
            except Exception:
                pass

    if all_product_lines:
        try:
            all_product_lines = recover_lines_quantites_from_raw(
                all_product_lines, combined_body=combined_body_early
            )
        except Exception:
            pass

    regex_info, extraction_trace = extract_info(combined_full, combined_header, all_header_layout_lines)
    regex_info = _extract_totals(all_full_texts, regex_info, predicted_doc_type)
    confidence = {}
    warnings_nlp = []
    extracted_info = regex_info
    if use_nlp:
        extracted_info, confidence, warnings_nlp = nlp_enrich(regex_info, combined_full, combined_header, nlp_model)
    else:
        pass

    ambiguous_doc_fields = [k for k, v in confidence.items() if isinstance(v, (int, float)) and v < 0.55]
    unresolved_line_items = []
    for item in all_product_lines:
        if not item.get("code"):
            continue
        if not item.get("quantite") and re.search(
            r"\d{2,5}|[0-9OIlS]{2}[\/\-.][0-9OIlS]{2}[\/\-.][0-9OIlS]{4}",
            str(item.get("designation", "")),
        ):
            unresolved_line_items.append(
                {"code": item.get("code"), "designation": item.get("designation", ""), "missing": ["quantite", "date_peremption"]}
            )

    should_use_llm = bool(ask_structured_json and (ambiguous_doc_fields or unresolved_line_items))
    if should_use_llm:
        llm_validation = resolve_ambiguous_fields(
            ask_json_fn=ask_structured_json,
            source_text=combined_full,
            candidate_payload={
                "document_type": extracted_info.get("type", ""),
                "known_fields": extracted_info,
                "field_confidence": confidence,
                "profile_hint": profile_hints,
                "ambiguous_fields": ambiguous_doc_fields,
                "unresolved_line_items": unresolved_line_items[:120],
            },
        )
    else:
        llm_validation = {"ok": False, "status": "skipped_no_low_confidence_targets", "resolved": {}, "accepted_line_item_hints": []}

    if llm_validation.get("ok"):
        for field, payload in llm_validation.get("resolved", {}).items():
            val = str(payload.get("value", "")).strip()
            if val:
                extracted_info[field] = val
                confidence[field] = max(float(confidence.get(field, 0.0)), float(payload.get("confidence", 0.0)))

    if structural_snapshot and structural_audit.get("ok"):
        gate_meta = structural_snapshot.get("document_metadata") or {}
        for key in ("fournisseur_nom", "type", "numero", "date"):
            val = str(gate_meta.get(key) or "").strip()
            if val:
                extracted_info[key] = val
                confidence[key] = max(float(confidence.get(key, 0.0)), 0.88)

    detected_schema = table_extraction_audit.get("detected_schema", set())

    if llm_validation.get("accepted_line_item_hints"):
        by_code = {str(i.get("code", "")).upper(): i for i in all_product_lines if i.get("code")}
        for hint in llm_validation.get("accepted_line_item_hints", []):
            code = str(hint.get("code", "")).upper()
            field = str(hint.get("field", "")).strip()
            if code not in by_code or not field:
                continue
            item = by_code[code]
            if str(item.get(field, "")).strip():
                continue
            coerced = _coerce_line_item_value(field, hint.get("value", ""))
            if coerced in ("", None):
                continue
            if field == "quantite" and not _is_qty_plausible(
                coerced,
                designation=item.get("designation", ""),
                doc_type=predicted_doc_type,
                profile_key=profile_hints.get("profile_key", ""),
            ):
                continue
            item[field] = coerced
            src = item.get("_field_source", {})
            conf = item.get("_field_confidence", {})
            src[field] = "ai_resolver"
            conf[field] = float(hint.get("confidence", 0.0))
            item["_field_source"] = src
            item["_field_confidence"] = conf

    document_payload = build_document_payload(extracted_info)
    invoice_family = detect_invoice_family(display_name, combined_header, combined_full, doc_type=predicted_doc_type)
    combined_body = "\n".join(all_body_texts) if all_body_texts else combined_full
    v2_payload = build_v2_payload(document_payload, combined_body, invoice_family)
    if structural_snapshot and structural_audit.get("ok"):
        v2_payload = apply_structural_snapshot_to_v2_payload(
            v2_payload,
            structural_snapshot,
            all_product_lines,
        )
    v2_gaps = collect_v2_gap_line_targets(invoice_family, v2_payload.get("line_items", []))
    v2_llm_validation = {"ok": False, "status": "skipped_no_v2_gaps", "accepted_line_item_hints": []}
    if ask_structured_json and v2_gaps:
        v2_llm_validation = resolve_ambiguous_fields(
            ask_json_fn=ask_structured_json,
            source_text=combined_full,
            candidate_payload={"task": "v2_gap_fill", "invoice_family": invoice_family, "v2_gap_lines": v2_gaps},
        )
    if v2_llm_validation.get("ok"):
        v2_payload = merge_v2_resolver_hints(v2_payload, v2_llm_validation.get("accepted_line_item_hints", []), combined_full)

    all_product_lines = merge_v2_quantities_into_product_lines(all_product_lines, v2_body_snapshot)
    try:
        all_product_lines = recover_lines_quantites_from_raw(
            all_product_lines, combined_body=combined_body
        )
    except Exception:
        pass
    try:
        all_product_lines = apply_designation_cleanup_only(all_product_lines)
    except Exception:
        pass

    gap_fill_audit = {"ok": False, "status": "skipped"}
    if all_product_lines and page_assets:
        try:
            from pipeline.ai.gap_filler import apply_vision_gap_fill, is_gap_filler_enabled
        except ImportError:
            try:
                from ai.gap_filler import apply_vision_gap_fill, is_gap_filler_enabled
            except ImportError:
                apply_vision_gap_fill = None
                is_gap_filler_enabled = lambda: False  # noqa: E731
        try:
            if apply_vision_gap_fill and is_gap_filler_enabled():
                all_product_lines, gap_fill_audit = apply_vision_gap_fill(
                    all_product_lines,
                    page_assets,
                    doc_type=predicted_doc_type,
                    invoice_family=invoice_family,
                )
        except Exception:
            pass

    all_product_lines = normalize_line_items_for_json(
        all_product_lines,
        detected_schema=detected_schema if detected_schema else None,
    )

    promotion_decisions = {
        "fields": {},
        "line_items": [],
        "llm_status": llm_validation.get("status", "unknown"),
        "invoice_family": invoice_family,
    }

    clean_payload = v2_payload
    audit_payload = build_audit_json(
        confidence,
        warnings_nlp,
        extraction_trace,
        table_extraction_audit,
        {},
        llm_validation,
        promotion_decisions,
        nlp_model_name,
        v2_llm_validation=v2_llm_validation,
        structural_gate=structural_audit,
    )

    db_result = {
        "header": {
            "doc_number": document_payload.get("numero") or document_payload.get("doc_number"),
            "doc_date": document_payload.get("date") or document_payload.get("doc_date"),
        },
        "totals": {
            "total_ht": document_payload.get("total_ht"),
            "total_tva": document_payload.get("tva"),
            "total_ttc": document_payload.get("total_ttc"),
        },
        "line_items": [
            {
                "designation": (li.get("designation") or li.get("raw_label") or ""),
                "quantity": li.get("quantite"),
                "unit_price_ht": (li.get("prix_unitaire") or li.get("prix_unitaire_ht") or li.get("unit_price_ht")),
            }
            for li in (all_product_lines or [])
        ],
    }

    out = {
        **db_result,
        "v2_export": clean_payload,
        "audit_payload": audit_payload,
        "document_payload": document_payload,
        "confidence": confidence,
        "warnings_nlp": warnings_nlp,
        "combined_full": combined_full,
        "extraction_trace": extraction_trace,
        "plumber_tables": plumber_tables,
        "all_product_lines": all_product_lines,
        "detected_schema": detected_schema,
        "total_pages": total_pages,
        "is_pdf": is_pdf,
        "is_native": is_native,
        "predicted_doc_type": predicted_doc_type,
        "invoice_family": invoice_family,
        "v2_payload": v2_payload,
        "nlp_model_name": nlp_model_name,
        "profile_hints": profile_hints,
        "table_extraction_audit": table_extraction_audit,
        "llm_validation": llm_validation,
        "v2_llm_validation": v2_llm_validation,
        "structural_audit": structural_audit,
    }
    if include_debug_images:
        out["all_orig_imgs"] = all_orig_imgs
        out["all_clean_imgs"] = all_clean_imgs
        out["all_header_texts"] = all_header_texts
        out["all_body_texts"] = all_body_texts
        out["all_full_texts"] = all_full_texts
    return out

# ═══════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════
def render_info_grid(fields,confidence,show_conf):
    html="<div class='info-grid'>"
    for label,key,value in fields:
        conf=confidence.get(key); is_empty=str(value) in("—","","None")
        badge=(_conf_badge_html(conf) if show_conf and conf is not None and not is_empty else "")
        val_cls=("empty-val" if is_empty else "warn-val" if(conf is not None and conf<0.55) else "")
        disp="—" if is_empty else str(value)
        html+=(f"<div class='metric-card'>{badge}<div class='metric-label'>{label}</div><div class='metric-value {val_cls}'>{disp}</div></div>")
    html+="</div>"
    st.markdown(html,unsafe_allow_html=True)

def render_product_table(items,detected_schema=None,doc_type=""):
    if not items: return
    present_keys=set()
    for item in items:
        for k,v in item.items():
            if str(v).strip() not in("","None","—","nan"): present_keys.add(k)
    if detected_schema:
        allowed={_CANON_TO_KEY.get(c,c) for c in detected_schema}|{"code","code_pct","code_article","designation"}
    else:
        allowed=present_keys|{"code","code_pct","code_article","designation"}
    schema=[k for k in _OUTPUT_ORDER if k in allowed and k in present_keys]
    if "code_pct" not in schema and "code" in present_keys:
        schema.insert(0,"code")
    if "designation" not in schema: schema.append("designation")
    tbl=("<div class='table-container'><table><thead><tr><th style='color:#555;width:32px'>#</th>")
    for k in schema: tbl+=f"<th>{_COL_LABELS.get(k,k)}</th>"
    tbl+="</tr></thead><tbody>"
    for i,item in enumerate(items,1):
        tbl+=f"<tr><td style='color:#555'>{i}</td>"
        for k in schema:
            val=item.get(k,"")
            if isinstance(val,float): val=f"{val:.0f}" if val==int(val) else f"{val:.3f}"
            if not str(val).strip() or str(val) in("None","nan"): val="—"
            style=""
            if k in("code","code_pct"): style=" style='color:#7ee8a2'"
            elif k=="code_article": style=" style='color:#7ec8e8'"
            elif k=="quantite": style=" style='text-align:right;color:#e8c87e'"
            elif k in("prix_unitaire","montant","nb_crt","u_crt"): style=" style='text-align:right'"
            tbl+=f"<td{style}>{val}</td>"
        tbl+="</tr>"
    tbl+="</tbody></table></div>"
    st.markdown(tbl,unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    with st.sidebar:
        st.markdown("## ⚙️ Options"); st.markdown("---")
        st.markdown("**Preprocessing**")
        use_fix_rotation=st.checkbox("Fix Rotation",value=True)
        use_erase_color=st.checkbox("Erase Colored Ink",value=True)
        use_remove_lines=st.checkbox("Remove Borders",value=True)
        use_keep_mask=st.checkbox("Blob Filter (CV)",value=True)
        st.markdown("---"); st.markdown("**OCR**")
        dpi_choice=st.radio("DPI",options=[150,200,300],index=1,help="200 ≈ 40% faster than 300")
        split_zones=st.checkbox("Split Header / Body OCR",value=True)
        show_raw=st.checkbox("Show Raw OCR Text",value=False)
        st.markdown("---"); st.markdown("**NLP**")
        use_nlp=st.checkbox("Enable NLP Enrichment",value=True)
        show_conf=st.checkbox("Show Confidence Scores",value=False,help="🟢≥80% reliable · 🟡55-79% · 🔴<55% likely wrong")
        show_warnings=st.checkbox("Show Validation Warnings",value=True)
        show_trace=st.checkbox("Show Extraction Trace",value=False)
        st.markdown("---"); st.markdown("**Output**")
        show_tables=st.checkbox("Show pdfplumber Tables",value=True)
        show_products=st.checkbox("Show Product Lines",value=True)
        show_json=st.checkbox("Show Clean JSON Preview",value=False)

    # ═══════════════════════════════════════════════════════════════
    # MAIN
    # ═══════════════════════════════════════════════════════════════
    st.markdown("# 🔬 Invoice OCR Pipeline")
    st.markdown("*Preprocessing → OCR → Regex → 🧠 NLP → Structured output*")
    st.markdown("---")

    nlp_model,nlp_model_name=load_nlp()
    with st.sidebar:
        st.markdown("---"); st.markdown("**NLP Model**")
        mc="#7ee8a2" if nlp_model_name!="blank_fr" else "#e8c87e"
        st.markdown(f"<span style='font-family:JetBrains Mono;font-size:11px;color:{mc}'>{'✓' if nlp_model_name!='blank_fr' else '⚠'} {nlp_model_name}</span>",unsafe_allow_html=True)
        if nlp_model_name=="blank_fr": st.caption("Install: `python -m spacy download fr_core_news_sm`")

    uploaded=st.file_uploader("Drop a PDF or image file",type=["pdf","png","jpg","jpeg"],label_visibility="collapsed")
    run_btn=st.button("▶  Run Pipeline",use_container_width=True)

    # Persist last extraction across reruns (button clicks)
    if "clean_payload" not in st.session_state:
        st.session_state["clean_payload"] = None
    if "audit_payload" not in st.session_state:
        st.session_state["audit_payload"] = None

    if not uploaded:
        st.markdown("""<div style='text-align:center;padding:60px 0;color:#444;'><div style='font-size:48px;margin-bottom:16px'>📄</div><div style='font-size:14px'>Upload a PDF or image to begin</div><div style='font-size:11px;color:#333;margin-top:8px'>Supports: Bon de Commande · Proforma · Facture · Statistiques</div></div>""",unsafe_allow_html=True)

    if uploaded and run_btn:
        _log_init(); _log_ph=st.empty(); _log_render(_log_ph)
        is_pdf=uploaded.type=="application/pdf"
        suffix=".pdf" if is_pdf else Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as tmp:
            tmp.write(uploaded.read()); tmp_path=tmp.name
        file_kb=round(len(uploaded.getvalue())/1024,1)
        _log_set("load","done",f"{uploaded.name}  ({file_kb} KB)"); _log_render(_log_ph)
        if is_pdf:
            _log_set("detect","running","reading PDF…"); _log_render(_log_ph)
        else:
            _log_set("detect","running","reading image…"); _log_render(_log_ph)
        try:
            with st.spinner("Running OCR pipeline…"):
                result = extract_invoice_from_file(
                    tmp_path,
                    original_filename=uploaded.name,
                    use_fix_rotation=use_fix_rotation,
                    use_erase_color=use_erase_color,
                    use_remove_lines=use_remove_lines,
                    use_keep_mask=use_keep_mask,
                    dpi_choice=dpi_choice,
                    split_zones=split_zones,
                    show_tables=show_tables,
                    show_products=show_products,
                    use_nlp=use_nlp,
                    include_debug_images=True,
                )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        is_native = result["is_native"]
        total_pages = result["total_pages"]
        if is_pdf:
            _log_set("detect","done",f"{'Native' if is_native else 'Scanned'} PDF — {total_pages} page(s)"); _log_render(_log_ph)
        else:
            _log_set("detect","done","Image file — 1 page"); _log_render(_log_ph)
        if is_pdf:
            c1,c2=st.columns([2,1])
            with c1:
                col="#7ee8a2" if is_native else "#e8c87e"
                st.markdown(f"<div class='metric-card'><div class='metric-label'>PDF type</div><div class='metric-value' style='color:{col}'>{'📄 Native (digital)' if is_native else '📷 Scanned'}</div></div>",unsafe_allow_html=True)
            with c2:
                st.markdown(f"<div class='metric-card'><div class='metric-label'>Pages</div><div class='metric-value'>{total_pages}</div></div>",unsafe_allow_html=True)
        st.markdown("---")

        all_orig_imgs = result["all_orig_imgs"]
        all_clean_imgs = result["all_clean_imgs"]
        all_header_texts = result["all_header_texts"]
        all_body_texts = result["all_body_texts"]
        all_full_texts = result["all_full_texts"]
        combined_full = result["combined_full"]
        extraction_trace = result["extraction_trace"]
        document_payload = result["document_payload"]
        confidence = result["confidence"]
        warnings_nlp = result["warnings_nlp"]
        plumber_tables = result["plumber_tables"]
        all_product_lines = result["all_product_lines"]
        detected_schema = result["detected_schema"]
        predicted_doc_type = result["predicted_doc_type"]
        profile_hints = result["profile_hints"]
        invoice_family = result["invoice_family"]
        v2_payload = result["v2_payload"]
        llm_validation = result["llm_validation"]
        v2_llm_validation = result["v2_llm_validation"]

        wc = len(combined_full.split())
        _log_set("preprocess","done",f"{total_pages} page(s) cleaned"); _log_render(_log_ph)
        _log_set("ocr","done",f"{total_pages} page(s)  {wc} words"); _log_render(_log_ph)
        _log_set("products","done",f"{len(all_product_lines)} item(s)"); _log_render(_log_ph)
        sg = result.get("structural_audit") or {}
        if sg.get("ok"):
            _log_set("structural_gate","done",f"{sg.get('rows_corrected',0)} row(s) · supplier={sg.get('fournisseur_nom','')[:40]}")
        elif sg.get("status") not in ("skipped", "skipped_disabled", "skipped_no_lines"):
            _log_set("structural_gate","skip",sg.get("status","—"))
        else:
            _log_set("structural_gate","skip",sg.get("status","disabled"))
        _log_render(_log_ph)
        sg = result.get("structural_audit") or {}
        if sg.get("ok"):
            _log_set("structural_gate","done",f"{sg.get('rows_corrected',0)} row(s) · supplier={sg.get('fournisseur_nom','')[:40]}")
        elif sg.get("status") not in ("skipped", "skipped_disabled", "skipped_no_lines"):
            _log_set("structural_gate","skip",sg.get("status","—"))
        else:
            _log_set("structural_gate","skip",sg.get("status","disabled"))
        _log_render(_log_ph)
        if plumber_tables:
            _log_set("pdfplumber","done",f"{len(plumber_tables)} table(s)")
        else:
            reason=("scanned PDF" if(is_pdf and not is_native) else "image file" if not is_pdf else "disabled")
            _log_set("pdfplumber","skip",reason)
        _log_render(_log_ph)
        _log_set("regex","done",f"type={document_payload.get('type','?')}  date={document_payload.get('date','—')}  HT={document_payload.get('total_ht','—')}  TTC={document_payload.get('total_ttc','—')}"); _log_render(_log_ph)
        if use_nlp:
            status="warn" if warnings_nlp else "done"
            _log_set("nlp",status,f"model={result['nlp_model_name']}  {len(warnings_nlp)} warn"); _log_render(_log_ph)
        else:
            _log_set("nlp","skip","disabled"); _log_render(_log_ph)
        _log_set("done","done",f"{total_pages} page(s) · {len(all_product_lines)} items · {len(plumber_tables)} tables · {len(warnings_nlp)} NLP warn"); _log_render(_log_ph)

        st.markdown("## 🖼️ Pages — Original & Cleaned")
        for page_i,(orig,clean) in enumerate(zip(all_orig_imgs,all_clean_imgs)):
            label=f"Page {page_i+1}/{total_pages}" if total_pages>1 else "Document"
            st.markdown(f"<div class='page-label'>{label}</div>",unsafe_allow_html=True)
            c1,c2=st.columns(2)
            with c1:
                st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#888;text-align:center;margin-bottom:4px'>📷 Original</div>",unsafe_allow_html=True)
                st.image(orig,use_container_width=True)
            with c2:
                st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#7ee8a2;text-align:center;margin-bottom:4px'>✨ After Cleaning</div>",unsafe_allow_html=True)
                st.image(clean,use_container_width=True)
            if page_i<len(all_clean_imgs)-1: st.markdown("<hr style='border-color:#1e2130;margin:12px 0;'>",unsafe_allow_html=True)
        st.markdown("---")

        dtype=document_payload.get("type","Document")
        tag_class={"Bon de Commande":"tag-bc","Proforma":"tag-proforma","Facture":"tag-facture"}.get(dtype,"tag-stat")
        st.markdown(
            f"<span class='{tag_class}'>{dtype}</span> <span style='color:#8ab4f8;font-size:12px'>v2 · {invoice_family}</span>",
            unsafe_allow_html=True,
        )
        st.markdown("## 📋 Extracted Information")
        if show_conf:
            st.markdown("<div class='conf-hint'>🟢 ≥80% reliable &nbsp;·&nbsp; 🟡 55–79% double-check &nbsp;·&nbsp; 🔴 &lt;55% likely wrong</div>",unsafe_allow_html=True)
        if show_warnings and warnings_nlp:
            ih="".join(f"<li>{w}</li>" for w in warnings_nlp)
            st.markdown(f"<div class='warn-box'>⚠ <strong>Validation warnings</strong><ul>{ih}</ul></div>",unsafe_allow_html=True)

        fields_to_show=[("Type de document","type",document_payload.get("type","—")),("Document N°","numero",document_payload.get("numero","—")),("Date","date",document_payload.get("date","—")),("Fournisseur","fournisseur_nom",document_payload.get("fournisseur_nom","—")),("Supplier MF","supplier_mf",document_payload.get("supplier_mf","—")),("Client MF","client_mf",document_payload.get("client_mf","—")),("Téléphone","tel",document_payload.get("tel","—")),("Fax","fax",document_payload.get("fax","—")),("Email","email",document_payload.get("email","—")),("RC","rc",document_payload.get("rc","—")),("Total Brut HT","total_brut_ht",document_payload.get("total_brut_ht","—")),("Remise %","remise_pct",document_payload.get("remise_pct","—")),("Total Net HT","total_ht",document_payload.get("total_ht","—")),("TVA","tva",document_payload.get("tva","—")),("Transport","transport",document_payload.get("transport","—")),("Timbre Fiscal","timbre_fiscal",document_payload.get("timbre_fiscal","—")),("Total TTC","total_ttc",document_payload.get("total_ttc","—"))]
        render_info_grid(fields_to_show,confidence,show_conf)

        if document_payload.get("adresse"):
            conf_a=confidence.get("adresse"); badge_a=_conf_badge_html(conf_a) if(show_conf and conf_a is not None) else ""
            st.markdown(f"<div class='metric-card addr-card'>{badge_a}<div class='metric-label'>Adresse</div><div class='metric-value addr-val'>{document_payload['adresse']}</div></div>",unsafe_allow_html=True)

        if show_products and all_product_lines:
            st.markdown(f"## 📦 Product Lines ({len(all_product_lines)} items)")
            render_product_table(all_product_lines,detected_schema=detected_schema,doc_type=dtype)
        elif show_products: st.info("No product lines detected. Enable 'Show Raw OCR Text' to debug.")

        if show_products and v2_payload.get("line_items"):
            st.markdown(f"## 📤 v2 export — `{v2_payload.get('invoice_family')}` ({len(v2_payload['line_items'])} rows)")
            st.dataframe(v2_payload["line_items"],use_container_width=True,height=min(420,120+28*len(v2_payload["line_items"])))

        if plumber_tables:
            st.markdown(f"## 🗃️ pdfplumber Tables ({len(plumber_tables)} found)")
            for t_idx,table in enumerate(plumber_tables):
                if not table: continue
                st.markdown(f"**Table {t_idx+1}**")
                tbl="<div class='table-container'><table><thead><tr>"
                for h in table[0]: tbl+=f"<th>{str(h).replace('&','&amp;').replace('<','&lt;')}</th>"
                tbl+="</tr></thead><tbody>"
                for row in table[1:]:
                    if any(str(c).strip() for c in row):
                        tbl+="<tr>"
                        for cell in row: tbl+=f"<td>{str(cell).replace('&','&amp;').replace('<','&lt;')}</td>"
                        tbl+="</tr>"
                tbl+="</tbody></table></div>"
                st.markdown(tbl,unsafe_allow_html=True)

        if show_raw:
            st.markdown("## 📝 Raw OCR Text")
            for page_i in range(total_pages):
                label=f"Page {page_i+1}" if total_pages>1 else "Full text"
                with st.expander(label,expanded=(page_i==0)):
                    if split_zones:
                        c1,c2=st.columns(2)
                        with c1:
                            st.markdown("**Header zone**"); st.markdown(f"<div class='raw-text'>{all_header_texts[page_i]}</div>",unsafe_allow_html=True)
                        with c2:
                            st.markdown("**Body zone**"); st.markdown(f"<div class='raw-text'>{all_body_texts[page_i]}</div>",unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div class='raw-text'>{all_full_texts[page_i]}</div>",unsafe_allow_html=True)

        clean_payload = result["v2_export"]
        audit_payload = result["audit_payload"]
        db_result = {
            "header": result["header"],
            "totals": result["totals"],
            "line_items": result["line_items"],
        }

        # Store in session_state so the page doesn't "forget" after button clicks.
        st.session_state["saved_invoice_data"] = db_result
        st.session_state["clean_payload"] = clean_payload
        st.session_state["audit_payload"] = audit_payload
        st.success("Extraction complete! Scroll down to save.")

        if show_json and st.session_state.get("clean_payload") is not None:
            st.markdown("## 🗂️ Clean JSON Preview")
            st.json(st.session_state["clean_payload"])
        if show_trace: st.markdown("## 🧭 Extraction Trace"); st.json(extraction_trace)

        st.markdown("---")
        c1,c2,c3=st.columns(3)
        with c1:
            st.download_button("⬇ Download Clean JSON",data=json.dumps(clean_payload,ensure_ascii=False,indent=2),file_name=f"{Path(uploaded.name).stem}_data.json",mime="application/json",use_container_width=True,help="Canonical v2: schema_version 2 + invoice_family + document_metadata + line_items")
        with c2:
            st.download_button("⬇ Download Audit JSON",data=json.dumps(audit_payload,ensure_ascii=False,indent=2,default=str),file_name=f"{Path(uploaded.name).stem}_audit.json",mime="application/json",use_container_width=True,help="Confidence, trace, rejected candidates")
        with c3:
            st.download_button("⬇ Download OCR Text",data=combined_full,file_name=f"{Path(uploaded.name).stem}_ocr.txt",mime="text/plain",use_container_width=True)

    # Save to DB: must live OUTSIDE `if run_btn` so the click reruns with run_btn=False.
    if uploaded and "saved_invoice_data" in st.session_state:
        st.markdown("---")
        if st.button("Extract and Save to Database", use_container_width=True):
            try:
                payload = st.session_state["saved_invoice_data"]
                invoice_id = save_result_to_db(payload)
                n_items = len(payload.get("line_items", []))
                st.success(
                    f"🎉 Success! Saved {n_items} line item(s) to the database. Invoice ID: {invoice_id}"
                )
                del st.session_state["saved_invoice_data"]
            except Exception as e:
                st.error(f"Database Error: {e}")