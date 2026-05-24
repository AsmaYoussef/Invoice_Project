from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from streamlit_ocr_app import merge_line_items  # noqa: E402


class TestMergeLineItemsRowTxt(unittest.TestCase):
    def test_primary_adopts_fallback_row_txt_with_qty(self) -> None:
        primary = [
            {
                "code": "302970",
                "designation": "AMLODIPINE MEDIS 10 MG",
                "_row_txt": "302970 AMLODIPINE MEDIS 10 MG",
                "_field_source": {"code": "table_structured"},
                "_field_confidence": {"code": 0.95},
            }
        ]
        fallback = [
            {
                "code": "302970",
                "quantite": 24,
                "qty": 24,
                "_quantite_locked": True,
                "_row_txt": "302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP",
                "_field_source": {"quantite": "ocr_fallback"},
                "_field_confidence": {"quantite": 0.85},
            }
        ]
        merged = merge_line_items(primary, fallback)
        row = merged[0]
        self.assertIn("24", str(row.get("_row_txt") or ""))
        self.assertEqual(row.get("quantite"), 24)
        self.assertTrue(row.get("_quantite_locked"))


if __name__ == "__main__":
    unittest.main()
