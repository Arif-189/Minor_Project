"""Use a saved pooled or station-specific model on feature rows in a CSV."""

from __future__ import annotations

import argparse

import joblib
import numpy as np
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Path to all_station_delay_model.joblib or a station-specific model.")
    parser.add_argument("--input", required=True, help="CSV with the model feature columns.")
    parser.add_argument("--output", default="predictions.csv")
    args = parser.parse_args()

    bundle = joblib.load(args.model)
    features = bundle["features"]
    rows = pd.read_csv(args.input)
    missing = sorted(set(features) - set(rows.columns))
    if missing:
        raise SystemExit("Input is missing model feature columns: " + ", ".join(missing))
    estimate = bundle["model"].predict(rows[features])
    radius = float(bundle["interval_abs_error_q90_min"])
    rows["predicted_delay_min"] = estimate
    rows["delay_lower_90_min"] = np.maximum(estimate - radius, 0)
    rows["delay_upper_90_min"] = estimate + radius
    rows.to_csv(args.output, index=False)
    print(f"Wrote {len(rows)} predictions to {args.output}")


if __name__ == "__main__":
    main()
