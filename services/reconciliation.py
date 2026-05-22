"""OCR line reconciliation against diva_demo ERP reference tables."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz

PRICE_TOLERANCE = 0.001
CONFIDENCE_THRESHOLD = 0.85
DESIGNATION_MATCH_HIGH = 0.95
DESIGNATION_MATCH_NOISY = 0.72
DESIGNATION_RATIO_HIGH = 0.88
DESIGNATION_RATIO_LOW = 0.75
QTY_CONF_PRESENT = 0.90
QTY_CONF_RECOVERED = 0.82
QTY_CONF_MISSING = 0.68
BC_DOC_TYPES = frozenset({"bon de commande", "bon commande", "bc"})

_NOISE_LEADING = re.compile(r'^[\s\d"\'#<>.,;:!?~`]+')
_NOISE_TRAILING = re.compile(r'[\s"\'#<>.,;:!?~`]+$')

try:
    from pipeline.ocr_line_clean import sanitize_pharma_designation
except ImportError:
    from ocr_line_clean import sanitize_pharma_designation  # type: ignore


def normalize_supplier_name(name: str) -> str:
    s = (name or "").upper()
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_price(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        return v if v > 0 else None
    text = str(raw).strip()
    if not text or text in ("—", "-", "ND"):
        return None
    t = text.replace(" ", "").replace(",", ".")
    parts = t.split(".")
    if len(parts) > 2:
        t = "".join(parts[:-1]) + "." + parts[-1]
    try:
        v = float(t)
        if v <= 0 or v > 99999:
            return None
        return v
    except ValueError:
        return None


def parse_quantity(raw: Any) -> float:
    v = parse_price(raw)
    return v if v is not None else 0.0


def is_pf_code(code: str) -> bool:
    c = (code or "").strip().upper()
    return bool(re.match(r"^PF[A-Z0-9]{5,14}$", c))


def is_numeric_mp_code(code: str) -> bool:
    c = (code or "").strip()
    return bool(re.match(r"^\d{5,8}$", c))


def resolve_codes(line: dict[str, Any]) -> tuple[str, str, str]:
    """Return (primary_code, mp_code, article_code)."""
    code_pct = str(line.get("code_pct") or "").strip().upper()
    code_article = str(line.get("code_article") or "").strip().upper()
    code = str(line.get("code") or "").strip().upper()

    if code_article and is_pf_code(code_article):
        pass
    elif is_pf_code(code):
        code_article = code

    if code_pct and is_numeric_mp_code(code_pct):
        mp_code = code_pct
    elif is_numeric_mp_code(code) and not is_pf_code(code):
        mp_code = code
    else:
        mp_code = code_pct if is_numeric_mp_code(code_pct) else ""

    if not code_article and is_pf_code(code):
        code_article = code

    primary = code or code_article or mp_code
    return primary, mp_code, code_article


def normalize_product_label(s: str) -> str:
    t = str(s or "").strip().upper()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"^[\-\s]+", "", t)
    t = re.sub(r"[^A-Z0-9\s\./]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def has_designation_noise_pattern(ocr_designation: str) -> bool:
    raw = str(ocr_designation or "").strip()
    if not raw:
        return False
    if _NOISE_LEADING.match(raw) and not re.match(r"^[A-Z]", raw):
        return True
    if _NOISE_TRAILING.search(raw):
        return True
    if re.search(r'[<>~`]|>\.|"[^"]*$', raw):
        return True
    m = re.match(r"^\s*(\d{1,5})\s+([A-Z].+)$", raw)
    if m and not re.match(r"^\d+\s*MG\b", raw, re.I):
        return True
    if re.search(r"^[^A-Z]{1,3}\s+[A-Z]", raw):
        return True
    return False


def clean_erp_libprod_display(lib_prod: str, quantite: Any = None) -> str:
    return sanitize_pharma_designation(str(lib_prod or ""), quantite)


def resolve_display_designation(
    ocr_designation: str,
    lib_prod: str | None,
    quantite: Any = None,
) -> str:
    cleaned = sanitize_pharma_designation(ocr_designation or "", quantite)
    if lib_prod:
        erp_clean = clean_erp_libprod_display(lib_prod, quantite)
        if has_designation_noise_pattern(ocr_designation or ""):
            return erp_clean or cleaned
        if cleaned and erp_clean:
            ratio = fuzz.token_set_ratio(
                normalize_product_label(cleaned),
                normalize_product_label(erp_clean),
            )
            if ratio >= 88:
                return cleaned
            return erp_clean
        return erp_clean or cleaned
    return cleaned


def designation_db_confidence(ocr_designation: str, lib_prod: str) -> float:
    o_norm = normalize_product_label(ocr_designation)
    l_norm = normalize_product_label(lib_prod)
    if not l_norm:
        return DESIGNATION_MATCH_NOISY
    if not o_norm:
        return DESIGNATION_MATCH_NOISY
    ratio = fuzz.token_set_ratio(o_norm, l_norm) / 100.0
    noisy = has_designation_noise_pattern(ocr_designation)
    if ratio >= DESIGNATION_RATIO_HIGH and not noisy:
        return DESIGNATION_MATCH_HIGH
    if noisy or ratio < DESIGNATION_RATIO_LOW:
        return DESIGNATION_MATCH_NOISY
    if ratio >= 0.82:
        return DESIGNATION_MATCH_HIGH
    return DESIGNATION_MATCH_NOISY


def _parsed_qty_positive(raw: Any) -> bool:
    if raw in (None, "", 0, 0.0):
        return False
    v = parse_price(raw)
    return v is not None and v > 0


def quantite_confidence_score(line: dict[str, Any], *, bc_layout: bool = False) -> float:
    if not _parsed_qty_positive(line.get("quantite")):
        return QTY_CONF_MISSING if bc_layout else 0.55
    field_conf = line.get("_field_confidence") or {}
    if "quantite" in field_conf:
        try:
            return float(field_conf["quantite"])
        except (TypeError, ValueError):
            pass
    src = str((line.get("_field_source") or {}).get("quantite") or "")
    if src in ("table_structured", "gemini_vision"):
        return QTY_CONF_PRESENT
    if src in (
        "qty_recovered_designation",
        "qty_recovered_row",
        "qty_pattern_a",
        "qty_pattern_b",
        "qty_positional_prefix",
        "qty_positional_suffix",
        "ocr_fallback",
        "local_sanitize",
        "v2_parser",
        "qty_locked",
    ):
        return QTY_CONF_RECOVERED
    return QTY_CONF_RECOVERED


def _line_has_quantite(line: dict[str, Any]) -> bool:
    return _parsed_qty_positive(line.get("quantite"))


def combined_line_confidence(
    line: dict[str, Any],
    *,
    erp_name: str | None = None,
    ref_row: bool = False,
    bc_layout: bool = False,
) -> float:
    if ref_row and erp_name:
        des_conf = designation_db_confidence(line.get("designation") or "", erp_name)
    else:
        des_conf = line_confidence_score(line)
    qty_conf = quantite_confidence_score(line, bc_layout=bc_layout)
    return min(des_conf, qty_conf)


def line_confidence_score(line: dict[str, Any]) -> float:
    if line.get("confidence") is not None:
        try:
            return float(line["confidence"])
        except (TypeError, ValueError):
            pass
    if line.get("line_confidence") is not None:
        try:
            return float(line["line_confidence"])
        except (TypeError, ValueError):
            pass
    field_conf = line.get("_field_confidence") or {}
    keys = ("code", "code_pct", "code_article", "prix_unitaire", "quantite", "designation")
    scores = []
    for k in keys:
        if k in field_conf:
            try:
                scores.append(float(field_conf[k]))
            except (TypeError, ValueError):
                pass
    if scores:
        return min(scores)
    return 1.0


def is_bc_document(doc_type: str, invoice_family: str = "") -> bool:
    dt = (doc_type or "").lower()
    fam = (invoice_family or "").lower()
    if "bc_" in fam or "bon" in fam:
        return True
    return any(token in dt for token in BC_DOC_TYPES)


class ReconciliationService:
    def __init__(self, cursor, *, articles_cache: dict | None = None, suppliers_cache: list | None = None):
        self.cursor = cursor
        self._articles = articles_cache
        self._suppliers = suppliers_cache

    def load_reference_data(self) -> None:
        self.cursor.execute("SELECT IDArticle, Code, LibProd, PrixAchat FROM article")
        self._articles = {
            str(row["Code"]).strip().upper(): row
            for row in self.cursor.fetchall()
            if row.get("Code")
        }
        self.cursor.execute("SELECT IDFournisseur, Code, Nom, MF FROM fournisseur")
        self._suppliers = list(self.cursor.fetchall())

    def lookup_article(self, code: str) -> dict | None:
        if not code or not self._articles:
            return None
        return self._articles.get(code.strip().upper())

    def match_supplier(self, ocr_name: str, ocr_mf: str = "") -> dict[str, Any]:
        norm_ocr = normalize_supplier_name(ocr_name)
        ocr_mf = (ocr_mf or "").strip().upper()
        if not norm_ocr and not ocr_mf:
            return {
                "supplier_status": "SUPPLIER_UNKNOWN",
                "erp_supplier_name": None,
                "erp_supplier_mf": None,
                "erp_supplier_code": None,
            }

        best = None
        for row in self._suppliers or []:
            nom = normalize_supplier_name(row.get("Nom") or "")
            mf = (row.get("MF") or "").strip().upper()
            if ocr_mf and mf and ocr_mf == mf:
                best = row
                break
            if nom and nom in norm_ocr:
                best = row
                break
            if norm_ocr and nom and any(token in nom for token in norm_ocr.split() if len(token) > 3):
                best = row
                break

        if best:
            return {
                "supplier_status": "SUPPLIER_MATCH",
                "erp_supplier_name": best.get("Nom"),
                "erp_supplier_mf": best.get("MF"),
                "erp_supplier_code": best.get("Code"),
            }
        return {
            "supplier_status": "SUPPLIER_UNKNOWN",
            "erp_supplier_name": None,
            "erp_supplier_mf": None,
            "erp_supplier_code": None,
        }

    def reconcile_line(
        self,
        line: dict[str, Any],
        *,
        doc_type: str = "",
        invoice_family: str = "",
    ) -> dict[str, Any]:
        primary, mp_code, article_code = resolve_codes(line)
        mp_row = self.lookup_article(mp_code) if mp_code else None
        article_row = self.lookup_article(article_code) if article_code else None
        if not article_row and primary:
            article_row = self.lookup_article(primary)
        if not mp_row and primary and is_numeric_mp_code(primary):
            mp_row = self.lookup_article(primary)

        ref_row = article_row or mp_row
        erp_price = None
        erp_name = None
        id_article = None
        if ref_row:
            erp_price = float(ref_row["PrixAchat"] or 0)
            erp_name = ref_row.get("LibProd")
            id_article = ref_row.get("IDArticle")

        extracted_price = parse_price(
            line.get("price_unit")
            if line.get("price_unit") is not None
            else line.get("prix_unitaire")
        )
        qty = parse_quantity(line.get("quantite"))
        bc_layout = is_bc_document(doc_type, invoice_family)
        price_from_db = False

        if extracted_price is None and erp_price is not None and (bc_layout or not parse_price(line.get("prix_unitaire"))):
            extracted_price = erp_price
            price_from_db = True

        flags: list[str] = []
        if mp_row:
            flags.append("mp_found")
        elif mp_code:
            flags.append("mp_missing")
        if article_row:
            flags.append("article_found")
        elif article_code:
            flags.append("article_missing")

        ocr_price = extracted_price if not price_from_db else None
        display_price = extracted_price
        display_designation = resolve_display_designation(
            line.get("designation") or "",
            erp_name,
            line.get("quantite"),
        )

        confidence = combined_line_confidence(
            line,
            erp_name=erp_name,
            ref_row=bool(ref_row),
            bc_layout=bc_layout,
        )

        if ref_row and erp_name and display_designation:
            if designation_db_confidence(
                display_designation or line.get("designation") or "", erp_name
            ) >= DESIGNATION_MATCH_HIGH:
                flags.append("designation_match_high")
        if _line_has_quantite(line):
            flags.append("qty_present")
        else:
            flags.append("qty_missing")

        code_known = bool(mp_row or article_row or ref_row)
        has_codes = bool(mp_code or article_code or primary)

        if not code_known and has_codes:
            validation_status = "UNKNOWN_PRODUCT"
        elif (
            ocr_price is not None
            and erp_price is not None
            and abs(ocr_price - erp_price) > PRICE_TOLERANCE
        ):
            validation_status = "PRICE_MISMATCH"
        elif confidence < CONFIDENCE_THRESHOLD:
            validation_status = "LOW_CONFIDENCE"
        elif not code_known:
            validation_status = "UNKNOWN_PRODUCT"
        elif bc_layout and ocr_price is None and erp_price is not None:
            validation_status = "VALID"
        elif ocr_price is not None and erp_price is not None:
            validation_status = "VALID"
        elif ocr_price is None and not bc_layout:
            validation_status = "UNKNOWN_PRODUCT"
        else:
            validation_status = "VALID"

        computed_montant = None
        if qty and display_price is not None:
            computed_montant = round(qty * display_price, 3)

        return {
            "code": primary or line.get("code", ""),
            "code_pct": mp_code,
            "code_article": article_code,
            "designation": display_designation or line.get("designation") or erp_name or "",
            "quantite": line.get("quantite") if line.get("quantite") not in (None, "") else "",
            "ocr_price": ocr_price,
            "price_unit": display_price,
            "erp_price": erp_price,
            "erp_name": erp_name,
            "id_article": id_article,
            "validation_status": validation_status,
            "confidence": round(confidence, 3),
            "flags": flags,
            "price_from_db": price_from_db,
            "computed_montant": computed_montant,
        }

    def reconcile_document(
        self,
        lines: list[dict[str, Any]],
        *,
        general_info: dict[str, Any] | None = None,
        doc_type: str = "",
        invoice_family: str = "",
    ) -> dict[str, Any]:
        if self._articles is None or self._suppliers is None:
            self.load_reference_data()

        info = general_info or {}
        supplier = self.match_supplier(
            info.get("supplier_name") or info.get("fournisseur_nom") or "",
            info.get("supplier_mf") or info.get("supplier_mf") or "",
        )

        product_lines = [
            self.reconcile_line(
                line,
                doc_type=doc_type or info.get("document_type", ""),
                invoice_family=invoice_family or info.get("invoice_family", ""),
            )
            for line in lines
        ]

        return {
            "general_info": {
                **info,
                **supplier,
            },
            "product_lines": product_lines,
        }


def coerce_quantite(val: Any) -> int | float | str:
    if val in (None, ""):
        return ""
    if isinstance(val, bool):
        return ""
    if isinstance(val, int):
        return val if val > 0 else ""
    if isinstance(val, float):
        if val <= 0:
            return ""
        return int(val) if val == int(val) else val
    parsed = parse_price(val)
    if parsed is not None and parsed > 0:
        return int(parsed) if parsed == int(parsed) else parsed
    text = str(val).strip()
    return text if text else ""


def pipeline_line_to_internal(line: dict[str, Any]) -> dict[str, Any]:
    """Map OCR pipeline keys to reconciliation input."""
    prix = (
        line.get("prix_unitaire")
        or line.get("prix_unitaire_ht")
        or line.get("unit_price_ht")
        or ""
    )
    out: dict[str, Any] = {
        "code": line.get("code", ""),
        "code_pct": line.get("code_pct", ""),
        "code_article": line.get("code_article", ""),
        "designation": line.get("designation") or line.get("designation_article") or "",
        "quantite": coerce_quantite(line.get("quantite") or line.get("qty")),
        "prix_unitaire": prix,
        "line_confidence": line.get("line_confidence"),
        "_field_confidence": line.get("_field_confidence"),
        "_field_source": line.get("_field_source"),
        "price_from_db": False,
    }
    if line.get("_quantite_locked"):
        out["_quantite_locked"] = True
    return out


def dashboard_line_to_internal(line: dict[str, Any]) -> dict[str, Any]:
    """Map API/dashboard row back into reconciliation (re-validate / save)."""
    ocr = line.get("ocr_price")
    if ocr is None and not line.get("price_from_db"):
        ocr = line.get("price_unit")
    return {
        "code": line.get("code", ""),
        "code_pct": line.get("code_pct", ""),
        "code_article": line.get("code_article", ""),
        "designation": line.get("designation", ""),
        "quantite": line.get("quantite", ""),
        "prix_unitaire": ocr if ocr is not None else "",
        "price_unit": line.get("price_unit"),
        "line_confidence": line.get("line_confidence")
        if line.get("line_confidence") is not None
        else line.get("confidence"),
        "confidence": line.get("confidence"),
        "price_from_db": bool(line.get("price_from_db")),
    }
