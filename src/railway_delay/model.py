"""Train, calibrate, and evaluate a portable station-agnostic delay model."""

from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

from .features import CATEGORICAL, FEATURES, NUMERIC, TARGET
from .xgb_optimization import run_optimizer


def time_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological 60/10/10/20 split with separate validation and calibration."""
    dates = np.array(sorted(pd.to_datetime(frame["date"]).dropna().unique()))
    if len(dates) < 5:
        raise ValueError("At least five distinct journey dates are required for a chronological split.")
    train_cut = max(1, int(len(dates) * .60))
    validation_cut = max(train_cut + 1, int(len(dates) * .70))
    calibration_cut = max(validation_cut + 1, int(len(dates) * .80))
    train_dates = set(dates[:train_cut])
    validation_dates = set(dates[train_cut:validation_cut])
    calibration_dates = set(dates[validation_cut:calibration_cut])
    test_dates = set(dates[calibration_cut:])
    d = pd.to_datetime(frame["date"])
    return (frame[d.isin(train_dates)].copy(), frame[d.isin(validation_dates)].copy(),
            frame[d.isin(calibration_dates)].copy(), frame[d.isin(test_dates)].copy())


def make_estimator(algorithm: str = "Extra Trees", seed: int = 42) -> Pipeline:
    dense = algorithm == "Hist Gradient Boosting"
    # Bound the dense matrix size for HistGradientBoosting on station-code categories.
    encoder = OneHotEncoder(handle_unknown="ignore", min_frequency=5,
                            max_categories=32 if dense else None, sparse_output=not dense)
    prep = ColumnTransformer([
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                           ("onehot", encoder)]), CATEGORICAL),
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")),
                           ("scale", StandardScaler())]), NUMERIC),
    ], remainder="drop", sparse_threshold=0 if dense else 0.3)
    if algorithm == "Extra Trees":
        regressor = ExtraTreesRegressor(n_estimators=60, max_depth=16, min_samples_leaf=3,
                                        max_features=0.7, n_jobs=2, random_state=seed)
    elif algorithm == "Random Forest":
        regressor = RandomForestRegressor(n_estimators=60, max_depth=16, min_samples_leaf=3,
                                          max_features=0.7, n_jobs=2, random_state=seed)
    elif algorithm == "Hist Gradient Boosting":
        regressor = HistGradientBoostingRegressor(max_iter=80, max_leaf_nodes=31,
                                                   min_samples_leaf=30, l2_regularization=1.0,
                                                   learning_rate=0.08, random_state=seed)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    return Pipeline([("features", prep), ("regressor", regressor)])


def decode_xgb_parameters(position: np.ndarray) -> dict[str, float | int]:
    """Map normalized search coordinates to the paper's XGBoost ranges."""
    return {
        "n_estimators": int(round(100 + position[0] * 900)),
        "learning_rate": float(0.001 + position[1] * 0.299),
        "min_child_weight": int(round(1 + position[2] * 9)),
        "max_depth": int(round(3 + position[3] * 12)),
    }


def make_xgb_estimator(parameters: dict, seed: int = 42) -> Pipeline:
    prep = ColumnTransformer([
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                           ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=5))]), CATEGORICAL),
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")),
                           ("scale", StandardScaler())]), NUMERIC),
    ], remainder="drop")
    regressor = XGBRegressor(
        objective="reg:squarederror", booster="gbtree", tree_method="hist",
        gamma=0.01, subsample=1.0, eval_metric="rmse", n_jobs=2,
        random_state=seed, verbosity=0, **parameters)
    return Pipeline([("features", prep), ("regressor", regressor)])


def _metrics(y: pd.Series, pred: np.ndarray) -> dict[str, float]:
    return {"n": int(len(y)), "mae_min": float(mean_absolute_error(y, pred)),
            "rmse_min": float(mean_squared_error(y, pred) ** .5),
            "r2": float(r2_score(y, pred)) if len(y) > 1 else float("nan")}


