from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass
class MetricBundle:
    field_total: int = 0
    field_match: int = 0
    line_item_total: int = 0
    line_item_match: int = 0
    placement_total: int = 0
    placement_match: int = 0
    quantite_total: int = 0
    quantite_empty: int = 0
    code_article_total: int = 0
    code_article_empty: int = 0
    designation_total: int = 0
    designation_polluted: int = 0

    def as_dict(self) -> Dict[str, float]:
        def ratio(numerator: int, denominator: int) -> float:
            return round(numerator / denominator, 4) if denominator else 0.0

        return {
            "field_accuracy": ratio(self.field_match, self.field_total),
            "line_item_accuracy": ratio(self.line_item_match, self.line_item_total),
            "placement_accuracy": ratio(self.placement_match, self.placement_total),
            "field_total": self.field_total,
            "line_item_total": self.line_item_total,
            "placement_total": self.placement_total,
            "quantite_empty_rate": ratio(self.quantite_empty, self.quantite_total),
            "code_article_empty_rate": ratio(self.code_article_empty, self.code_article_total),
            "designation_polluted_rate": ratio(self.designation_polluted, self.designation_total),
        }


def _normalize(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value).strip().lower()


def _read_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _compare_document_fields(expected: Dict, predicted: Dict, metrics: MetricBundle, mismatches: List[Dict[str, str]]) -> None:
    for key, exp_val in expected.items():
        metrics.field_total += 1
        pred_val = predicted.get(key)
        if _normalize(pred_val) == _normalize(exp_val):
            metrics.field_match += 1
        else:
            mismatches.append({"scope": "document", "field": key, "expected": str(exp_val), "predicted": str(pred_val)})


def _compare_line_items(expected: List[Dict], predicted: List[Dict], metrics: MetricBundle, mismatches: List[Dict[str, str]]) -> None:
    pred_by_code = {
        _normalize(item.get("code")): item for item in predicted if _normalize(item.get("code"))
    }
    for exp_item in expected:
        code = _normalize(exp_item.get("code"))
        if not code:
            continue
        pred_item = pred_by_code.get(code, {})
        for key, exp_val in exp_item.items():
            if key == "code":
                continue
            metrics.line_item_total += 1
            metrics.placement_total += 1
            pred_val = pred_item.get(key)
            if _normalize(pred_val) == _normalize(exp_val):
                metrics.line_item_match += 1
                metrics.placement_match += 1
            else:
                mismatches.append(
                    {
                        "scope": "line_item",
                        "code": code,
                        "field": key,
                        "expected": str(exp_val),
                        "predicted": str(pred_val),
                    }
                )

def _capture_prediction_quality(predicted: List[Dict], metrics: MetricBundle) -> None:
    noisy_tail_re = r'(\d{2}[\/\-.]\d{2}[\/\-.]\d{2,4}|\|\s*\d{1,5}\s*$)'
    for item in predicted or []:
        metrics.quantite_total += 1
        if _normalize(item.get("quantite")) == "":
            metrics.quantite_empty += 1
        metrics.code_article_total += 1
        if _normalize(item.get("code_article")) == "":
            metrics.code_article_empty += 1
        designation = str(item.get("designation", "") or "").strip()
        if designation:
            metrics.designation_total += 1
            if _normalize(designation) and re.search(noisy_tail_re, designation):
                metrics.designation_polluted += 1


def evaluate_case(truth_case: Dict, prediction: Dict) -> Dict[str, float]:
    metrics = MetricBundle()
    mismatches: List[Dict[str, str]] = []
    _compare_document_fields(truth_case.get("document", {}), prediction.get("document", {}), metrics, mismatches)
    _compare_line_items(truth_case.get("line_items", []), prediction.get("line_items", []), metrics, mismatches)
    _capture_prediction_quality(prediction.get("line_items", []), metrics)
    result = metrics.as_dict()
    result["mismatches"] = mismatches
    return result


def evaluate_suite(truth_path: Path, prediction_dir: Path) -> Dict[str, object]:
    truth = _read_json(truth_path)
    results: Dict[str, object] = {"cases": {}, "aggregate": {}}
    aggregate = MetricBundle()

    for case in truth.get("cases", []):
        case_id = case["id"]
        pred_path = prediction_dir / f"{case_id}_data.json"
        if not pred_path.exists():
            results["cases"][case_id] = {"error": f"missing_prediction:{pred_path.name}"}
            continue
        predicted = _read_json(pred_path)
        case_metrics = evaluate_case(case, predicted)
        results["cases"][case_id] = case_metrics
        aggregate.field_total += case_metrics["field_total"]
        aggregate.field_match += int(case_metrics["field_accuracy"] * case_metrics["field_total"])
        aggregate.line_item_total += case_metrics["line_item_total"]
        aggregate.line_item_match += int(case_metrics["line_item_accuracy"] * case_metrics["line_item_total"])
        aggregate.placement_total += case_metrics["placement_total"]
        aggregate.placement_match += int(case_metrics["placement_accuracy"] * case_metrics["placement_total"])

    results["aggregate"] = aggregate.as_dict()
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate invoice extraction predictions.")
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("pipeline/benchmarks/reference_ground_truth.json"),
        help="Ground-truth json file.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=Path("pipeline/benchmarks/predictions"),
        help="Directory containing *_data.json prediction files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("pipeline/benchmarks/latest_metrics.json"),
        help="Output path for computed metrics.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    results = evaluate_suite(args.truth, args.predictions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
