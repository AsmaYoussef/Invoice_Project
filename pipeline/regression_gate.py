from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _get_score(payload: dict, key: str) -> float:
    return float(payload.get("aggregate", {}).get(key, 0.0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Regression gate for extraction metrics.")
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline metrics JSON.")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate metrics JSON.")
    parser.add_argument("--min-delta", type=float, default=0.0, help="Minimum required placement_accuracy delta.")
    args = parser.parse_args()

    baseline = _read(args.baseline)
    candidate = _read(args.candidate)

    base = _get_score(baseline, "placement_accuracy")
    cand = _get_score(candidate, "placement_accuracy")
    delta = cand - base

    payload = {
        "baseline_placement_accuracy": base,
        "candidate_placement_accuracy": cand,
        "delta": round(delta, 6),
        "required_delta": args.min_delta,
        "pass": delta >= args.min_delta,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
