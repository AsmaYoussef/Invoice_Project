from __future__ import annotations

import unittest

from ocr_line_clean import is_proforma_pct_token
from parsers.v2_pharmasud import parse_pharmasud_line
from parsers.v2_proforma import parse_proforma_line, parse_proforma_lines, salvage_proforma_line
from parsers.v2_simple_bc import parse_simple_bc_line


class TestV2Parsers(unittest.TestCase):
    def test_simple_bc_qty_not_second_token(self) -> None:
        row = parse_simple_bc_line("301500 216 ADEX LP 1.5MG B/30 CP")
        assert row is not None
        self.assertEqual(row.code, "301500")
        self.assertEqual(row.quantite, "216")

    def test_proforma_outside_in(self) -> None:
        line = "352730 PF000400001 DMAX 200000 U UML AMP 12 1 234,56 14 567,89"
        row = parse_proforma_line(line)
        assert row is not None
        self.assertEqual(row.code_pct, "352730")
        self.assertEqual(row.code_article, "PF000400001")
        self.assertEqual(row.quantite, "12")
        self.assertIn("1234", row.prix_unitaire.replace(" ", ""))
        self.assertIn("14567", row.montant.replace(" ", ""))

    def test_pharmasud_date_anchor(self) -> None:
        row = parse_pharmasud_line("AB1234  PARACETAMOL 500MG  48  2  31/12/2026  24")
        assert row is not None
        self.assertEqual(row.date_peremption, "31/12/2026")
        self.assertEqual(row.quantite_commande, "48")
        self.assertEqual(row.nb_cartons, "2")

    def test_proforma_salvage_keeps_bad_trailer_line(self) -> None:
        bad = "352730 PF009900011 SOME PRODUCT NAME WITHOUT VALID MONEY TRAILER"
        salv = salvage_proforma_line(bad)
        assert salv is not None
        self.assertEqual(salv.code_pct, "352730")
        self.assertEqual(salv.code_article, "PF009900011")
        self.assertEqual(salv.quantite, "")
        body = "352730 PF000400001 OK 12 1 234,56 14 567,89\n" + bad
        rows = parse_proforma_lines(body)
        self.assertGreaterEqual(len(rows), 2)
        raw_lines = {r["raw_line"].strip() for r in rows}
        self.assertIn(bad.strip(), raw_lines)

    def test_is_proforma_pct_rejects_french_money(self) -> None:
        self.assertFalse(is_proforma_pct_token("123,45"))
        self.assertFalse(is_proforma_pct_token("1 234,56"))
        self.assertTrue(is_proforma_pct_token("352730"))

    def test_proforma_skips_leading_money_for_code_pct(self) -> None:
        line = "123,45 352730 PF000400001 DMAX 12 1 234,56 14 567,89"
        row = parse_proforma_line(line)
        assert row is not None
        self.assertEqual(row.code_pct, "352730")
        self.assertEqual(row.code_article, "PF000400001")
        self.assertNotEqual(row.code_pct, "12345")

    def test_salvage_rejects_footer_without_pf(self) -> None:
        footer = "Total HT 1 234,56 TVA 560,12 Montant TTC 1 794,68"
        self.assertIsNone(salvage_proforma_line(footer))
        self.assertEqual(parse_proforma_lines(footer), [])

    def test_proforma_dot_decimal_money(self) -> None:
        line = "352730 PF000400001 DMAX 200000 U 12 1234.56 7890.12"
        row = parse_proforma_line(line)
        assert row is not None
        self.assertEqual(row.quantite, "12")
        self.assertIn("1234", row.prix_unitaire.replace(",", "."))
        self.assertIn("7890", row.montant.replace(",", "."))


if __name__ == "__main__":
    unittest.main()
