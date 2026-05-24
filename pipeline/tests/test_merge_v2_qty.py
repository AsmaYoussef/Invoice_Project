from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from v2_build import merge_v2_quantities_into_product_lines  # noqa: E402


class TestMergeV2Qty(unittest.TestCase):
    def test_table_row_gets_locked_qty_from_v2_snapshot(self) -> None:
        legacy = [
            {
                "code": "302970",
                "designation": "AMLODIPINE MEDIS 10 MG",
                "_row_txt": "302970 AMLODIPINE MEDIS 10 MG",
            }
        ]
        v2_payload = {
            "line_items": [
                {
                    "code": "302970",
                    "quantite": 24,
                    "designation": "AMLODIPINE MEDIS 10 MG B/30 COMP",
                    "raw_line": "302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP",
                    "line_confidence": 0.9,
                }
            ]
        }
        out = merge_v2_quantities_into_product_lines(legacy, v2_payload)
        row = out[0]
        self.assertEqual(row.get("quantite"), 24)
        self.assertEqual(row.get("qty"), 24)
        self.assertTrue(row.get("_quantite_locked"))
        self.assertIn("24", str(row.get("_row_txt") or ""))

    def test_pf_code_normalization_matches(self) -> None:
        legacy = [{"code": "PF003900003", "designation": "CALCITRUS", "_row_txt": "PF003900003 CALCITRUS"}]
        v2_payload = {
            "line_items": [
                {
                    "code": "PFO03900003",
                    "quantite": 10,
                    "raw_line": "PFO03900003 10 CALCITRUS PLUS",
                    "line_confidence": 0.88,
                }
            ]
        }
        out = merge_v2_quantities_into_product_lines(legacy, v2_payload)
        self.assertEqual(out[0].get("quantite"), 10)
        self.assertTrue(out[0].get("_quantite_locked"))


if __name__ == "__main__":
    unittest.main()
