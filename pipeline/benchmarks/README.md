# Benchmark Harness

This folder stores evaluation artifacts for placement quality.

## Files
- `reference_ground_truth.json`: dataset cases and expected fields (fill progressively).
- `predictions/`: place extracted `*_data.json` outputs here.
- `latest_metrics.json`: produced by the benchmark runner.

## Run metrics

```powershell
python pipeline/benchmark_runner.py --truth pipeline/benchmarks/reference_ground_truth.json --predictions pipeline/benchmarks/predictions --out pipeline/benchmarks/latest_metrics.json
```

## Bootstrap initial predictions

```powershell
python pipeline/bootstrap_predictions.py --truth pipeline/benchmarks/reference_ground_truth.json --out-dir pipeline/benchmarks/predictions --overwrite
```

## Regression gate

```powershell
python pipeline/regression_gate.py --baseline pipeline/benchmarks/baseline_metrics.json --candidate pipeline/benchmarks/latest_metrics.json --min-delta 0.005
```

## Empty-field report on exported JSONs

```powershell
python pipeline/empty_field_report.py "C:\path\to\invoice1_data.json" "C:\path\to\invoice2_data.json" --out pipeline/benchmarks/empty_field_report.json
```
