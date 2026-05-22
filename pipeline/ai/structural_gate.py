"""Unit tests for Gemini structural realignment gate (no live API)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_PIPELINE = Path(__file__).resolve().parents[1]
_REPO = _PIPELINE.parent
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ai.structural_gate import (  # noqa: E402
    _coerce_qty_float,
    _is_supplier_name_plausible,
    _is_qty_plausible_local,
    _math_balance_ok,
    _merge_gate_into_lines,
    _sanitize_gate_row,
    apply_structural_realignment_gate,
    lines_to_unified_payload,
    snapshot_to_v2_line_items,
    validate_structural_response,
)
from parsers import FAMILY_BC_AVENIR, FAMILY_PROFORMA  # noqa: E402


class TestSupplierSanity(unittest.TestCase):
    def test_rejects_proforma_doc_number(self) -> None:
        self.assertFalse(
            _is_supplier_name_plausible("PROFORMA N°:MDN-PRE-2308139")
        )

    def test_rejects_url_noise(self) -> None:
        self.assertFalse(
            _is_supplier_name_plausible(
                "STAT VENTES / APPRO http://192.168.1.5/stock"
            )
        )

    def test_rejects_omnipharm_header_garbage(self) -> None:
        self.assertFalse(_is_supplier_name_plausible("ack _"))

    def test_accepts_laboratory_name(self) -> None:
        self.assertTrue(_is_supplier_name_plausible("Laboratoires Médis"))
        self.assertTrue(_is_supplier_name_plausible("STE AVICENNE"))


class TestQtyPlausibility(unittest.TestCase):
    def test_comma_decimal_qty_plausible(self) -> None:
        self.assertTrue(
            _is_qty_plausible_local("280,00", "AMLODIPINE 10 MG B/30 COMP")
        )

    def test_244_comma_qty(self) -> None:
        self.assertTrue(_is_qty_plausible_local("244,00", "AMLODIPINE MEDIS 5 MG"))

    def test_coerce_qty_float_comma(self) -> None:
        self.assertEqual(_coerce_qty_float("280,00"), 280.0)

    def test_200000_ui_still_rejected(self) -> None:
        self.assertFalse(
            _is_qty_plausible_local(200000, "DMAX 200000 UI INJ B01")
        )

    def test_normal_order_qty_plausible(self) -> None:
        self.assertTrue(
            _is_qty_plausible_local(24, "AMLODIPINE MEDIS 10 MG B/30 COMP")
        )

    def test_high_commercial_count_accepted(self) -> None:
        self.assertTrue(_is_qty_plausible_local(4500, "NEUROMED 160MG B/90 GEL"))


class TestMathBalance(unittest.TestCase):
    def test_balanced_row(self) -> None:
        self.assertTrue(_math_balance_ok(60, 8258, 495480))

    def test_unbalanced_row(self) -> None:
        self.assertFalse(_math_balance_ok(200000, 2.8, 896800))


class TestSanitizeGateRow(unittest.TestCase):
    def test_math_unbalanced_keeps_qty(self) -> None:
        row = _sanitize_gate_row(
            {
                "designation_article": "AMLODIPINE 10 MG",
                "quantite": 200000,
                "prix_unitaire": 2.8,
                "montant": 896800,
            },
            doc_type="Proforma",
        )
        self.assertIsNone(row["quantite"])

    def test_math_unbalanced_preserves_valid_qty(self) -> None:
        row = _sanitize_gate_row(
            {
                "designation_article": "AMLODIPINE 10 MG CP",
                "quantite": "60,00",
                "prix_unitaire": 100,
                "montant": 50,
            },
            doc_type="Proforma",
        )
        self.assertEqual(row["quantite"], 60.0)
        self.assertTrue(row["_math_unbalanced"])


class TestLinesToUnified(unittest.TestCase):
    def test_maps_legacy_bc_row(self) -> None:
        lines = [
            {
                "code": "302970",
                "quantite": 24,
                "designation": "AMLODIPINE MEDIS 10 MG B/30 COMP",
            }
        ]
        payload = lines_to_unified_payload(lines, {"type": "Bon de Commande"})
        item = payload["line_items"][0]
        self.assertEqual(item["code_pct"], "302970")
        self.assertEqual(item["quantite"], 24.0)
        self.assertIn("AMLODIPINE", item["designation_article"])

    def test_maps_proforma_row(self) -> None:
        lines = [
            {
                "code_pct": "303543",
                "code_article": "PF000400001",
                "designation": "DMAX 200000 UI INJ",
                "quantite": "200000",
                "prix_unitaire": "2.8",
                "montant": "896800",
            }
        ]
        payload = lines_to_unified_payload(lines)
        item = payload["line_items"][0]
        self.assertEqual(item["code_article"], "PF000400001")


class TestValidateResponse(unittest.TestCase):
    def test_strips_bad_supplier_and_dosage_qty(self) -> None:
        parsed = {
            "document_metadata": {
                "fournisseur_nom": "PROFORMA N°:MDN-PRE-2308139",
                "type": "Proforma",
                "numero": "MDN-PRE-2308139",
                "date": "30/08/2023",
            },
            "line_items": [
                {
                    "code_pct": "303543",
                    "code_article": "PF000400001",
                    "designation_article": "DMAX 200000 UI INJ B01",
                    "quantite": 200000,
                    "prix_unitaire": 2.8,
                    "montant": 896800,
                }
            ],
        }
        out = validate_structural_response(parsed, doc_type="Proforma")
        assert out is not None
        self.assertEqual(out["document_metadata"]["fournisseur_nom"], "")
        self.assertIsNone(out["line_items"][0]["quantite"])


class TestMergeGateIntoLines(unittest.TestCase):
    def test_merges_designation_and_qty(self) -> None:
        original = [
            {
                "code": "302970",
                "designation": "7 AMLODIPINE MEDIS 10 MG B/30 COMP >.",
                "quantite": "",
            }
        ]
        snapshot = {
            "line_items": [
                {
                    "code_pct": "302970",
                    "code_article": "",
                    "designation_article": "AMLODIPINE MEDIS 10 MG B/30 COMP",
                    "quantite": 24,
                    "prix_unitaire": None,
                    "montant": None,
                    "gate_confidence": 0.9,
                }
            ]
        }
        merged, n = _merge_gate_into_lines(original, snapshot, doc_type="Bon de Commande")
        self.assertGreaterEqual(n, 1)
        self.assertEqual(merged[0]["quantite"], 24)
        self.assertEqual(merged[0]["qty"], 24)
        self.assertIn("AMLODIPINE", merged[0]["designation"])

    def test_merge_comma_qty_string(self) -> None:
        original = [{"code": "302968", "quantite": ""}]
        snapshot = {
            "line_items": [
                {
                    "designation_article": "AMLODIPINE MEDIS 5 MG",
                    "quantite": "244,00",
                    "gate_confidence": 0.9,
                }
            ]
        }
        merged, n = _merge_gate_into_lines(original, snapshot)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(merged[0]["quantite"], 244)
        self.assertEqual(merged[0]["qty"], 244)

    def test_respects_locked_qty(self) -> None:
        original = [
            {
                "code": "302970",
                "quantite": 12,
                "_quantite_locked": True,
                "designation": "OLD",
            }
        ]
        snapshot = {
            "line_items": [
                {
                    "designation_article": "NEW NAME",
                    "quantite": 99,
                    "gate_confidence": 0.9,
                }
            ]
        }
        merged, _ = _merge_gate_into_lines(original, snapshot)
        self.assertEqual(merged[0]["quantite"], 12)


class TestSnapshotToV2(unittest.TestCase):
    def test_proforma_shape(self) -> None:
        snapshot = {
            "line_items": [
                {
                    "code_pct": "302970",
                    "code_article": "PF000700004",
                    "designation_article": "AMLODIPINE 10 MG CP",
                    "quantite": 60,
                    "prix_unitaire": 8258,
                    "montant": 495480,
                    "gate_confidence": 0.9,
                }
            ]
        }
        rows = snapshot_to_v2_line_items(
            snapshot,
            [{"raw_line": "302970 PF000700004 AMLODIPINE 60,00 8258 495480"}],
            invoice_family=FAMILY_PROFORMA,
        )
        self.assertEqual(rows[0]["code_pct"], "302970")
        self.assertEqual(rows[0]["quantite"], "60")
        self.assertEqual(rows[0]["qty"], "60")

    def test_bc_shape_with_orig_fallback(self) -> None:
        snapshot = {
            "line_items": [
                {
                    "code_pct": "302970",
                    "designation_article": "AMLODIPINE MEDIS 10 MG B/30 COMP",
                    "quantite": None,
                    "gate_confidence": 0.9,
                }
            ]
        }
        rows = snapshot_to_v2_line_items(
            snapshot,
            [{"code": "302970", "quantite": 24, "qty": 24}],
            invoice_family=FAMILY_BC_AVENIR,
        )
        self.assertEqual(rows[0]["quantite"], "24")
        self.assertEqual(rows[0]["qty"], "24")


class TestApplyGateMocked(unittest.TestCase):
    @patch("ai.structural_gate.is_structural_gate_enabled", return_value=True)
    @patch("ai.structural_gate.generate_vision_json")
    def test_applies_mock_vision_response(
        self, mock_vision, _enabled
    ) -> None:
        mock_vision.return_value = {
            "ok": True,
            "parsed_json": {
                "document_metadata": {
                    "fournisseur_nom": "Laboratoires Médis",
                    "type": "Proforma",
                    "numero": "MDN-PRE-2308139",
                    "date": "30/08/2023",
                },
                "line_items": [
                    {
                        "code_pct": "303543",
                        "code_article": "PF000400001",
                        "designation_article": "DMAX 200000 UI INJ B01",
                        "quantite": 5,
                        "prix_unitaire": 2.8,
                        "montant": 14.0,
                    }
                ],
            },
        }
        import numpy as np

        lines = [
            {
                "code_pct": "303543",
                "code_article": "PF000400001",
                "designation": "DMAX 200000 UI INJ",
                "quantite": "200000",
            }
        ]
        page_assets = [
            {
                "image_rgb": np.zeros((100, 100, 3), dtype=np.uint8),
                "body_text": "Laboratoires Médis Proforma",
            }
        ]
        merged, audit, snap = apply_structural_realignment_gate(
            lines,
            page_assets,
            document_metadata={"type": "Proforma"},
            doc_type="Proforma",
            invoice_family=FAMILY_PROFORMA,
        )
        self.assertTrue(audit["ok"])
        self.assertEqual(merged[0]["quantite"], 5)
        self.assertEqual(merged[0]["qty"], 5)
        self.assertEqual(audit["fournisseur_nom"], "Laboratoires Médis")
        assert snap is not None


if __name__ == "__main__":
    unittest.main()
