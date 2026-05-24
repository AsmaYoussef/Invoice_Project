from __future__ import annotations

import unittest

from pipeline.ocr_line_clean import (
    apply_designation_cleanup_only,
    extract_and_lock_quantite_only,
    line_has_quantite,
    process_line_extract_then_clean,
    quantite_is_locked,
    sanitize_pharma_designation,
)


class TestExtractLockCleanOrder(unittest.TestCase):
    def test_avenir_mp_line_extracts_and_locks_qty(self) -> None:
        raw = "302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP"
        item = {"code": "302970", "_row_txt": raw}
        out = extract_and_lock_quantite_only(item)
        self.assertTrue(quantite_is_locked(out))
        self.assertEqual(out.get("quantite"), 24)
        self.assertEqual(out.get("qty"), 24)
        self.assertIn("AMLODIPINE", str(out.get("designation") or "").upper())

    def test_sanitize_preserves_locked_qty(self) -> None:
        raw = "302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP"
        item = process_line_extract_then_clean({"code": "302970", "_row_txt": raw})
        self.assertTrue(quantite_is_locked(item))
        self.assertEqual(item.get("quantite"), 24)
        cleaned = apply_designation_cleanup_only([item])[0]
        self.assertTrue(line_has_quantite(cleaned))
        self.assertEqual(cleaned.get("quantite"), 24)
        self.assertEqual(cleaned.get("qty"), 24)
        desig = str(cleaned.get("designation") or "").upper()
        self.assertIn("AMLODIPINE", desig)
        self.assertIn("B/30 COMP", desig)
        self.assertNotRegex(desig, r"^\s*302970")
        self.assertNotRegex(desig, r"^\s*24\b")

    def test_locked_sanitize_strips_code_qty_ink(self) -> None:
        desig = "302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP"
        cleaned = sanitize_pharma_designation(
            desig,
            24,
            quantite_locked=True,
            code="302970",
        )
        self.assertIn("AMLODIPINE", cleaned.upper())
        self.assertNotIn("302970", cleaned)
        self.assertNotRegex(cleaned.strip(), r"^24\b")


if __name__ == "__main__":
    unittest.main()