def fit_and_evaluate(frame: pd.DataFrame, output_dir: str | Path, station: str = "NDLS", seed: int = 42,
                     source_rows: int | None = None, source_files: int | None = None) -> dict:
    """Compare tree models on validation dates, select one, and score a final holdout."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = frame.dropna(subset=["station_code", "next_station_code", TARGET, "date"]).copy()
    frame["date"] = pd.to_datetime(frame["date"])
    station = station.upper()
    station_rows = frame[frame["next_station_code"].str.upper().eq(station)].copy()
    if len(station_rows) < 200:
        raise ValueError(f"Only {len(station_rows)} usable {station} examples; at least 200 are required.")

    # Keep the final chronological test period untouched during model selection.
    all_train, all_validation, all_calibration, all_test = time_split(frame)
    y_train = all_train[TARGET].to_numpy()
    median_start = time.perf_counter()
    median_prediction = np.repeat(float(np.median(y_train)), len(all_validation))
    median_elapsed = time.perf_counter() - median_start
    median_metrics = _metrics(all_validation[TARGET], median_prediction)
    comparison = [{"algorithm": "Median Baseline", "kind": "baseline", **median_metrics,
                   "training_seconds": 0.0, "selected": False}]

    # All four optimizers see the same bounded training and validation samples;
    # RMSE is the search fitness, following Gao et al. The final holdout remains
    # untouched. A compact budget is used because the source sample and hardware
    # differ substantially from the paper's 1.9M-row GPU experiment.
    tune_train = all_train.sample(n=min(6000, len(all_train)), random_state=seed)
    tune_validation = all_validation.sample(n=min(2500, len(all_validation)), random_state=seed)
    optimizer_results = []
    for optimizer_name in ["GA", "PSO", "WOA", "GWO"]:
        metric_cache = {}

        def objective(position):
            parameters = decode_xgb_parameters(position)
            estimator = make_xgb_estimator(parameters, seed)
            estimator.fit(tune_train[FEATURES], tune_train[TARGET])
            prediction = estimator.predict(tune_validation[FEATURES])
            metrics = _metrics(tune_validation[TARGET], prediction)
            metric_cache[tuple(np.round(position, 5))] = metrics
            return metrics["rmse_min"]

        start = time.perf_counter()
        result = run_optimizer(optimizer_name, objective, population_size=6,
                               generations=2, seed=seed + len(optimizer_results))
        elapsed = time.perf_counter() - start
        best_position = result["best_position"]
        best_parameters = decode_xgb_parameters(best_position)
        best_metrics = metric_cache[tuple(np.round(best_position, 5))]
        optimizer_results.append({**result, "parameters": best_parameters,
                                  "metrics": best_metrics, "training_seconds": float(elapsed)})
        comparison.append({"algorithm": f"XGBoost-{optimizer_name}", "optimizer": optimizer_name,
                           "kind": "xgboost_metaheuristic", **best_metrics,
                           "training_seconds": float(elapsed), "evaluations": result["evaluations"],
                           "population_size": result["population_size"],
                           "generations": result["generations"],
                           "parameters": best_parameters, "selected": False})

    tuned_models = [row for row in comparison if row["kind"] == "xgboost_metaheuristic"]
    # The paper uses RMSE as the optimizer fitness, so it is also the primary
    # selection metric here; MAE and R² remain visible for context.
    selected_row = min(tuned_models, key=lambda item: (item["rmse_min"], item["mae_min"]))
    selected_algorithm = selected_row["algorithm"]
    selected_optimizer = selected_row["optimizer"]
    selected_parameters = selected_row["parameters"]
    for row in comparison:
        row["selected"] = row["algorithm"] == selected_algorithm
    runner_up = min((row for row in tuned_models if row["algorithm"] != selected_algorithm),
                    key=lambda item: (item["rmse_min"], item["mae_min"]))
    reason = (f"Selected {selected_algorithm} because it achieved the lowest validation RMSE "
              f"({selected_row['rmse_min']:.2f} min), the optimization fitness used in the cited paper; "
              "the final test dates were not used for selection.")
    reason += f" The runner-up was {runner_up['algorithm']} ({runner_up['rmse_min']:.2f} min RMSE)."

    # Refit the chosen algorithm on train + validation dates. The separate
    # calibration dates set the prediction interval; the final test stays untouched.
    train_validation = pd.concat([all_train, all_validation], ignore_index=True)
    universal = make_xgb_estimator(selected_parameters, seed)
    start = time.perf_counter()
    universal.fit(train_validation[FEATURES], train_validation[TARGET])
    production_training_seconds = time.perf_counter() - start
    cal_pred = universal.predict(all_calibration[FEATURES])
    universal_q = float(np.quantile(np.abs(all_calibration[TARGET].to_numpy() - cal_pred), .90, method="higher"))
    all_pred = universal.predict(all_test[FEATURES])
    universal_metrics = _metrics(all_test[TARGET], all_pred)
    universal_metrics["interval_abs_error_q90_min"] = universal_q
    universal_metrics["interval_coverage_90_nominal"] = float(np.mean(np.abs(all_test[TARGET].to_numpy() - all_pred) <= universal_q))
    universal_metrics["production_training_seconds"] = float(production_training_seconds)
    universal_metrics["algorithm"] = selected_algorithm
    station_breakdown = {}
    for target_station, indices in all_test.groupby("next_station_code").groups.items():
        mask = all_test.index.isin(indices)
        if int(mask.sum()) >= 50:
            station_breakdown[str(target_station)] = _metrics(all_test.loc[mask, TARGET], all_pred[mask])
    joblib.dump({"model": universal, "features": FEATURES, "station": "*",
                 "interval_abs_error_q90_min": universal_q, "algorithm": selected_algorithm,
                 "xgboost_parameters": selected_parameters},
                output / "all_station_delay_model.joblib")

    # NDLS-only temporal model uses the selected pooled algorithm for consistency.
    train, validation, calibration, test = time_split(station_rows)
    model = make_xgb_estimator(selected_parameters, seed)
    model.fit(pd.concat([train, validation], ignore_index=True)[FEATURES],
              pd.concat([train, validation], ignore_index=True)[TARGET])
    cal_pred = model.predict(calibration[FEATURES])
    residual_q = float(np.quantile(np.abs(calibration[TARGET].to_numpy() - cal_pred), .90, method="higher"))
    pred = model.predict(test[FEATURES])
    ndls_result = _metrics(test[TARGET], pred)
    ndls_result.update({"station": station, "algorithm": selected_algorithm,
                        "calibration_abs_error_q90_min": residual_q,
                        "interval_coverage_90_nominal": float(np.mean(np.abs(test[TARGET].to_numpy() - pred) <= residual_q)),
                        "baseline_median_mae_min": float(mean_absolute_error(test[TARGET], np.repeat(train[TARGET].median(), len(test))))})
    joblib.dump({"model": model, "features": FEATURES, "station": station,
                 "interval_abs_error_q90_min": residual_q, "algorithm": selected_algorithm,
                 "xgboost_parameters": selected_parameters},
                output / f"{station.lower()}_delay_model.joblib")

    # Explainability: permutation importance on a bounded calibration subset.
    importance_rows = all_calibration.sample(n=min(512, len(all_calibration)), random_state=seed)
    importance = permutation_importance(
        universal, importance_rows[FEATURES], importance_rows[TARGET], n_repeats=3,
        random_state=seed, scoring="neg_mean_absolute_error", n_jobs=1)
    feature_importance = sorted(
        [{"feature": name, "mae_increase_min": float(value)}
         for name, value in zip(FEATURES, importance.importances_mean)],
        key=lambda item: item["mae_increase_min"], reverse=True)

    prediction_rows = all_test[["date", "train_no", "station_code", "next_station_code"]].copy()
    prediction_rows["actual_delay_min"] = all_test[TARGET].to_numpy()
    prediction_rows["predicted_delay_min"] = all_pred
    prediction_rows["delay_lower_90_min"] = np.maximum(all_pred - universal_q, 0)
    prediction_rows["delay_upper_90_min"] = all_pred + universal_q
    prediction_rows["absolute_error_min"] = np.abs(all_test[TARGET].to_numpy() - all_pred)
    prediction_rows.to_csv(output / "test_predictions.csv", index=False)
    pd.DataFrame(comparison).to_csv(output / "algorithm_comparison.csv", index=False)

    split_counts = {"train": int(len(all_train)), "validation": int(len(all_validation)),
                    "calibration": int(len(all_calibration)), "test": int(len(all_test))}
    workflow = [
        {"step": 1, "name": "Load data", "description": "Read stop-level train histories from the source CSV files.",
         "records": source_rows if source_rows is not None else None},
        {"step": 2, "name": "Clean and pair stops", "description": "Keep reported stops, order each train journey, and pair each stop with its immediate next stop.",
         "records": int(len(frame))},
        {"step": 3, "name": "Build features", "description": "Use schedule, route, calendar, train-type, and current-stop delay features; predict next-stop arrival delay.",
         "features": len(FEATURES), "target": TARGET},
        {"step": 4, "name": "Split by date", "description": "Use chronological partitions so later journeys cannot leak into training.",
         "records_by_partition": split_counts},
        {"step": 5, "name": "Tune XGBoost", "description": "Run GA, PSO, WOA, and GWO with validation RMSE as fitness over the paper's four XGBoost parameters.",
         "selected_algorithm": selected_algorithm, "population_size": 6, "generations": 2,
         "tuning_train_rows": int(len(tune_train)), "tuning_validation_rows": int(len(tune_validation))},
        {"step": 6, "name": "Calibrate uncertainty", "description": "Use absolute calibration residuals to form a nominal 90% prediction interval.",
         "calibration_rows": split_counts["calibration"]},
        {"step": 7, "name": "Final evaluation", "description": "Report metrics once on later, untouched test dates.",
         "test_rows": split_counts["test"]},
    ]

    results = {"target": "next-stop reported arrival delay (minutes)",
               "split": "chronological by journey date: 60% train, 10% validation, 10% calibration, 20% test",
               "station_specific": ndls_result,
               "all_station_model": {**universal_metrics, "test_by_target_station": station_breakdown},
               "model_comparison": comparison,
               "selected_algorithm": selected_algorithm,
               "selected_optimizer": selected_optimizer,
               "selected_xgboost_parameters": selected_parameters,
               "optimization_method": "GA, PSO, WOA, and GWO; RMSE fitness; paper search ranges; compute-adapted population=6 and generations=2",
               "model_selection_reason": reason,
               "feature_importance": feature_importance,
               "workflow": workflow,
               "split_counts": split_counts,
               "source_files": source_files,
               "data_rows_after_feature_engineering": int(len(frame)),
               "optimization_results": [{"optimizer": x["method"], "best_rmse_min": x["best_fitness"],
                                          "parameters": x["parameters"], "history": x["history"],
                                          "evaluations": x["evaluations"],
                                          "training_seconds": x["training_seconds"]}
                                         for x in optimizer_results],
               "limitations": ["Only stops with reported=1 are used.",
                               "Dataset delay labels are clipped at zero by source, so early running is not modeled.",
                               "The sample covers a bounded set of train histories and is not a nationwide benchmark.",
                               "Station performance depends on which routes and dates are present in the selected extract."]}
    (output / "evaluation.json").write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    return results

