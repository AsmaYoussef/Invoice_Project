import unittest

from pipeline.benchmark_runner import evaluate_case


class BenchmarkRunnerTests(unittest.TestCase):
    def test_evaluate_case_reports_mismatch_snapshot(self):
        truth_case = {
            "document": {"numero": "BCN-XX-1234"},
            "line_items": [{"code": "301500", "quantite": 216}],
        }
        prediction = {
            "document": {"numero": "BCN-XX-9999"},
            "line_items": [{"code": "301500", "quantite": 200}],
        }
        result = evaluate_case(truth_case, prediction)
        self.assertGreaterEqual(len(result["mismatches"]), 2)
        self.assertEqual(result["field_total"], 1)
        self.assertEqual(result["line_item_total"], 1)


if __name__ == "__main__":
    unittest.main()
