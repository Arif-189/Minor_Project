"""Run and save the offline platform twin and Monte Carlo stress scenario."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from railway_delay.platforming import default_platforms, make_scenario, simulate_comparison, stress_test


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, help="CSV exported from the dashboard; needs predicted_delay_min")
    parser.add_argument("--station", default="NDLS", help="Target station label for this demo scenario")
    parser.add_argument("--movements", type=int, default=36, choices=range(20, 61))
    parser.add_argument("--platforms", type=int, default=6, choices=range(4, 9))
    parser.add_argument("--platform-length-m", type=float, default=700.0)
    parser.add_argument("--clearance-min", type=float, default=5.0)
    parser.add_argument("--demand", choices=["light", "moderate", "busy"], default="moderate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stress-runs", type=int, default=10_000, choices=[10_000])
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args()

    platforms = default_platforms(args.platforms, args.platform_length_m)
    prediction_rows = pd.read_csv(args.predictions) if args.predictions else None
    scenario = make_scenario(prediction_rows, n=args.movements, seed=args.seed, demand=args.demand,
                             platforms=platforms, clearance_min=args.clearance_min)
    result = simulate_comparison(scenario, platforms, args.clearance_min)
    stress = stress_test(scenario, runs=args.stress_runs, seed=args.seed + 2026,
                         platforms=platforms, clearance_min=args.clearance_min)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result["fcfs_schedule"].to_csv(args.output_dir / "fcfs_platform_schedule.csv", index=False)
    result["optimized_schedule"].to_csv(args.output_dir / "optimized_platform_schedule.csv", index=False)
    serializable = {k: v for k, v in result.items() if not k.endswith("_schedule")}
    serializable["stress_test"] = stress
    serializable["station_label"] = args.station
    (args.output_dir / "platform_twin_evaluation.json").write_text(
        json.dumps(serializable, indent=2, default=float), encoding="utf-8")
    print(json.dumps({"evaluation": str(args.output_dir / "platform_twin_evaluation.json"),
                      "fcfs_schedule": str(args.output_dir / "fcfs_platform_schedule.csv"),
                      "optimized_schedule": str(args.output_dir / "optimized_platform_schedule.csv"),
                      "fcfs_total_wait_min": result["fcfs"]["total_wait_min"],
                      "optimized_total_wait_min": result["optimized"]["total_wait_min"],
                      "stress_runs": stress["runs"],
                      "stress_p99_wait_min": stress["total_wait_min"]["p99"]}, indent=2))


if __name__ == "__main__":
    main()
