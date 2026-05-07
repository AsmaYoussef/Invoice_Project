"""Canonical v2 JSON schema (per-invoice-family line shapes)."""

from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class DocumentMetadataV2(BaseModel):
    """Header-level fields mirrored from legacy document payload."""

    model_config = ConfigDict(extra="ignore")

    type: str = ""
    numero: str = ""
    date: str = ""
    fournisseur_nom: str = ""
    supplier_mf: str = ""
    client_mf: str = ""
    tel: str = ""
    fax: str = ""
    email: str = ""
    rc: str = ""
    adresse: str = ""
    total_brut_ht: Optional[float] = None
    remise_pct: Optional[float] = None
    total_ht: Optional[float] = None
    tva: Optional[float] = None
    tva_detail: Any = None
    transport: Optional[float] = None
    timbre_fiscal: Optional[float] = None
    total_ttc: Optional[float] = None


class ProformaLineItemV2(BaseModel):
    code_pct: str = ""
    code_article: str = ""
    designation_article: str = ""
    unite_mesure: Optional[str] = None
    quantite: str = ""
    prix_unitaire: str = ""
    montant: str = ""
    line_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_line: str = ""


class SimpleBCLineItemV2(BaseModel):
    code: str = ""
    quantite: str = ""
    designation: str = ""
    line_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_line: str = ""


class PharmasudLineItemV2(BaseModel):
    code_pct: str = ""
    designation: str = ""
    quantite_commande: str = ""
    nb_cartons: str = ""
    unite_carton: str = ""
    date_peremption: str = ""
    line_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_line: str = ""


class UnknownFamilyLineItemV2(BaseModel):
    """Fallback row when family is unknown (minimal structure)."""

    code: str = ""
    raw_line: str = ""
    line_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


LineItemV2Union = Union[ProformaLineItemV2, SimpleBCLineItemV2, PharmasudLineItemV2, UnknownFamilyLineItemV2]


class InvoiceV2Payload(BaseModel):
    schema_version: Literal[2] = 2
    invoice_family: str
    document_metadata: DocumentMetadataV2
    line_items: List[Any]

    def to_export_dict(self) -> dict:
        dm = self.document_metadata.model_dump(exclude_none=True)
        rows = []
        for row in self.line_items:
            if hasattr(row, "model_dump"):
                rows.append(row.model_dump(exclude_none=True))
            elif isinstance(row, dict):
                rows.append(dict(row))
            else:
                rows.append(row)
        return {
            "schema_version": self.schema_version,
            "invoice_family": self.invoice_family,
            "document_metadata": dm,
            "line_items": rows,
        }


def document_metadata_from_legacy(doc: dict) -> DocumentMetadataV2:
    known = {k: v for k, v in (doc or {}).items() if k in DocumentMetadataV2.model_fields}
    return DocumentMetadataV2(**known)
