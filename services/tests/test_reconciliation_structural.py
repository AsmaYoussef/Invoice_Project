from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.reconciliation import (
    STRUCTURAL_VALID_CONFIDENCE,
    ReconciliationService,
    combined_line_confidence,
    designation_db_confidence,
)


def _svc(articles: dict) -> ReconciliationService:
    cursor = MagicMock()
    return ReconciliationService(cursor, articles_cache=articles, suppliers_cache=[])


class TestCombinedLineConfidence(unittest.TestCase):
    def test_messy_designation_with_ref_row_scores_high_without_fuzz(self) -> None:
        line = {
            "designation": "302970 24 7 AMLODIPINE MEDIS 10 MG",
            "quantite": 24,
        }
        erp_name = "AMLODIPINE MEDIS 10 MG B/30 COMP"
        self.assertLess(
            designation_db_confidence(line["designation"], erp_name),
            STRUCTURAL_VALID_CONFIDENCE,
        )
        score = combined_line_confidence(line, erp_name=erp_name, ref_row=True, bc_layout=True)
        self.assertEqual(score, STRUCTURAL_VALID_CONFIDENCE)

    def test_empty_designation_forces_low_score(self) -> None:
        line = {"designation": "", "quantite": 24}
        score = combined_line_confidence(line, ref_row=True, bc_layout=True)
        self.assertEqual(score, 0.0)

    def test_missing_qty_forces_low_score(self) -> None:
        line = {"designation": "DRUG A 10 MG", "quantite": ""}
        score = combined_line_confidence(line, ref_row=True, bc_layout=True)
        self.assertLess(score, 0.85)


class TestReconcileLineStructural(unittest.TestCase):
    def setUp(self) -> None:
        self.articles = {
            "302970": {
                "IDArticle": 1,
                "Code": "302970",
                "LibProd": "AMLODIPINE MEDIS 10 MG B/30 COMP",
                "PrixAchat": 12.5,
            },
            "999999": {
                "IDArticle": 2,
                "Code": "999999",
                "LibProd": "OTHER DRUG",
                "PrixAchat": 5.0,
            },
        }
        self.svc = _svc(self.articles)

    def test_structural_valid_messy_designation_green(self) -> None:
        line = {
            "code": "302970",
            "designation": "302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP",
            "quantite": 24,
            "prix_unitaire": 12.5,
        }
        out = self.svc.reconcile_line(line, doc_type="Bon de Commande", invoice_family="bc_avenir")
        self.assertEqual(out["validation_status"], "VALID")
        self.assertEqual(out["confidence"], STRUCTURAL_VALID_CONFIDENCE)
        self.assertEqual(out["quantite"], 24)

    def test_empty_designation_low_confidence(self) -> None:
        line = {
            "code": "302970",
            "designation": "",
            "quantite": 24,
            "prix_unitaire": 12.5,
        }
        out = self.svc.reconcile_line(line, doc_type="Bon de Commande", invoice_family="bc_avenir")
        self.assertEqual(out["validation_status"], "LOW_CONFIDENCE")
        self.assertLess(out["confidence"], 0.85)

    def test_missing_qty_low_confidence(self) -> None:
        line = {
            "code": "302970",
            "designation": "AMLODIPINE MEDIS 10 MG",
            "quantite": "",
            "prix_unitaire": 12.5,
        }
        out = self.svc.reconcile_line(line, doc_type="Bon de Commande", invoice_family="bc_avenir")
        self.assertEqual(out["validation_status"], "LOW_CONFIDENCE")
        self.assertLess(out["confidence"], 0.85)

    def test_price_mismatch_red(self) -> None:
        line = {
            "code": "302970",
            "designation": "AMLODIPINE MEDIS 10 MG",
            "quantite": 24,
            "prix_unitaire": 99.0,
        }
        out = self.svc.reconcile_line(line, doc_type="Bon de Commande", invoice_family="bc_avenir")
        self.assertEqual(out["validation_status"], "PRICE_MISMATCH")

    def test_unknown_product_gray(self) -> None:
        line = {
            "code": "000001",
            "designation": "UNKNOWN DRUG",
            "quantite": 10,
            "prix_unitaire": 1.0,
        }
        out = self.svc.reconcile_line(line, doc_type="Bon de Commande", invoice_family="bc_avenir")
        self.assertEqual(out["validation_status"], "UNKNOWN_PRODUCT")

    def test_price_from_db_valid_bc(self) -> None:
        line = {
            "code": "302970",
            "designation": "AMLODIPINE MEDIS 10 MG",
            "quantite": 24,
            "prix_unitaire": "",
        }
        out = self.svc.reconcile_line(line, doc_type="Bon de Commande", invoice_family="bc_avenir")
        self.assertEqual(out["validation_status"], "VALID")
        self.assertTrue(out["price_from_db"])
        self.assertEqual(out["confidence"], STRUCTURAL_VALID_CONFIDENCE)


if __name__ == "__main__":
    unittest.main()
