from __future__ import annotations

import unittest

from line_items_utils import legacy_line_merge_key


class TestLegacyLineMergeKey(unittest.TestCase):
    def test_distinguishes_same_pct_different_article(self) -> None:
        a = {"code_pct": "352730", "code_article": "PF000400001", "montant": 100.0, "designation": "DMAX"}
        b = {"code_pct": "352730", "code_article": "PF000400002", "montant": 200.0, "designation": "OTHER"}
        self.assertNotEqual(legacy_line_merge_key(a), legacy_line_merge_key(b))

    def test_row_snip_participates(self) -> None:
        x = {"code_pct": "1", "code_article": "", "montant": "", "designation": "A", "_row_txt": "row-a"}
        y = {"code_pct": "1", "code_article": "", "montant": "", "designation": "A", "_row_txt": "row-b"}
        self.assertNotEqual(legacy_line_merge_key(x), legacy_line_merge_key(y))


if __name__ == "__main__":
    unittest.main()
