"""Create separate, model-ready next-stop datasets for selected target stations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from railway_delay.features import FEATURES, TARGET, build_examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default="data/cache/huggingface",
                        help="Folder containing cached per-train Hugging Face CSV files.")
    parser.add_argument("--csv", help="Optional single raw stop-history CSV to use instead of cached files.")
    parser.add_argument("--stations", nargs="+", default=["NDLS", "AGC", "GWL"],
                        help="Target station codes; defaults to NDLS AGC GWL.")
    parser.add_argument("--output-dir", default="data/processed/stations")
    args = parser.parse_args()

    if args.csv:
        paths = [Path(args.csv)]
    else:
        paths = sorted(Path(args.source_dir).glob("**/*.csv"))
    if not paths:
        raise SystemExit(f"No raw train-history CSV files found under {args.source_dir}.")

    chunks = [pd.read_csv(path, dtype={"train_no": str}, low_memory=False) for path in paths]
    raw = pd.concat(chunks, ignore_index=True)
    examples = build_examples(raw)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    summary = []
    for requested in args.stations:
        station = requested.strip().upper()
        subset = examples[examples["next_station_code"].str.upper().eq(station)].copy()
        if subset.empty:
            print(f"{station}: no target examples in the selected source files; skipped.")
            continue
        destination = output / f"{station}.csv"
        columns = ["date", "train_no", *FEATURES, TARGET]
        subset = subset[columns].sort_values(["date", "train_no", "seq"], kind="stable")
        subset.to_csv(destination, index=False)
        record = {
            "station_code": station,
            "examples": int(len(subset)),
            "trains": int(subset["train_no"].nunique()),
            "journey_dates": int(pd.to_datetime(subset["date"]).nunique()),
            "date_start": str(pd.to_datetime(subset["date"]).min().date()),
            "date_end": str(pd.to_datetime(subset["date"]).max().date()),
            "file": destination.as_posix(),
        }
        summary.append(record)
        print(f"{station}: wrote {len(subset):,} examples from {record['trains']} trains to {destination}")

    if not summary:
        raise SystemExit("None of the requested stations appeared in the source files.")
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps({"source_files": len(paths), "source_rows": len(raw),
                                        "engineered_examples": len(examples),
                                        "station_datasets": summary}, indent=2), encoding="utf-8")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()

