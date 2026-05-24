from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from ai.gap_filler import (  # noqa: E402
    apply_vision_gap_fill,
    is_gap_filler_enabled,
    merge_vision_gaps,
)


def _healthy_row(code: str, designation: str, qty: int, prix: float | None = None) -> dict:
    row = {
        "code": code,
        "designation": designation,
        "quantite": qty,
        "qty": qty,
        "_quantite_locked": True,
        "_row_txt": f"{code} {qty} {designation}",
        "_field_source": {"code": "table_structured", "quantite": "table_structured", "designation": "table_structured"},
        "_field_confidence": {"code": 0.95, "quantite": 0.88, "designation": 0.85},
    }
    if prix is not None:
        row["prix_unitaire"] = prix
        row["_field_source"]["prix_unitaire"] = "table_structured"
        row["_field_confidence"]["prix_unitaire"] = 0.90
    return row


class TestMergeVisionGaps(unittest.TestCase):
    def test_healthy_tesseract_rows_untouched_and_missing_appended(self) -> None:
        row_a = _healthy_row("111111", "DRUG A 10 MG", 10, prix=5.0)
        row_b = _healthy_row("222222", "DRUG B 20 MG", 20)
        existing = [deepcopy(row_a), deepcopy(row_b)]
        vision = [
            {"code": "111111", "quantite": 99, "designation": "SHOULD NOT REPLACE A"},
            {"code": "222222", "quantite": 99, "designation": "SHOULD NOT REPLACE B"},
            {"code": "333333", "quantite": 30, "designation": "DRUG C 5 MG B/30 COMP"},
        ]

        out, audit = merge_vision_gaps(existing, vision)

        self.assertEqual(len(out), 3)
        self.assertEqual(out[0], row_a)
        self.assertEqual(out[1], row_b)
        self.assertEqual(out[2]["code"], "333333")
        self.assertEqual(out[2]["quantite"], 30)
        self.assertEqual(out[2]["qty"], 30)
        self.assertTrue(out[2].get("_quantite_locked"))
        self.assertEqual(audit["rows_backfilled"], 1)
        self.assertEqual(audit["rows_discarded"], 2)
        self.assertEqual(audit["rows_enriched"], 0)

    def test_backfilled_row_locked_and_designation_sanitized(self) -> None:
        existing = [_healthy_row("111111", "DRUG A 10 MG", 10)]
        vision = [
            {
                "code": "333333",
                "quantite": 30,
                "designation": "333333 30 7 DRUG C 5 MG B/30 COMP",
            }
        ]

        out, audit = merge_vision_gaps(existing, vision)
        row_c = out[1]

        self.assertEqual(audit["rows_backfilled"], 1)
        self.assertEqual(row_c["quantite"], 30)
        self.assertEqual(row_c["qty"], 30)
        self.assertTrue(row_c.get("_quantite_locked"))
        desig = str(row_c.get("designation") or "").upper()
        self.assertIn("DRUG C", desig)
        self.assertNotIn("333333", desig)
        self.assertNotRegex(desig, r"^\s*30\b")

    def test_broken_row_enriched_preserves_tesseract_prices(self) -> None:
        broken_a = {
            "code": "111111",
            "designation": "",
            "prix_unitaire": 99.0,
            "_row_txt": "111111",
            "_field_source": {"code": "table_structured", "prix_unitaire": "table_structured"},
            "_field_confidence": {"code": 0.90, "prix_unitaire": 0.88},
        }
        vision = [
            {"code": "111111", "quantite": 24, "designation": "AMLODIPINE MEDIS 10 MG B/30 COMP"},
        ]

        out, audit = merge_vision_gaps([broken_a], vision)

        self.assertEqual(len(out), 1)
        self.assertEqual(audit["rows_enriched"], 1)
        self.assertEqual(audit["rows_discarded"], 0)
        self.assertEqual(audit["rows_backfilled"], 0)
        self.assertEqual(out[0]["prix_unitaire"], 99.0)
        self.assertEqual(out[0]["quantite"], 24)
        self.assertEqual(out[0]["qty"], 24)
        self.assertTrue(out[0].get("_quantite_locked"))
        self.assertIn("AMLODIPINE", str(out[0].get("designation") or "").upper())

    def test_pf_alias_on_healthy_row_discards_vision_duplicate(self) -> None:
        existing = [_healthy_row("PF003900003", "CALCITRUS PLUS", 10)]
        vision = [{"code": "PFO03900003", "quantite": 10, "designation": "CALCITRUS PLUS BT 30"}]

        out, audit = merge_vision_gaps(existing, vision)

        self.assertEqual(len(out), 1)
        self.assertEqual(audit["rows_discarded"], 1)
        self.assertEqual(audit["rows_backfilled"], 0)

    def test_invalid_vision_rows_skipped(self) -> None:
        existing = [_healthy_row("111111", "DRUG A", 10)]
        vision = [{"code": "", "quantite": 5, "designation": "X"}, {"code": "222222", "quantite": 0, "designation": ""}]

        out, audit = merge_vision_gaps(existing, vision)

        self.assertEqual(len(out), 1)
        self.assertEqual(audit["rows_skipped_invalid"], 2)


class TestApplyVisionGapFill(unittest.TestCase):
    def test_disabled_returns_input_unchanged(self) -> None:
        lines = [_healthy_row("111111", "DRUG A", 10)]
        with patch.dict(os.environ, {"GEMINI_GAP_FILLER_ENABLED": "false"}, clear=False):
            out, audit = apply_vision_gap_fill(lines, [{"image_rgb": None}])
        self.assertEqual(out, lines)
        self.assertEqual(audit["status"], "skipped_disabled")


if __name__ == "__main__":
    unittest.main()
