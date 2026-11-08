"""Train delay prediction from a local stop-level CSV or Hugging Face station sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from railway_delay.features import build_examples
from railway_delay.huggingface import fetch_station_corridor
from railway_delay.model import fit_and_evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="Local full run-history CSV; omit to fetch a bounded Hugging Face corridor sample.")
    parser.add_argument("--station", default="NDLS", help="Starting evaluation target station code (default: NDLS).")
    parser.add_argument("--stations", nargs="*", default=[], help="Additional target stations to include in corridor download, e.g. HWH BCT.")
    parser.add_argument("--max-trains-per-station", type=int, default=10)
    parser.add_argument("--max-index-rows", type=int, default=50000)
    parser.add_argument("--fallback-sample-rows", type=int, default=4000,
                        help="Rows sampled through the regular viewer endpoint if station filtering fails.")
    parser.add_argument("--output", default="output", help="Directory for model and evaluation.json.")
    parser.add_argument("--cache", default="data/cache/huggingface", help="Cache location for per-train source files.")
    args = parser.parse_args()

    if args.csv:
        raw = pd.read_csv(args.csv, dtype={"train_no": str}, low_memory=False)
    else:
        raw = fetch_station_corridor([args.station, *args.stations], args.cache,
                                     args.max_trains_per_station, args.max_index_rows,
                                     args.fallback_sample_rows)
    examples = build_examples(raw)
    print(f"Built {len(examples):,} one-stop-ahead examples across {examples['next_station_code'].nunique():,} target stations")
    results = fit_and_evaluate(examples, args.output, station=args.station,
                               source_rows=len(raw), source_files=int(raw["train_no"].nunique()))
    print(json.dumps(results, indent=2, allow_nan=False))
    print(f"Saved model and metrics under {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()

