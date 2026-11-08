"""Interactive project workflow, evaluation, model comparison, and prediction dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from railway_delay.platforming import (
    allocate_platforms, default_platforms, make_scenario, simulate_comparison, stress_test,
)
from railway_delay.explainability import shap_contributions


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
DEFAULT_EVALUATION = OUTPUT / "evaluation.json"
DEFAULT_MODEL = OUTPUT / "all_station_delay_model.joblib"
DEFAULT_TEST_PREDICTIONS = OUTPUT / "test_predictions.csv"

st.set_page_config(page_title="Railway Delay Model", page_icon="🚆", layout="wide")
st.title("Railway Delay Prediction Dashboard")
st.caption("Project workflow, model selection, station evaluation, and next-stop predictions")


def load_evaluation(uploaded) -> dict | None:
    if uploaded is not None:
        return json.load(uploaded)
    if DEFAULT_EVALUATION.exists():
        return json.loads(DEFAULT_EVALUATION.read_text(encoding="utf-8"))
    return None


def metric_row(metrics: dict) -> None:
    cols = st.columns(5)
    cols[0].metric("Test examples", f"{metrics.get('n', 0):,}")
    cols[1].metric("MAE", f"{metrics.get('mae_min', float('nan')):.2f} min")
    cols[2].metric("RMSE", f"{metrics.get('rmse_min', float('nan')):.2f} min")
    cols[3].metric("R²", f"{metrics.get('r2', float('nan')):.3f}")
    coverage = metrics.get("interval_coverage_90_nominal")
    cols[4].metric("90% interval coverage", f"{coverage:.1%}" if coverage is not None else "—")


with st.sidebar:
    st.header("Dashboard files")
    uploaded_evaluation = st.file_uploader("Upload evaluation.json", type=["json"])
    evaluation = load_evaluation(uploaded_evaluation)
    model_path = st.text_input("Pooled model file", str(DEFAULT_MODEL))
    predictions_upload = st.file_uploader("Upload test_predictions.csv", type=["csv"])
    st.caption("Training writes the evaluation, test predictions, comparison table, and model under output/.")

if not evaluation:
    st.warning("No evaluation file found. Train the model first, or upload evaluation.json in the sidebar.")
    st.stop()

ndls = evaluation.get("station_specific", {})
pooled = evaluation.get("all_station_model", {})
station_scores = pooled.get("test_by_target_station", {})
workflow = evaluation.get("workflow", [])
comparison = evaluation.get("model_comparison", [])
selected_algorithm = evaluation.get("selected_algorithm", pooled.get("algorithm", "Not recorded"))

workflow_tab, results_tab, algorithms_tab, stations_tab, predictions_tab, predict_tab, methods_tab, platform_tab = st.tabs(
    ["Project steps", "Final results", "Algorithm comparison", "Station results",
     "Prediction audit", "Make predictions", "Data and metrics", "Platform twin"]
)

with workflow_tab:
    st.subheader("What the project does at each step")
    if workflow:
        rows = []
        for item in workflow:
            rows.append({"Step": item.get("step"), "Stage": item.get("name"),
                         "What happens": item.get("description"),
                         "Records / details": json.dumps({k: v for k, v in item.items()
                                                            if k not in {"step", "name", "description"}}, ensure_ascii=False)})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("This evaluation file predates the detailed workflow summary. Retrain once to record all steps.")
    st.markdown("**Prediction target:** arrival delay, in minutes, at the immediate next reported station.")
    st.markdown("**Information used:** current and next station codes, train type, route sequence, scheduled running/dwell time, calendar features, and the current stop’s reported delay.")
    if "source_files" in evaluation:
        st.metric("Train files included", f"{evaluation['source_files']:,}")
    st.metric("Engineered examples", f"{evaluation.get('data_rows_after_feature_engineering', 0):,}")

with results_tab:
    st.subheader(f"Selected pooled model: {selected_algorithm}")
    st.write(evaluation.get("model_selection_reason", "The evaluation file does not include a model-selection explanation. Retrain to compare models."))
    metric_row(pooled)
    st.subheader("NDLS-only future-date result")
    st.caption(f"Algorithm: {ndls.get('algorithm', selected_algorithm)}")
    metric_row(ndls)
    if "baseline_median_mae_min" in ndls:
        st.caption(f"Simple median baseline MAE: {ndls['baseline_median_mae_min']:.2f} min")
    if DEFAULT_TEST_PREDICTIONS.exists() or predictions_upload is not None:
        test_data = pd.read_csv(predictions_upload) if predictions_upload is not None else pd.read_csv(DEFAULT_TEST_PREDICTIONS)
        if {"actual_delay_min", "predicted_delay_min"}.issubset(test_data.columns):
            st.subheader("Actual versus predicted delay on the final holdout")
            scatter = px.scatter(test_data.sample(n=min(5000, len(test_data)), random_state=42),
                                 x="actual_delay_min", y="predicted_delay_min",
                                 color="next_station_code" if "next_station_code" in test_data else None,
                                 hover_data=[c for c in ["train_no", "station_code", "next_station_code"] if c in test_data],
                                 labels={"actual_delay_min": "Actual delay (min)", "predicted_delay_min": "Predicted delay (min)"})
            bound = max(test_data["actual_delay_min"].max(), test_data["predicted_delay_min"].max())
            scatter.add_trace(go.Scatter(x=[0, bound], y=[0, bound], mode="lines", name="Perfect prediction", line={"dash": "dash"}))
            st.plotly_chart(scatter, use_container_width=True)
            if "absolute_error_min" in test_data:
                hist = px.histogram(test_data, x="absolute_error_min", nbins=40,
                                    labels={"absolute_error_min": "Absolute error (min)"},
                                    title="Final holdout absolute-error distribution")
                st.plotly_chart(hist, use_container_width=True)

with algorithms_tab:
    st.subheader("Compare the paper's XGBoost optimization methods")
    if not comparison:
        st.info("No optimization comparison is recorded yet. Run the updated training script to compare XGBoost-GA, XGBoost-PSO, XGBoost-WOA, and XGBoost-GWO.")
    else:
        comp = pd.DataFrame(comparison)
        display_cols = [c for c in ["algorithm", "n", "rmse_min", "mae_min", "r2",
                                    "evaluations", "population_size", "generations",
                                    "training_seconds", "parameters", "selected"] if c in comp]
        st.dataframe(comp[display_cols].sort_values("rmse_min"), use_container_width=True, hide_index=True)
        col1, col2 = st.columns(2)
        with col1:
            order = comp.sort_values("rmse_min")
            fig = px.bar(order, x="algorithm", y="rmse_min", color="selected",
                         color_discrete_map={True: "#15803d", False: "#64748b"},
                         labels={"rmse_min": "Validation RMSE (minutes)", "algorithm": "Method", "selected": "Selected"},
                         title="Validation RMSE fitness (lower is better)")
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            xgb_comp = comp[comp["kind"] == "xgboost_metaheuristic"]
            fig = px.bar(xgb_comp, x="algorithm", y="mae_min", color="selected",
                         color_discrete_map={True: "#15803d", False: "#64748b"},
                         labels={"mae_min": "Validation MAE (minutes)", "algorithm": "Method", "selected": "Selected"},
                         title="Validation MAE (lower is better)")
            st.plotly_chart(fig, use_container_width=True)
        st.success(evaluation.get("model_selection_reason", f"Selected algorithm: {selected_algorithm}"))
        st.caption("RMSE is the tuning fitness, following Gao et al. The final chronological test dates are held back for final scoring.")
        if evaluation.get("optimization_results"):
            st.subheader("Best-so-far RMSE by optimizer generation")
            convergence = []
            for result in evaluation["optimization_results"]:
                for generation, score in enumerate(result["history"]):
                    convergence.append({"Optimizer": result["optimizer"], "Generation": generation,
                                        "Best validation RMSE (min)": score})
            st.plotly_chart(px.line(pd.DataFrame(convergence), x="Generation",
                                    y="Best validation RMSE (min)", color="Optimizer",
                                    markers=True), use_container_width=True)

with stations_tab:
    st.subheader("Future-date performance by target station")
    if not station_scores:
        st.info("No per-station scores are in this evaluation file.")
    else:
        score_df = pd.DataFrame.from_dict(station_scores, orient="index").reset_index(names="station_code")
        score_df = score_df.sort_values("mae_min")
        codes = sorted(score_df["station_code"].tolist())
        selected_station = st.selectbox("Inspect station", codes)
        selected_row = score_df.loc[score_df["station_code"] == selected_station].iloc[0]
        cols = st.columns(4)
        cols[0].metric("Holdout examples", f"{int(selected_row['n']):,}")
        cols[1].metric("MAE", f"{selected_row['mae_min']:.2f} min")
        cols[2].metric("RMSE", f"{selected_row['rmse_min']:.2f} min")
        cols[3].metric("R²", f"{selected_row['r2']:.3f}")
        max_count = min(40, len(score_df))
        count = st.slider("Stations in chart", min_value=5, max_value=max_count, value=min(15, max_count)) if max_count >= 5 else max_count
        best = score_df.nsmallest(count, "mae_min").sort_values("mae_min")
        fig = px.bar(best, x="mae_min", y="station_code", orientation="h", color="mae_min",
                     color_continuous_scale="YlOrRd", hover_data={"n": True, "rmse_min": ":.2f", "r2": ":.3f"},
                     labels={"mae_min": "MAE (minutes)", "station_code": "Target station"})
        fig.update_layout(height=max(400, 24 * count), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(score_df.sort_values("mae_min"), use_container_width=True, hide_index=True)

with predictions_tab:
    st.subheader("Row-by-row final test predictions")
    if predictions_upload is not None:
        test_data = pd.read_csv(predictions_upload)
    elif DEFAULT_TEST_PREDICTIONS.exists():
        test_data = pd.read_csv(DEFAULT_TEST_PREDICTIONS)
    else:
        test_data = pd.DataFrame()
    if test_data.empty:
        st.info("No test_predictions.csv found. Retrain with the updated script to save every test prediction.")
    else:
        if "next_station_code" in test_data:
            options = sorted(test_data["next_station_code"].dropna().unique())
            chosen = st.multiselect("Filter target stations", options, default=options[:min(8, len(options))])
            if chosen:
                test_data = test_data[test_data["next_station_code"].isin(chosen)]
        st.dataframe(test_data.head(1000), use_container_width=True, hide_index=True)
        st.download_button("Download filtered test predictions", test_data.to_csv(index=False),
                           file_name="filtered_test_predictions.csv", mime="text/csv")
        if "absolute_error_min" in test_data and not test_data.empty:
            fig = px.box(test_data, x="next_station_code", y="absolute_error_min", points=False,
                         labels={"next_station_code": "Target station", "absolute_error_min": "Absolute error (min)"},
                         title="Error distribution by target station")
            st.plotly_chart(fig, use_container_width=True)

with predict_tab:
    st.subheader("Predict delay at a next stop")
    st.write("Upload engineered feature rows. Each row receives a point estimate and a calibrated 90% interval.")
    model_file = Path(model_path)
    if not model_file.exists():
        st.warning(f"Model not found: {model_file}. Train the model or update the path in the sidebar.")
    else:
        try:
            bundle = joblib.load(model_file)
            feature_names = bundle["features"]
            radius = float(bundle["interval_abs_error_q90_min"])
            st.caption(f"Model: {bundle.get('algorithm', 'unknown')} | Required features: " + ", ".join(feature_names))
            feature_upload = st.file_uploader("Upload prediction feature CSV", type=["csv"], key="feature_csv")
            if feature_upload is not None:
                input_rows = pd.read_csv(feature_upload)
                missing = sorted(set(feature_names) - set(input_rows.columns))
                if missing:
                    st.error("Missing required columns: " + ", ".join(missing))
                else:
                    predictions = bundle["model"].predict(input_rows[feature_names])
                    result = input_rows.copy()
                    result["predicted_delay_min"] = predictions
                    result["delay_lower_90_min"] = np.maximum(predictions - radius, 0)
                    result["delay_upper_90_min"] = predictions + radius

                    st.subheader("Why did the model make these estimates? (TreeSHAP)")
                    with st.expander("View feature contributions", expanded=True):
                        explain_rows = input_rows[feature_names].head(500)
                        shap_values = shap_contributions(bundle["model"], explain_rows, feature_names)
                        if len(input_rows) > len(explain_rows):
                            st.caption(f"TreeSHAP summary uses the first {len(explain_rows)} rows to keep the dashboard responsive.")
                        shap_summary = pd.DataFrame({
                            "Feature": feature_names,
                            "Mean absolute contribution (min)": [float(shap_values[f].abs().mean()) for f in feature_names],
                            "Mean signed contribution (min)": [float(shap_values[f].mean()) for f in feature_names],
                        }).sort_values("Mean absolute contribution (min)", ascending=False)
                        shap_col1, shap_col2 = st.columns([1, 1])
                        with shap_col1:
                            st.plotly_chart(px.bar(shap_summary.head(12).sort_values("Mean absolute contribution (min)"),
                                                   x="Mean absolute contribution (min)", y="Feature", orientation="h",
                                                   title="Mean absolute TreeSHAP contribution",
                                                   labels={"Mean absolute contribution (min)": "Average impact magnitude (min)"}),
                                            use_container_width=True)
                        with shap_col2:
                            st.dataframe(shap_summary, use_container_width=True, hide_index=True)
                        if len(shap_values):
                            row_contrib = shap_values.iloc[0][feature_names].sort_values(key=lambda x: x.abs(), ascending=False)
                            top = row_contrib.head(8).rename_axis("Feature").reset_index(name="Contribution (min)")
                            top["Direction"] = np.where(top["Contribution (min)"] >= 0,
                                                         "Pushes estimate higher", "Pushes estimate lower")
                            st.caption("For one prediction, positive contributions raise the estimate and negative contributions lower it; the baseline plus all contributions equals the model estimate.")
                            st.dataframe(top, use_container_width=True, hide_index=True)

                    st.subheader("Prediction summary")
                    mean_prediction = float(np.mean(predictions))
                    max_index = int(np.argmax(predictions))
                    mean_interval_width = float(np.mean(result["delay_upper_90_min"] - result["delay_lower_90_min"]))
                    summary_cols = st.columns(4)
                    summary_cols[0].metric("Trains scored", f"{len(result):,}")
                    summary_cols[1].metric("Average predicted delay", f"{mean_prediction:.1f} min")
                    summary_cols[2].metric("Highest predicted delay", f"{predictions[max_index]:.1f} min")
                    summary_cols[3].metric("Average 90% range width", f"{mean_interval_width:.1f} min")

                    if len(result) == 1:
                        target_station = str(result.iloc[0].get("next_station_code", "next stop"))
                        train_number = str(result.iloc[0].get("train_no", ""))
                        train_text = f" for train {train_number}" if train_number else ""
                        st.success(
                            f"Estimated arrival delay{train_text} at {target_station}: "
                            f"**{predictions[0]:.1f} minutes**."
                        )
                        st.caption(
                            f"Calibrated 90% prediction range: "
                            f"{result['delay_lower_90_min'].iloc[0]:.1f}–"
                            f"{result['delay_upper_90_min'].iloc[0]:.1f} minutes."
                        )
                    else:
                        st.write(
                            f"Across these {len(result):,} rows, the model estimates an average "
                            f"next-stop delay of **{mean_prediction:.1f} minutes**. The chart shows "
                            "the 20 largest estimates; whiskers show each calibrated 90% range."
                        )
                        # Add a unique case number because one train can appear
                        # many times in a history CSV with the same next station.
                        result["prediction_label"] = [f"Case {i + 1}" for i in range(len(result))]
                        result["interval_error_low_min"] = result["predicted_delay_min"] - result["delay_lower_90_min"]
                        result["interval_error_high_min"] = result["delay_upper_90_min"] - result["predicted_delay_min"]
                        chart_rows = result.nlargest(20, "predicted_delay_min").sort_values("predicted_delay_min")
                        hover_columns = [c for c in ["train_no", "date", "station_code", "next_station_code", "seq",
                                                       "delay_lower_90_min", "delay_upper_90_min"] if c in chart_rows]
                        hover_details = "<br>".join(f"{column}: %{{customdata[{i}]}}"
                                                     for i, column in enumerate(hover_columns))
                        fig = go.Figure(go.Scatter(
                            x=chart_rows["predicted_delay_min"], y=chart_rows["prediction_label"],
                            mode="markers", name="Predicted delay",
                            marker={"size": 10, "color": "#38bdf8"},
                            error_x={"type": "data", "symmetric": False,
                                     "array": chart_rows["interval_error_high_min"],
                                     "arrayminus": chart_rows["interval_error_low_min"],
                                     "thickness": 1.5, "width": 4},
                            customdata=chart_rows[hover_columns].to_numpy(),
                            hovertemplate=("%{y}<br>Estimated delay: %{x:.1f} min<br>" +
                                           hover_details + "<extra></extra>")))
                        fig.update_layout(
                            title="Largest predicted delays with calibrated 90% ranges",
                            xaxis_title="Estimated next-stop delay (minutes)",
                            yaxis_title="Prediction row",
                            yaxis={"categoryorder": "array", "categoryarray": chart_rows["prediction_label"],
                                   "automargin": True},
                            height=520)
                        st.plotly_chart(fig, use_container_width=True)
                        st.caption("Hover over a point to see its train, date, route segment, and prediction interval.")

                    if "target_delay_min" in result:
                        actual = pd.to_numeric(result["target_delay_min"], errors="coerce")
                        valid = actual.notna()
                        if valid.any():
                            st.info("This CSV contains known delay labels, so the following is a check against recorded examples. For future trains, upload features without target_delay_min.")
                            actual_values = actual[valid].to_numpy()
                            predicted_values = result.loc[valid, "predicted_delay_min"].to_numpy()
                            evaluation_cols = st.columns(2)
                            evaluation_cols[0].metric("MAE on uploaded labeled rows", f"{np.mean(np.abs(actual_values - predicted_values)):.2f} min")
                            evaluation_cols[1].metric("RMSE on uploaded labeled rows", f"{np.sqrt(np.mean((actual_values - predicted_values) ** 2)):.2f} min")
                            comparison_rows = pd.DataFrame({"Actual delay (min)": actual_values,
                                                            "Predicted delay (min)": predicted_values})
                            fig = px.scatter(comparison_rows, x="Actual delay (min)", y="Predicted delay (min)",
                                             title="Recorded and predicted delays for uploaded examples")
                            limit = float(max(comparison_rows.max().max(), 1))
                            fig.add_shape(type="line", x0=0, y0=0, x1=limit, y1=limit,
                                          line={"dash": "dash", "color": "gray"})
                            st.plotly_chart(fig, use_container_width=True)

                    st.subheader("Detailed prediction table")
                    st.caption("Each row shows the model estimate and its calibrated 90% range. Use the download button to save all rows.")
                    clean_result = result.drop(columns=["interval_error_low_min", "interval_error_high_min", "prediction_label"], errors="ignore")
                    st.dataframe(clean_result, use_container_width=True, hide_index=True)
                    st.download_button("Download predictions CSV", clean_result.to_csv(index=False),
                                       file_name="railway_delay_predictions.csv", mime="text/csv")
        except Exception as exc:
            st.error(f"Could not load the model or make predictions: {exc}")

with methods_tab:
    st.subheader("Metrics and interpretation")
    if evaluation.get("feature_importance"):
        imp = pd.DataFrame(evaluation["feature_importance"])
        fig = px.bar(imp.head(12).sort_values("mae_increase_min"), x="mae_increase_min", y="feature",
                     orientation="h", labels={"mae_increase_min": "Increase in validation MAE when shuffled (min)", "feature": "Feature"},
                     title="Permutation feature importance")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Larger positive values mean shuffling that feature made predictions less accurate on the calibration sample.")
    metric_help = pd.DataFrame([
        {"Metric": "MAE", "Meaning": "Average absolute prediction error, in minutes. Lower is better."},
        {"Metric": "RMSE", "Meaning": "Penalizes large misses more than MAE, in minutes. Lower is better."},
        {"Metric": "R²", "Meaning": "Variance explained relative to a mean predictor. Closer to 1 is better; can be negative."},
        {"Metric": "90% interval coverage", "Meaning": "Share of test labels inside the calibrated lower/upper delay interval. Near 90% is the target."},
        {"Metric": "Fit time", "Meaning": "Seconds used to fit each candidate on the same training partition."},
        {"Metric": "Optimizer fitness", "Meaning": "Validation RMSE used by GA, PSO, WOA, and GWO to search XGBoost hyperparameters."},
    ])
    st.dataframe(metric_help, use_container_width=True, hide_index=True)
    st.subheader("Dataset limits")
    for limitation in evaluation.get("limitations", []):
        st.write(f"- {limitation}")
    st.info("This is an educational delay predictor. It does not learn platform assignments, dispatch commands, or signaling rules, and it must not be used as a live railway-control system.")

with platform_tab:
    st.subheader("Station platform allocation and discrete-event twin")
    st.warning("Offline educational simulation. Arrival timetable, platform lengths, train lengths, dwell, and priorities are configurable demo inputs. Delay estimates can come from the prediction model, but this dataset does not verify actual platform operations.")
    left, right = st.columns([1, 2])
    with left:
        movement_count = st.slider("Movements in demo day", 20, 60, 36)
        platform_count = st.slider("Configured platforms", 4, 8, 6)
        platform_length = st.slider("Platform length (demo meters)", 450, 800, 700, step=10)
        clearance = st.slider("Minimum clearance (minutes)", 5, 20, 5)
        demand = st.selectbox("Arrival demand pattern", ["light", "moderate", "busy"], index=1)
        seed = st.number_input("Scenario seed", min_value=0, max_value=999999, value=42)
        pred_file = st.file_uploader("Optional prediction-results CSV", type=["csv"], key="platform_predictions")
        prediction_rows = pd.read_csv(pred_file) if pred_file is not None else None
        if prediction_rows is not None and "next_station_code" in prediction_rows:
            target_options = sorted(prediction_rows["next_station_code"].dropna().astype(str).unique())
            default_target = "NDLS" if "NDLS" in target_options else (target_options[0] if target_options else None)
            if target_options:
                target = st.selectbox("Target station for this scenario", target_options,
                                      index=target_options.index(default_target))
                prediction_rows = prediction_rows[prediction_rows["next_station_code"].astype(str).eq(target)].reset_index(drop=True)
    with right:
        st.markdown("**Pipeline:** model delay estimates → scheduled arrival windows → length and clearance checks → priority-aware weighted interval allocation → SimPy FCFS/optimized comparison → Monte Carlo stress test.")
        st.caption("The prediction workflow above is unchanged. Provide its downloaded predictions CSV here to use its `predicted_delay_min` values in this scenario.")
    platform_config = default_platforms(platform_count, platform_length)
    try:
        demo_scenario = make_scenario(prediction_rows, n=movement_count, seed=int(seed), demand=demand,
                                      platforms=platform_config, clearance_min=clearance)
        st.caption(f"Delay input: {demo_scenario['prediction_source'].iloc[0]}. Timetable, train lengths, dwell, priority, and platform specs: synthetic/configurable.")
        if st.button("Run platform allocation and SimPy comparison", type="primary", key="run_twin"):
            with st.spinner("Allocating platforms and running FCFS and optimized simulations…"):
                comparison_result = simulate_comparison(demo_scenario, platform_config, clearance)
            st.session_state["platform_result"] = comparison_result
        twin = st.session_state.get("platform_result")
        if twin:
            fcfs, optimized = twin["fcfs"], twin["optimized"]
            cols = st.columns(5)
            cols[0].metric("FCFS total wait", f"{fcfs['total_wait_min']:.1f} min")
            cols[1].metric("Optimized total wait", f"{optimized['total_wait_min']:.1f} min")
            cols[2].metric("Wait change vs FCFS", f"{twin['wait_reduction_pct_vs_fcfs']:+.1f}%")
            cols[3].metric("Optimized utilization", f"{optimized['platform_utilization_pct']:.1f}%")
            cols[4].metric("Safety violations", f"{twin['allocation']['clearance_violations'] + twin['allocation']['length_violations']}")
            st.caption(f"Allocation computation: {twin['allocation']['allocation_runtime_ms']:.2f} ms | SimPy run: {twin['simulation_runtime_ms']:.2f} ms. Results depend on this synthetic scenario.")
            utilization_rows = []
            for method, metrics in [("FCFS", fcfs), ("WIS / safeguard", optimized)]:
                utilization_rows.extend({"Method": method, "Platform": pid, "Utilization (%)": value}
                                        for pid, value in metrics["platform_utilization_by_id_pct"].items())
            st.plotly_chart(px.bar(pd.DataFrame(utilization_rows), x="Platform", y="Utilization (%)",
                                   color="Method", barmode="group", title="Utilization by configured platform"),
                            use_container_width=True)
            chart_data = twin["optimized_schedule"].copy()
            chart_data = chart_data[chart_data.platform_id.ne("")]
            chart_data["platform_label"] = chart_data["platform_id"] + " · " + chart_data["train_no"].astype(str)
            chart_data["service_duration_min"] = chart_data["scheduled_end_min"] - chart_data["scheduled_start_min"]
            gantt = px.bar(chart_data, x="service_duration_min", y="platform_id", base="scheduled_start_min",
                           orientation="h", color="priority", hover_name="train_no",
                           hover_data=["movement_id", "scheduled_start_min", "scheduled_end_min",
                                       "estimated_arrival_min", "predicted_delay_min", "train_length_m",
                                       "dwell_min", "allocation_explanation"],
                           color_continuous_scale="Viridis",
                           title="Optimized platform schedule (minutes from day start)")
            gantt.update_yaxes(autorange="reversed", title="Configured platform")
            gantt.update_xaxes(title="Minutes from day start", type="linear")
            st.plotly_chart(gantt, use_container_width=True)
            display_cols = ["movement_id", "train_no", "estimated_arrival_min", "platform_id",
                            "scheduled_start_min", "scheduled_end_min", "train_length_m", "priority",
                            "allocation_explanation"]
            st.dataframe(twin["optimized_schedule"][display_cols], use_container_width=True, hide_index=True)
            st.download_button("Download optimized schedule", twin["optimized_schedule"].to_csv(index=False),
                               file_name="ndls_demo_platform_schedule.csv", mime="text/csv")
            st.subheader("10,000-run Monte Carlo stress test")
            st.write("Randomly perturbs arrival estimates and dwell, with an assumed 2% chance of one configured platform being unavailable. These are sensitivity assumptions, not measured failure probabilities. The reported zero resource collisions are guaranteed by the single-capacity platform queue; static conflict-risk before queue recovery is reported separately.")
            if st.button("Run 10,000 stress scenarios", key="run_stress"):
                with st.spinner("Running 10,000 deterministic-seed perturbation scenarios…"):
                    stress = stress_test(demo_scenario, runs=10_000, seed=int(seed) + 2026,
                                         platforms=platform_config, clearance_min=clearance)
                st.session_state["platform_stress"] = stress
            stress = st.session_state.get("platform_stress")
            if stress:
                st.json(stress)
    except Exception as exc:
        st.error(f"Platform simulation could not run: {exc}")
