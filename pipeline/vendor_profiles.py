from __future__ import annotations

import re
from typing import Dict, List, Optional


VENDOR_PROFILES: Dict[str, Dict[str, object]] = {
    "avenir_medis": {
        "match_tokens": ["avenir", "rekik", "medis"],
        "doc_types": ["Bon de Commande", "Proforma", "Facture", "Document"],
        "expected_columns": ["code_pct", "quantity", "designation", "unit_price", "amount"],
        "header_aliases": {
            "code_pct": ["code", "ref", "code article local", "code pct"],
            "quantity": ["qte", "qte cmde", "qt", "quantite"],
            "designation": ["designation", "produit", "article", "desig"],
            "unit_price": ["pu", "prix", "prix unitaire"],
            "amount": ["montant", "total ligne"],
        },
    },
    "omnipharm_medis": {
        "match_tokens": ["omnipharm", "medis"],
        "doc_types": ["Bon de Commande", "Facture", "Document"],
        "expected_columns": ["code_pct", "quantity", "promotion", "designation", "unit_price", "amount"],
        "header_aliases": {
            "code_pct": ["code", "code pct", "ref"],
            "quantity": ["qte", "qt", "quantity"],
            "promotion": ["promotion", "promo"],
            "designation": ["designation", "produit", "libelle"],
            "unit_price": ["pu", "prix u", "prix unitaire"],
            "amount": ["montant", "total", "amount"],
        },
    },
    "pharmasud_medis": {
        "match_tokens": ["pharmasud", "medis"],
        "doc_types": ["Bon de Commande", "Facture", "Document"],
        "expected_columns": [
            "code_pct",
            "code_article",
            "designation",
            "quantity",
            "nb_crt",
            "u_crt",
            "date",
            "unit_price",
            "amount",
        ],
        "header_aliases": {
            "code_pct": ["code pct", "code", "ref"],
            "code_article": ["code article", "code frs", "article code"],
            "designation": ["designation", "article", "produit"],
            "quantity": ["qte", "qte cmde", "quantite"],
            "nb_crt": ["nb crt", "nombre cartons"],
            "u_crt": ["u crt", "unite carton"],
            "date": ["date p", "date peremption", "date exp"],
            "unit_price": ["pu", "prix unitaire"],
            "amount": ["montant", "total ligne"],
        },
    },
    "modele_proforma": {
        "match_tokens": ["proforma", "modele", "medis"],
        "doc_types": ["Proforma", "Document"],
        "expected_columns": ["code_pct", "code_article", "designation", "quantity", "unit_price", "amount"],
        "header_aliases": {
            "code_pct": ["code pct", "code produit", "ref pct", "ref"],
            "code_article": ["code article", "code frs", "article code", "ref article"],
            "designation": ["designation", "produit", "article", "desig"],
            "quantity": ["qte", "qt", "quantite"],
            "unit_price": ["pu", "prix unitaire", "prix"],
            "amount": ["montant", "total ligne", "montant ht"],
        },
    },
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


PROFILE_TO_V2_FAMILY = {
    "modele_proforma": "proforma_modele",
    "avenir_medis": "bc_avenir",
    "omnipharm_medis": "bc_omnipharm",
    "pharmasud_medis": "bc_pharmasud",
}


def detect_invoice_family(
    source_file: str = "",
    header_text: str = "",
    full_text: str = "",
    doc_type: str = "",
) -> str:
    """
    Single routing key for v2 parsers.
    Returns: proforma_modele | bc_avenir | bc_omnipharm | bc_pharmasud | unknown
    """
    profile = detect_vendor_profile(source_file=source_file, header_text=header_text, full_text=full_text)
    if profile and profile in PROFILE_TO_V2_FAMILY:
        mapped = PROFILE_TO_V2_FAMILY[profile]
        if profile == "modele_proforma":
            dt = (doc_type or "").lower()
            if "proforma" not in dt and "proforma" not in _normalize(full_text[:2500]):
                return "unknown"
        return mapped
    hay = _normalize(" ".join([source_file, header_text[:500], full_text[:800]]))
    if "pharmasud" in hay:
        return "bc_pharmasud"
    if "omnipharm" in hay:
        return "bc_omnipharm"
    if "avenir" in hay and "rekik" in hay:
        return "bc_avenir"
    if "proforma" in hay or "pro forma" in hay:
        return "proforma_modele"
    return "unknown"


def detect_vendor_profile(source_file: str = "", header_text: str = "", full_text: str = "") -> Optional[str]:
    hay = _normalize(" ".join([source_file, header_text[:400], full_text[:400]]))
    if not hay:
        return None
    best_key = None
    best_score = 0
    for key, profile in VENDOR_PROFILES.items():
        score = 0
        for token in profile.get("match_tokens", []):
            token_n = _normalize(token)
            if token_n and token_n in hay:
                score += 1
        if score > best_score:
            best_score = score
            best_key = key
    return best_key if best_score > 0 else None


def get_profile_hints(source_file: str = "", doc_type: str = "", header_text: str = "", full_text: str = "") -> Dict[str, object]:
    profile_key = detect_vendor_profile(source_file=source_file, header_text=header_text, full_text=full_text)
    if not profile_key:
        return {}
    profile = VENDOR_PROFILES.get(profile_key, {})
    profile_doc_types = set(profile.get("doc_types", []))
    if profile_doc_types and doc_type and doc_type not in profile_doc_types and "Document" not in profile_doc_types:
        return {"profile_key": profile_key, "confidence": 0.4, "header_aliases": {}, "expected_columns": []}
    confidence = 0.7 if doc_type in profile_doc_types else 0.6
    return {
        "profile_key": profile_key,
        "confidence": confidence,
        "header_aliases": profile.get("header_aliases", {}),
        "expected_columns": profile.get("expected_columns", []),
    }


def merge_header_aliases(base_aliases: Dict[str, List[str]], profile_hints: Dict[str, object]) -> Dict[str, List[str]]:
    merged = {k: list(v) for k, v in (base_aliases or {}).items()}
    for canon, aliases in (profile_hints or {}).get("header_aliases", {}).items():
        merged.setdefault(canon, [])
        seen = {a.lower() for a in merged[canon]}
        for alias in aliases:
            if alias.lower() not in seen:
                merged[canon].append(alias)
                seen.add(alias.lower())
    return merged
