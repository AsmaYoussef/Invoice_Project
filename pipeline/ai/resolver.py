from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from pydantic import BaseModel, Field, ValidationError


class FieldEvidence(BaseModel):
    value: str = ""
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ResolverOutput(BaseModel):
    document_fields: Dict[str, FieldEvidence] = Field(default_factory=dict)
    line_item_hints: List[Dict[str, Any]] = Field(default_factory=list)

class LineItemHint(BaseModel):
    code: str = ""
    field: str = ""
    value: str = ""
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def _build_prompt(context: Dict[str, Any]) -> str:
    base = (
        "You are validating ambiguous invoice fields.\n"
        "Return strict JSON only with keys: document_fields, line_item_hints.\n"
        "Each document field entry must have value, evidence, confidence (0..1).\n"
        "Each line_item_hints entry: code, field, value, evidence, confidence (0..1).\n"
        "Use only values directly present in provided text; evidence must be an exact substring of the source.\n"
    )
    if context.get("v2_gap_lines"):
        base += (
            "v2_gap_lines lists rows missing canonical v2 fields. Fill line_item_hints using the row's code, "
            "the missing field name (e.g. prix_unitaire, montant, quantite, date_peremption, quantite_commande), "
            "and evidence copied from that row's raw_line.\n"
        )
    base += f"\nContext JSON:\n{json.dumps(context, ensure_ascii=False)}"
    return base


def _extract_candidate_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    parsed = raw.get("parsed_json")
    if isinstance(parsed, dict):
        return parsed
    text = raw.get("response_text", "")
    if isinstance(text, str):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return {}
    return {}


def _has_evidence(source_text: str, evidence: str) -> bool:
    evidence = str(evidence or "").strip()
    return bool(evidence) and evidence.lower() in source_text.lower()


def resolve_ambiguous_fields(
    ask_json_fn: Callable[..., Dict[str, Any]] | None,
    source_text: str,
    candidate_payload: Dict[str, Any],
    min_confidence: float = 0.65,
) -> Dict[str, Any]:
    if ask_json_fn is None:
        return {
            "ok": False,
            "status": "skipped_client_unavailable",
            "resolved": {},
            "raw": {},
            "accepted_line_item_hints": [],
        }

    prompt = _build_prompt(candidate_payload)
    try:
        raw = ask_json_fn(prompt, retries=1, timeout_s=35, max_response_chars=20000)
    except Exception as exc:
        return {
            "ok": False,
            "status": "request_error",
            "error": str(exc),
            "resolved": {},
            "raw": {},
            "accepted_line_item_hints": [],
        }

    candidate = _extract_candidate_dict(raw)
    if not candidate:
        return {
            "ok": False,
            "status": "invalid_json",
            "resolved": {},
            "raw": raw,
            "accepted_line_item_hints": [],
        }

    try:
        validated = ResolverOutput.model_validate(candidate)
    except ValidationError as exc:
        return {
            "ok": False,
            "status": "schema_validation_failed",
            "error": str(exc),
            "resolved": {},
            "raw": raw,
            "accepted_line_item_hints": [],
        }

    resolved: Dict[str, Any] = {}
    for field, payload in validated.document_fields.items():
        if payload.confidence < min_confidence:
            continue
        if not _has_evidence(source_text, payload.evidence):
            continue
        resolved[field] = {
            "value": payload.value,
            "confidence": payload.confidence,
            "evidence": payload.evidence,
            "source": "ai_resolver",
        }

    accepted_line_hints: List[Dict[str, Any]] = []
    for raw_hint in validated.line_item_hints:
        try:
            hint = LineItemHint.model_validate(raw_hint)
        except ValidationError:
            continue
        if hint.confidence < min_confidence:
            continue
        if not _has_evidence(source_text, hint.evidence):
            continue
        allowed = {
            "quantite",
            "code_article",
            "date_peremption",
            "nb_crt",
            "u_crt",
            "prix_unitaire",
            "montant",
            "quantite_commande",
            "nb_cartons",
            "unite_carton",
            "designation_article",
        }
        if hint.field not in allowed:
            continue
        if not str(hint.code).strip():
            continue
        accepted_line_hints.append(
            {
                "code": hint.code.strip().upper(),
                "field": hint.field,
                "value": hint.value,
                "confidence": hint.confidence,
                "evidence": hint.evidence,
            }
        )

    return {
        "ok": True,
        "status": "resolved" if (resolved or accepted_line_hints) else "no_high_confidence_match",
        "resolved": resolved,
        "raw": raw,
        "line_item_hints": validated.line_item_hints,
        "accepted_line_item_hints": accepted_line_hints,
    }
