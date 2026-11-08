"""Build leakage-safe one-stop-ahead examples from stop-level run history."""

from __future__ import annotations

import numpy as np
import pandas as pd


TARGET = "target_delay_min"
CATEGORICAL = ["train_type", "station_code", "next_station_code"]
NUMERIC = [
    "seq", "next_seq", "distance_to_next_km", "scheduled_run_min",
    "scheduled_dwell_min", "departure_delay_min", "arrival_delay_min",
    "day_of_week", "month", "is_weekend",
]
FEATURES = CATEGORICAL + NUMERIC


def build_examples(raw: pd.DataFrame) -> pd.DataFrame:
    """Create next-stop arrival-delay labels using information available at departure.

    A label is the next stop's reported arrival delay. Rows with an unreported
    target stop are dropped. `reported` is honored when present, as recommended
    by the dataset card. No actual arrival/departure timestamp or platform field
    is used as a predictor.
    """
    df = raw.copy()
    required = {"date", "train_no", "station_code", "seq", "delay_arrival_min",
                "delay_departure_min", "train_type", "sch_departure",
                "sch_arrival", "distance_km"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing required source columns: {', '.join(missing)}")

    if "reported" in df:
        df["_reported"] = pd.to_numeric(df["reported"], errors="coerce").fillna(0).eq(1)
    else:
        df["_reported"] = True
    df["seq"] = pd.to_numeric(df["seq"], errors="coerce")
    df["distance_km"] = pd.to_numeric(df["distance_km"], errors="coerce")
    df["delay_arrival_min"] = pd.to_numeric(df["delay_arrival_min"], errors="coerce")
    df["delay_departure_min"] = pd.to_numeric(df["delay_departure_min"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "seq", "station_code"])
    keys = ["train_no", "date"]
    if "reported_at" in df:
        df = df.sort_values(keys + ["seq", "reported", "reported_at"], kind="stable")
    df = df.drop_duplicates(keys + ["seq", "station_code"], keep="last")
    df = df.sort_values(keys + ["seq"], kind="stable")
    grouped = df.groupby(keys, sort=False, dropna=False)

    nxt = grouped["station_code"].shift(-1)
    target = grouped["delay_arrival_min"].shift(-1)
    next_reported = grouped["_reported"].shift(-1)
    next_seq = grouped["seq"].shift(-1)
    next_distance = grouped["distance_km"].shift(-1)
    next_arrival_date = grouped["sch_arrival_date"].shift(-1) if "sch_arrival_date" in df else pd.Series(pd.NaT, index=df.index)
    next_arrival_time = grouped["sch_arrival"].shift(-1)

    run_date = df["date"].dt.strftime("%Y-%m-%d")
    current_sched_date = df.get("sch_departure_date", run_date)
    next_sched_date = next_arrival_date.fillna(run_date)
    current_departure = pd.to_datetime(current_sched_date.astype(str) + " " + df["sch_departure"].astype(str), errors="coerce")
    following_arrival = pd.to_datetime(next_sched_date.astype(str) + " " + next_arrival_time.astype(str), errors="coerce")
    run_min = (following_arrival - current_departure).dt.total_seconds() / 60
    run_min = run_min.where(run_min >= 0, run_min + 24 * 60)

    if "sch_arrival_date" in df:
        scheduled_arrival = pd.to_datetime(df["sch_arrival_date"].astype(str) + " " + df["sch_arrival"].astype(str), errors="coerce")
        scheduled_departure = pd.to_datetime(df.get("sch_departure_date", df["sch_arrival_date"]).astype(str) + " " + df["sch_departure"].astype(str), errors="coerce")
        dwell_min = (scheduled_departure - scheduled_arrival).dt.total_seconds() / 60
        dwell_min = dwell_min.where(dwell_min >= 0, dwell_min + 24 * 60)
    else:
        dwell_min = np.nan

    examples = pd.DataFrame(index=df.index)
    examples["date"] = df["date"]
    examples["train_no"] = df["train_no"].astype(str)
    examples["train_type"] = df["train_type"].fillna("UNKNOWN").astype(str)
    examples["station_code"] = df["station_code"].astype(str).str.upper()
    examples["next_station_code"] = nxt.astype("string").str.upper()
    examples["seq"] = df["seq"]
    examples["next_seq"] = next_seq
    examples["distance_to_next_km"] = next_distance - df["distance_km"]
    examples["scheduled_run_min"] = run_min
    examples["scheduled_dwell_min"] = dwell_min
    examples["departure_delay_min"] = df["delay_departure_min"]
    examples["arrival_delay_min"] = df["delay_arrival_min"]
    examples["day_of_week"] = df["date"].dt.dayofweek
    examples["month"] = df["date"].dt.month
    examples["is_weekend"] = (df["date"].dt.dayofweek >= 5).astype(int)
    examples[TARGET] = pd.to_numeric(target, errors="coerce")
    examples["_valid_pair"] = df["_reported"].to_numpy() & next_reported.fillna(False).to_numpy()
    examples = examples.replace([np.inf, -np.inf], np.nan)
    examples = examples[examples["_valid_pair"]].drop(columns="_valid_pair")
    examples = examples.dropna(subset=[TARGET, "next_station_code", "departure_delay_min"])
    examples = examples[examples[TARGET] >= 0].reset_index(drop=True)
    return examples

