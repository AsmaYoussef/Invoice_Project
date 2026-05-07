from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List


def _is_empty(value) -> bool:
    return str(value or "").strip() in {"", "None", "nan", "—"}


def analyze_payload_v1(payload: Dict) -> Dict[str, float]:
    items = payload.get("line_items", []) or []
    total = len(items)
    if total == 0:
        return {
            "schema": 1,
            "rows": 0,
            "quantite_empty_rate": 0.0,
            "code_article_empty_rate": 0.0,
            "date_empty_rate": 0.0,
            "designation_polluted_rate": 0.0,
        }

    quantite_empty = 0
    code_article_empty = 0
    date_empty = 0
    designation_polluted = 0
    noisy_tail_re = re.compile(r"(\d{2}[\/\-.]\d{2}[\/\-.]\d{2,4}|[|]\s*\d{1,5}\s*$)")

    for row in items:
        if _is_empty(row.get("quantite")):
            quantite_empty += 1
        if _is_empty(row.get("code_article")):
            code_article_empty += 1
        if _is_empty(row.get("date_peremption")):
            date_empty += 1
        designation = str(row.get("designation", "") or "")
        if designation and noisy_tail_re.search(designation):
            designation_polluted += 1

    def pct(n: int) -> float:
        return round(n / total, 4)

    return {
        "schema": 1,
        "rows": total,
        "quantite_empty_rate": pct(quantite_empty),
        "code_article_empty_rate": pct(code_article_empty),
        "date_empty_rate": pct(date_empty),
        "designation_polluted_rate": pct(designation_polluted),
    }


def analyze_payload_v2(payload: Dict) -> Dict[str, object]:
    family = str(payload.get("invoice_family") or "unknown")
    items: List[dict] = list(payload.get("line_items") or [])
    total = len(items)
    if total == 0:
        return {
            "schema": 2,
            "invoice_family": family,
            "rows": 0,
            "v2_critical_empty_rate": 0.0,
            "v2_by_field": {},
        }

    crit_empty = 0
    by_field: Dict[str, int] = {}

    def bump(field: str) -> None:
        by_field[field] = by_field.get(field, 0) + 1

    for row in items:
        miss_row = False
        if family == "proforma_modele":
            for f in ("prix_unitaire", "montant"):
                if _is_empty(row.get(f)):
                    bump(f)
                    miss_row = True
        elif family in ("bc_avenir", "bc_omnipharm"):
            if _is_empty(row.get("quantite")):
                bump("quantite")
                miss_row = True
        elif family == "bc_pharmasud":
            for f in ("date_peremption", "quantite_commande"):
                if _is_empty(row.get(f)):
                    bump(f)
                    miss_row = True
        else:
            if _is_empty(row.get("code")) and _is_empty(row.get("code_pct")):
                bump("code")
                miss_row = True
        if miss_row:
            crit_empty += 1

    def pct(n: int) -> float:
        return round(n / total, 4)

    rates = {k: pct(v) for k, v in by_field.items()}
    return {
        "schema": 2,
        "invoice_family": family,
        "rows": total,
        "v2_critical_empty_rate": pct(crit_empty),
        "v2_by_field": rates,
    }


def analyze_payload(payload: Dict) -> Dict[str, object]:
    if int(payload.get("schema_version") or 0) == 2:
        return analyze_payload_v2(payload)
    return analyze_payload_v1(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute empty-field and field-crush indicators for extracted JSON files.")
    parser.add_argument("files", nargs="+", type=Path, help="Paths to *_data.json files.")
    parser.add_argument("--out", type=Path, default=Path("pipeline/benchmarks/empty_field_report.json"))
    args = parser.parse_args()

    out: Dict[str, object] = {"files": {}, "aggregate": {}}
    agg_v1 = {
        "rows": 0,
        "quantite_empty": 0.0,
        "code_article_empty": 0.0,
        "date_empty": 0.0,
        "designation_polluted": 0.0,
    }
    agg_v2_rows = 0
    agg_v2_crit = 0.0
    agg_v2_by_family: Dict[str, Dict[str, object]] = {}
    weighted_den_v1 = 0

    for file_path in args.files:
        with file_path.open("r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        stats = analyze_payload(payload)
        out["files"][str(file_path)] = stats
        rows = int(stats.get("rows", 0))
        if stats.get("schema") == 2 and rows > 0:
            agg_v2_rows += rows
            agg_v2_crit += float(stats.get("v2_critical_empty_rate", 0)) * rows
            fam = str(stats.get("invoice_family", "unknown"))
            slot = agg_v2_by_family.setdefault(fam, {"rows": 0, "v2_critical_empty": 0.0, "fields": {}})
            slot["rows"] = int(slot["rows"]) + rows
            slot["v2_critical_empty"] += float(stats.get("v2_critical_empty_rate", 0)) * rows
            for fk, fv in (stats.get("v2_by_field") or {}).items():
                fd = slot["fields"]
                fd[fk] = fd.get(fk, 0.0) + float(fv) * rows
        elif rows > 0:
            weighted_den_v1 += rows
            agg_v1["rows"] += rows
            agg_v1["quantite_empty"] += float(stats.get("quantite_empty_rate", 0)) * rows
            agg_v1["code_article_empty"] += float(stats.get("code_article_empty_rate", 0)) * rows
            agg_v1["date_empty"] += float(stats.get("date_empty_rate", 0)) * rows
            agg_v1["designation_polluted"] += float(stats.get("designation_polluted_rate", 0)) * rows

    if weighted_den_v1 > 0:
        out["aggregate"]["v1"] = {
            "rows": agg_v1["rows"],
            "quantite_empty_rate": round(agg_v1["quantite_empty"] / weighted_den_v1, 4),
            "code_article_empty_rate": round(agg_v1["code_article_empty"] / weighted_den_v1, 4),
            "date_empty_rate": round(agg_v1["date_empty"] / weighted_den_v1, 4),
            "designation_polluted_rate": round(agg_v1["designation_polluted"] / weighted_den_v1, 4),
        }
    else:
        out["aggregate"]["v1"] = {
            "rows": 0,
            "quantite_empty_rate": 0.0,
            "code_article_empty_rate": 0.0,
            "date_empty_rate": 0.0,
            "designation_polluted_rate": 0.0,
        }

    if agg_v2_rows > 0:
        by_fam_out = {}
        for fam, slot in agg_v2_by_family.items():
            r = int(slot["rows"])
            if r <= 0:
                continue
            fields_norm = {k: round(v / r, 4) for k, v in slot["fields"].items()}
            by_fam_out[fam] = {
                "rows": r,
                "v2_critical_empty_rate": round(float(slot["v2_critical_empty"]) / r, 4),
                "v2_by_field": fields_norm,
            }
        out["aggregate"]["v2"] = {
            "rows": agg_v2_rows,
            "v2_critical_empty_rate": round(agg_v2_crit / agg_v2_rows, 4),
            "per_family": by_fam_out,
        }
    else:
        out["aggregate"]["v2"] = {"rows": 0, "v2_critical_empty_rate": 0.0, "per_family": {}}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
