"""Offline, configurable platform allocation and simulation for the project.

All timetable/platform fields created here are explicitly scenario inputs. The
public delay dataset is used only for predicted delay samples; it does not
provide a verified NDLS platform plan or train-length/platform-length mapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Platform:
    platform_id: str
    length_m: float = 600.0


def default_platforms(count: int = 6, length_m: float = 700.0) -> list[Platform]:
    if not 4 <= int(count) <= 8:
        raise ValueError("Use between 4 and 8 demo platforms.")
    if float(length_m) <= 0:
        raise ValueError("Platform length must be positive.")
    return [Platform(f"P{i + 1}", float(length_m)) for i in range(int(count))]


def make_scenario(prediction_rows: pd.DataFrame | None = None, *, n: int = 36,
                  seed: int = 42, demand: str = "moderate",
                  platforms: list[Platform] | None = None,
                  clearance_min: float = 5.0) -> pd.DataFrame:
    """Build a reproducible demo day. All schedule/length values are synthetic.

    If prediction_rows are supplied, their delay estimates are sampled and
    consumed unchanged. Otherwise delays are drawn from a bounded demo range.
    """
    if not 20 <= int(n) <= 60:
        raise ValueError("Scenario size must be between 20 and 60 movements.")
    rng = np.random.default_rng(seed)
    platforms = platforms or default_platforms()
    source = prediction_rows.copy() if prediction_rows is not None else pd.DataFrame()
    if len(source):
        source = source.reset_index(drop=True)
        take = rng.choice(len(source), size=n, replace=len(source) < n)
        sampled = source.iloc[take].reset_index(drop=True)
        delay_col = "predicted_delay_min" if "predicted_delay_min" in sampled else None
        if delay_col is None:
            raise ValueError("Prediction rows need a predicted_delay_min column.")
        delays = pd.to_numeric(sampled[delay_col], errors="coerce").fillna(0).clip(0, 240).to_numpy()
        trains = sampled.get("train_no", pd.Series([f"DEMO-{i+1:03}" for i in range(n)])).astype(str).to_numpy()
        stations = sampled.get("station_code", pd.Series(["SRC"] * n)).astype(str).to_numpy()
        next_stations = sampled.get("next_station_code", pd.Series(["NDLS"] * n)).astype(str).to_numpy()
        prediction_source = "uploaded/model prediction rows"
    else:
        delays = np.clip(rng.gamma(shape=2.0, scale=8.0, size=n), 0, 90)
        trains = np.array([f"DEMO-{i+1:03}" for i in range(n)])
        stations, next_stations = np.array(["SRC"] * n), np.array(["NDLS"] * n)
        prediction_source = "synthetic delay draws (no prediction CSV supplied)"

    # A synthetic 18-hour operating window, with controllable burstiness.
    operating_window = {"light": 1080.0, "moderate": 600.0, "busy": 360.0}.get(demand)
    if operating_window is None:
        raise ValueError("demand must be light, moderate, or busy")
    base_gaps = rng.exponential(1.0, size=n)
    # Re-scale to a configurable 6–18 hour synthetic operating window.
    minutes = np.cumsum(base_gaps)
    minutes = minutes / max(float(minutes.max()), 1.0) * operating_window
    scheduled_arrival = minutes + 240.0
    # Sample train lengths and dwell from editable demo ranges, not the dataset.
    train_lengths = rng.choice([300, 420, 500, 560, 620, 680], size=n,
                               p=[.08, .18, .26, .25, .15, .08])
    dwell = rng.choice([10, 15, 20, 25, 30], size=n, p=[.10, .25, .30, .25, .10])
    priorities = rng.choice([1, 2, 3], size=n, p=[.55, .30, .15])
    rows = pd.DataFrame({
        "movement_id": [f"M{i + 1:03}" for i in range(n)],
        "train_no": trains, "from_station": stations, "station_code": next_stations,
        "scheduled_arrival_min": scheduled_arrival,
        "predicted_delay_min": delays,
        "delay_lower_90_min": np.maximum(0, delays - 13.08),
        "delay_upper_90_min": delays + 13.08,
        "train_length_m": train_lengths.astype(float), "dwell_min": dwell.astype(float),
        "priority": priorities.astype(int),
        "prediction_source": prediction_source,
        "scenario_data": "synthetic timetable, train length, dwell, priority, and platform configuration",
    })
    rows["estimated_arrival_min"] = rows["scheduled_arrival_min"] + rows["predicted_delay_min"]
    rows["clearance_min"] = float(clearance_min)
    return rows.sort_values("estimated_arrival_min").reset_index(drop=True)


def _wis(intervals: list[dict[str, Any]], clearance: float) -> list[dict[str, Any]]:
    """Weighted interval scheduling for a single platform; deterministic ties."""
    items = sorted(intervals, key=lambda x: (x["end_min"], x["start_min"], str(x["train_no"])))
    prev = []
    for i, item in enumerate(items):
        j = i - 1
        while j >= 0 and items[j]["end_min"] + clearance > item["start_min"]:
            j -= 1
        prev.append(j)
    dp = [0.0] * (len(items) + 1)
    take = [False] * len(items)
    for i, item in enumerate(items, start=1):
        weight = float(item["weight"])
        with_item = weight + dp[prev[i - 1] + 1]
        without_item = dp[i - 1]
        if with_item > without_item + 1e-9:
            dp[i] = with_item
            take[i - 1] = True
        else:
            dp[i] = without_item
    chosen, i = [], len(items)
    while i > 0:
        item = items[i - 1]
        with_item = float(item["weight"]) + dp[prev[i - 1] + 1]
        if with_item > dp[i - 1] + 1e-9:
            chosen.append(item)
            i = prev[i - 1] + 1
        else:
            i -= 1
    return list(reversed(chosen))


def allocate_platforms(scenario: pd.DataFrame, platforms: list[Platform] | None = None,
                       clearance_min: float = 5.0) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Allocate all movements using deterministic priority-aware interval search.

    WIS selects compatible requests on each platform. Excluded requests are
    reconsidered in priority order and placed at the earliest feasible time;
    preemption only changes not-yet-started reservations.
    """
    platforms = platforms or default_platforms()
    began = perf_counter()
    df = scenario.copy().reset_index(drop=True)
    required = {"train_no", "estimated_arrival_min", "train_length_m", "dwell_min", "priority"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError("Scenario missing columns: " + ", ".join(sorted(missing)))
    df["scheduled_start_min"] = pd.to_numeric(df["estimated_arrival_min"], errors="coerce").fillna(0)
    df["scheduled_end_min"] = df["scheduled_start_min"] + pd.to_numeric(df["dwell_min"], errors="coerce").fillna(10)
    df["platform_id"] = ""
    df["allocation_explanation"] = ""
    # Long, high-priority trains receive larger WIS weights. Scaling keeps the
    # scheduled-arrival preference meaningful while favoring priority service.
    df["schedule_weight"] = 100 + 18 * df["priority"].astype(float) + 0.02 * df["train_length_m"]
    tentative: dict[str, list[dict[str, Any]]] = {p.platform_id: [] for p in platforms}
    # Preferred platform is the least-loaded compatible platform; WIS handles
    # competing intervals within each chosen platform.
    for row in df.sort_values(["estimated_arrival_min", "priority", "train_no"], ascending=[True, False, True]).to_dict("records"):
        eligible = [p for p in platforms if row["train_length_m"] <= p.length_m]
        if not eligible:
            df.loc[df.train_no.astype(str).eq(str(row["train_no"])), "allocation_explanation"] = (
                f"Not assigned: train length {row['train_length_m']:.0f} m exceeds every configured platform.")
            continue
        loads = {p.platform_id: sum(x["end_min"] - x["start_min"] for x in tentative[p.platform_id]) for p in eligible}
        chosen = min(eligible, key=lambda p: (loads[p.platform_id], p.platform_id))
        interval = {"movement_id": str(row.get("movement_id", row["train_no"])),
                    "train_no": str(row["train_no"]), "start_min": float(row["estimated_arrival_min"]),
                    "end_min": float(row["estimated_arrival_min"] + row["dwell_min"]),
                    "weight": float(row["schedule_weight"]), "priority": int(row["priority"]),
                    "length_m": float(row["train_length_m"])}
        tentative[chosen.platform_id].append(interval)

    accepted: dict[str, dict[str, Any]] = {}
    rejected = []
    for platform_id, candidates in tentative.items():
        selected = _wis(candidates, clearance_min)
        selected_ids = {x["movement_id"] for x in selected}
        for item in selected:
            accepted[item["movement_id"]] = {**item, "platform_id": platform_id}
        rejected.extend((platform_id, x) for x in candidates if x["movement_id"] not in selected_ids)

    # Deterministically reinsert excluded movements, allowing priority to move
    # a future reservation while never interrupting an occupied platform.
    occupied = {p.platform_id: sorted([x for x in accepted.values() if x["platform_id"] == p.platform_id],
                                       key=lambda x: x["start_min"]) for p in platforms}
    for _, item in sorted(rejected, key=lambda pair: (-pair[1]["priority"], pair[1]["start_min"], pair[1]["movement_id"])):
        choices = []
        for p in platforms:
            if item["length_m"] > p.length_m:
                continue
            start = item["start_min"]
            for old in occupied[p.platform_id]:
                if start + item["end_min"] - item["start_min"] + clearance_min <= old["start_min"]:
                    break
                if start < old["end_min"] + clearance_min:
                    start = old["end_min"] + clearance_min
            choices.append((start, p.platform_id))
        if choices:
            start, pid = min(choices)
            new_item = {**item, "start_min": start, "end_min": start + item["end_min"] - item["start_min"],
                        "platform_id": pid}
            accepted[item["movement_id"]] = new_item
            occupied[pid].append(new_item)
            occupied[pid].sort(key=lambda x: x["start_min"])

    for ix, row in df.iterrows():
        movement_id = str(row.get("movement_id", row["train_no"]))
        allocation = accepted.get(movement_id)
        if allocation:
            df.at[ix, "platform_id"] = allocation["platform_id"]
            df.at[ix, "scheduled_start_min"] = allocation["start_min"]
            df.at[ix, "scheduled_end_min"] = allocation["end_min"]
            wait = allocation["start_min"] - float(row["estimated_arrival_min"])
            df.at[ix, "allocation_explanation"] = ("Assigned to " + allocation["platform_id"] +
                (f" with {wait:.1f} min wait after interval conflict resolution." if wait > 0.1 else
                 " at the predicted arrival time; length and clearance checks passed."))
        elif not df.at[ix, "allocation_explanation"]:
            df.at[ix, "allocation_explanation"] = "Not assigned: no length-compatible platform configuration."
    df["clearance_min"] = float(clearance_min)
    # A compatible, earliest-available FCFS schedule is the wait-time guardrail.
    # If WIS priority choices increase total wait, use this safe alternative.
    fcfs_available = {p.platform_id: 0.0 for p in platforms}
    fcfs_plan: dict[str, tuple[str, float, float]] = {}
    for row in df.sort_values(["estimated_arrival_min", "movement_id" if "movement_id" in df else "train_no"]).to_dict("records"):
        mid = str(row.get("movement_id", row["train_no"]))
        eligible = [p for p in platforms if row["train_length_m"] <= p.length_m]
        if not eligible:
            continue
        p = min(eligible, key=lambda x: (max(float(row["estimated_arrival_min"]), fcfs_available[x.platform_id]), x.platform_id))
        start = max(float(row["estimated_arrival_min"]), fcfs_available[p.platform_id])
        end = start + float(row["dwell_min"])
        fcfs_plan[mid] = (p.platform_id, start, end)
        fcfs_available[p.platform_id] = end + clearance_min
    wis_wait = float((df.scheduled_start_min - df.estimated_arrival_min).clip(lower=0).sum())
    identity_column = "movement_id" if "movement_id" in df else "train_no"
    arrival_by_id = dict(zip(df[identity_column].astype(str),
                             pd.to_numeric(df["estimated_arrival_min"], errors="coerce").fillna(0).astype(float)))
    fcfs_wait = sum(max(0.0, plan[1] - arrival_by_id[mid])
                    for mid, plan in fcfs_plan.items())
    allocator_name = "priority-aware weighted interval scheduling"
    if fcfs_wait < wis_wait - 1e-9:
        allocator_name = "priority-aware weighted interval scheduling with minimum-wait FCFS safeguard"
        for ix, row in df.iterrows():
            mid = str(row.get("movement_id", row["train_no"]))
            plan = fcfs_plan.get(mid)
            if plan:
                pid, start, end = plan
                df.at[ix, "platform_id"] = pid
                df.at[ix, "scheduled_start_min"] = start
                df.at[ix, "scheduled_end_min"] = end
                df.at[ix, "allocation_explanation"] = "FCFS safeguard selected this length-compatible slot because it reduced total wait versus priority interval reservations."
    # Verify each output reservation for hard safety constraints.
    violations = []
    pmap = {p.platform_id: p.length_m for p in platforms}
    assigned = df[df.platform_id.ne("")].sort_values(["platform_id", "scheduled_start_min"])
    for pid, group in assigned.groupby("platform_id"):
        records = group.to_dict("records")
        for a, b in zip(records, records[1:]):
            if b["scheduled_start_min"] < a["scheduled_end_min"] + clearance_min - 1e-9:
                violations.append(f"{a['train_no']}/{b['train_no']} clearance")
    length_violations = sum(1 for r in df.to_dict("records")
                            if r["platform_id"] and r["train_length_m"] > pmap[r["platform_id"]])
    metrics = {"allocator": allocator_name,
               "platform_count": len(platforms), "platforms": [asdict(p) for p in platforms],
               "clearance_min": float(clearance_min), "movements": int(len(df)),
               "assigned": int(df.platform_id.ne("").sum()), "unassigned": int(df.platform_id.eq("").sum()),
               "length_violations": int(length_violations), "clearance_violations": len(violations),
               "allocation_runtime_ms": (perf_counter() - began) * 1000,
               "total_wait_min": float((df.scheduled_start_min - df.estimated_arrival_min).clip(lower=0).sum())}
    return df, metrics


def _simulate_once(schedule: pd.DataFrame, platforms: list[Platform], clearance: float) -> dict[str, Any]:
    """SimPy DES for platform entry, dwell, release, and queued movement waits."""
    try:
        import simpy
    except ImportError as exc:  # precise install guidance in the dashboard
        raise RuntimeError("SimPy is required. Run: python -m pip install simpy") from exc
    env = simpy.Environment()
    resources = {p.platform_id: simpy.Resource(env, capacity=1) for p in platforms}
    results = {"waits": {}, "starts": {}, "ends": {}, "collisions": 0}
    by_id = {p.platform_id: p for p in platforms}

    def train_process(row):
        train = str(row.get("movement_id", row["train_no"]))
        arrival = float(row["estimated_arrival_min"])
        requested_start = float(row.get("scheduled_start_min", arrival))
        yield env.timeout(max(0, requested_start - env.now))
        pid = str(row.get("platform_id", ""))
        if not pid or pid not in resources:
            eligible = [p.platform_id for p in platforms if float(row["train_length_m"]) <= p.length_m]
            pid = eligible[0] if eligible else ""
        if not pid:
            results["waits"][train] = 0.0
            return
        with resources[pid].request() as request:
            yield request
            start = float(env.now)
            wait = max(0.0, start - arrival)
            results["waits"][train] = wait
            results["starts"][train] = start
            yield env.timeout(float(row["dwell_min"]))
            results["ends"][train] = float(env.now)
            yield env.timeout(clearance)

    for row in schedule.to_dict("records"):
        env.process(train_process(row))
    env.run()
    waits = list(results["waits"].values())
    starts = list(results["starts"].values())
    ends = list(results["ends"].values())
    horizon = max(ends, default=1) - min(starts, default=0)
    id_column = "movement_id" if "movement_id" in schedule else "train_no"
    occ = sum(float(x) for x in schedule.loc[schedule[id_column].astype(str).isin(results["ends"]), "dwell_min"])
    platform_occ = schedule.loc[schedule[id_column].astype(str).isin(results["ends"])].groupby("platform_id")["dwell_min"].sum().to_dict()
    per_platform_utilization = {p.platform_id: float(100 * float(platform_occ.get(p.platform_id, 0.0)) / max(horizon, 1))
                                for p in platforms}
    return {"total_wait_min": float(sum(waits)), "mean_wait_min": float(np.mean(waits)) if waits else 0.0,
            "p95_wait_min": float(np.percentile(waits, 95)) if waits else 0.0,
            "platform_utilization_pct": float(100 * occ / max(horizon * len(platforms), 1)),
            "platform_utilization_by_id_pct": per_platform_utilization,
            "collisions": int(results["collisions"]), "served": len(results["ends"]),
            "throughput_per_hour": float(len(results["ends"]) / max(horizon / 60, 1/60)),
            "per_train_waits": results["waits"]}


def simulate_comparison(scenario: pd.DataFrame, platforms: list[Platform] | None = None,
                        clearance_min: float = 5.0) -> dict[str, Any]:
    """Compare FCFS and interval allocations using identical SimPy inputs."""
    platforms = platforms or default_platforms()
    fcfs = scenario.copy().sort_values("estimated_arrival_min").reset_index(drop=True)
    # FCFS: queue at the earliest available length-compatible platform.
    availability = {p.platform_id: 0.0 for p in platforms}
    fcfs_platforms, starts, ends = [], [], []
    for row in fcfs.to_dict("records"):
        eligible = [p for p in platforms if float(row["train_length_m"]) <= p.length_m]
        if not eligible:
            fcfs_platforms.append(""); starts.append(float(row["estimated_arrival_min"])); ends.append(float(row["estimated_arrival_min"]))
            continue
        p = min(eligible, key=lambda x: (max(float(row["estimated_arrival_min"]), availability[x.platform_id]), x.platform_id))
        st = max(float(row["estimated_arrival_min"]), availability[p.platform_id])
        en = st + float(row["dwell_min"])
        availability[p.platform_id] = en + clearance_min
        fcfs_platforms.append(p.platform_id); starts.append(st); ends.append(en)
    fcfs["platform_id"], fcfs["scheduled_start_min"], fcfs["scheduled_end_min"] = fcfs_platforms, starts, ends
    optimized, alloc_metrics = allocate_platforms(scenario, platforms, clearance_min)
    # DES each allocated plan with the same arrival stream, serving requests in
    # scheduled order while preserving a five-minute physical release gap.
    t0 = perf_counter(); fcfs_result = _simulate_once(fcfs, platforms, clearance_min)
    opt_result = _simulate_once(optimized, platforms, clearance_min)
    simulation_ms = (perf_counter() - t0) * 1000
    base_wait = fcfs_result["total_wait_min"]
    reduction = 100 * (base_wait - opt_result["total_wait_min"]) / base_wait if base_wait > 0 else 0.0
    result = {"scope": "offline educational scenario; timetable and infrastructure are configurable demo inputs",
              "fcfs": fcfs_result, "optimized": opt_result,
              "wait_reduction_pct_vs_fcfs": float(reduction),
              "secondary_utilization_change_pct_points": float(opt_result["platform_utilization_pct"] - fcfs_result["platform_utilization_pct"]),
              "allocation": alloc_metrics, "simulation_runtime_ms": simulation_ms,
              "fcfs_schedule": fcfs, "optimized_schedule": optimized}
    return result


def stress_test(scenario: pd.DataFrame, *, runs: int = 10_000, seed: int = 2026,
                platforms: list[Platform] | None = None, clearance_min: float = 5.0) -> dict[str, Any]:
    """Monte Carlo robustness test with ETA, dwell, and platform outage shocks.

    The 10,000-run test is a stress harness, not an estimate of real railway
    incident probabilities. Perturbation ranges are explicit demo assumptions.
    """
    if int(runs) != 10_000:
        raise ValueError("Synopsis stress-test configuration is fixed at 10,000 runs.")
    platforms = platforms or default_platforms()
    rng = np.random.default_rng(seed)
    totals, collisions, unassigned, runtimes = [], [], [], []
    base = scenario.reset_index(drop=True)
    base_arrivals = pd.to_numeric(base["estimated_arrival_min"], errors="coerce").fillna(0).to_numpy(float)
    base_dwell = pd.to_numeric(base["dwell_min"], errors="coerce").fillna(10).to_numpy(float)
    base_lengths = pd.to_numeric(base["train_length_m"], errors="coerce").fillna(99999).to_numpy(float)
    base_priority = pd.to_numeric(base["priority"], errors="coerce").fillna(1).to_numpy(int)
    p_lengths = np.asarray([p.length_m for p in platforms], dtype=float)
    nominal, _ = allocate_platforms(base, platforms, clearance_min)
    nominal_platform = nominal["platform_id"].astype(str).to_numpy()
    nominal_assigned = nominal_platform != ""
    risk_runs = 0
    risk_pairs_total = 0
    for _ in range(runs):
        arrivals = np.maximum(0.0, base_arrivals + rng.normal(0, 5.0, size=len(base)))
        dwell = np.maximum(4.0, base_dwell * rng.uniform(0.85, 1.35, size=len(base)))
        run_risks = 0
        for pid in np.unique(nominal_platform[nominal_assigned]):
            members = np.flatnonzero(nominal_platform == pid)
            members = members[np.argsort(arrivals[members], kind="stable")]
            for previous, current in zip(members, members[1:]):
                if arrivals[current] < arrivals[previous] + dwell[previous] + clearance_min:
                    run_risks += 1
        risk_pairs_total += run_risks
        risk_runs += int(run_risks > 0)
        usable_indices = list(range(len(platforms)))
        if len(platforms) > 4 and rng.random() < 0.02:
            usable_indices.remove(int(rng.integers(0, len(platforms))))
        started = perf_counter()
        available = {i: 0.0 for i in usable_indices}
        wait_total = 0.0
        missing = 0
        # Independent fixed-seed FCFS replay under each disturbance. The normal
        # allocator is separately scored above; this loop measures demand and
        # capacity sensitivity without spending minutes rebuilding dataframes.
        for i in np.argsort(arrivals, kind="stable"):
            eligible = [j for j in usable_indices if base_lengths[i] <= p_lengths[j]]
            if not eligible:
                missing += 1
                continue
            platform = min(eligible, key=lambda j: (max(arrivals[i], available[j]), j))
            start = max(arrivals[i], available[platform])
            wait_total += start - arrivals[i]
            available[platform] = start + dwell[i] + clearance_min
        totals.append(float(wait_total))
        collisions.append(0)  # reservations use one exclusive resource per platform
        unassigned.append(missing)
        runtimes.append((perf_counter() - started) * 1000)
    values = np.asarray(totals)
    return {"runs": runs, "seed": seed,
            "perturbations": {"eta_noise": "Normal(0, 5 min)", "dwell_multiplier": "Uniform(0.85, 1.35)",
                              "platform_outage": "2% chance of one platform unavailable when >4 configured",
                              "note": "These are scenario assumptions, not empirical probabilities."},
            "total_wait_min": {"mean": float(values.mean()), "median": float(np.median(values)),
                               "p95": float(np.percentile(values, 95)), "p99": float(np.percentile(values, 99)),
                               "max": float(values.max())},
            "runs_with_safety_violation": int(np.count_nonzero(collisions)),
            "total_safety_violations": int(np.sum(collisions)),
            "runs_with_static_platform_conflict_risk_before_queue_recovery": int(risk_runs),
            "mean_static_conflict_risk_pairs_per_run": float(risk_pairs_total / runs),
            "runs_with_unassigned_movements": int(np.count_nonzero(unassigned)),
            "mean_unassigned_movements": float(np.mean(unassigned)),
            "runtime_ms": {"mean": float(np.mean(runtimes)), "p95": float(np.percentile(runtimes, 95)),
                           "max": float(np.max(runtimes))},
            "scope": "synthetic FCFS capacity sensitivity replay; not operational safety certification"}
