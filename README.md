# Railway station delay prediction

This project retains the delay prediction pipeline and adds an offline,
configurable platform allocation and discrete-event simulation for an NDLS
demo scenario. The same prediction pipeline can train a station-specific model
for another target station and evaluate a pooled model across stations.

## Data and prediction target

The supplied Hugging Face corpus has one record per train, stop, and journey
date. A training example uses only fields known at the current stop: current
station, next station, train class, route sequence, distance to the next stop,
scheduled run and dwell times, day and month, and reported arrival/departure
delay at the current stop. The label is the reported arrival delay at the next
stop. The implementation filters `reported == 1`, pairs rows within the same
train and journey, and does not use actual arrival/departure timestamps or
platform labels as model features.

The model still predicts next-stop arrival delay; its training, selected model,
and evaluation procedure are unchanged by the platforming addition. The public
source's `platform` field is not used or audited as a verified platform plan.
The project does not have a verified NDLS timetable, platform lengths, train
lengths, dispatch commands, or dwell plan. The scheduler therefore uses clearly
marked configurable demo inputs and must not be interpreted as observed railway
operations or as a live control system.

## Run

Install the dependencies in `requirements.txt` in a virtual environment, then
from the repository root:

```powershell
python -m pip install -r requirements.txt
python src/train_model.py --station NDLS --stations HWH BCT
```

The default downloader asks the Hugging Face dataset viewer for train numbers
serving the requested station(s), then downloads only those trains' individual
history files. It caches source files in `data/cache/huggingface/`. Use
`--max-trains-per-station` and `--max-index-rows` to bound the download. The
viewer currently exposes only a partial Parquet export of the much larger CSV
dataset, so this mode creates a corridor sample rather than a full-corpus
benchmark. If the station filter is unavailable, the downloader falls back to
sampling the ordinary rows endpoint (4,000 rows by default); increase that with
`--fallback-sample-rows 20000` if it finds too few trains. If the viewer is
unavailable entirely, provide a local CSV with the source columns instead:

```powershell
python src/train_model.py --csv path\to\stop_history.csv --station NDLS
```

The training run tunes XGBoost with the four metaheuristics in Gao et al.:
Genetic Algorithm (GA), Particle Swarm Optimization (PSO), Whale Optimization
Algorithm (WOA), and Grey Wolf Optimization (GWO). Search fitness is validation
RMSE, with MAE and R² reported for comparison. It uses the paper's search ranges
for `n_estimators`, `learning_rate`, `min_child_weight`, and `max_depth`, while
using a smaller population of 6 and 2 generations to keep the experiment
practical on a student laptop. All four methods use the same dated training and
validation samples. The later test dates are untouched until final scoring.

The trained models and results are written to `output/`:

- `all_station_delay_model.joblib`: pooled model, supports stations not seen in
  training through unknown-category handling.
- `ndls_delay_model.joblib`: NDLS-only temporal model.
- `evaluation.json`: selected XGBoost-metaheuristic method, tuned parameters,
  optimizer convergence, NDLS and pooled future-date scores, and station scores.
- `algorithm_comparison.csv`: validation comparison of GA, PSO, WOA, and GWO.
- `test_predictions.csv`: row-level predictions from the untouched pooled test set.

To score a CSV whose rows contain the same engineered feature columns, run:

```powershell
python src/predict.py --model output\all_station_delay_model.joblib --input next_stop_features.csv --output predictions.csv
```

The output contains a point estimate and a calibrated 90% residual interval in
minutes. For a new station code, use the pooled model; unknown station codes
are accepted by the encoder. Actual accuracy at an unseen station still depends
on how similar its traffic and reporting pattern are to the training stations.

## Interactive dashboard

After training, launch the Streamlit dashboard from the project root:

```powershell
python -m streamlit run src/dashboard.py
```

The dashboard shows NDLS and pooled metrics, lets you compare station scores,
and accepts feature CSVs for interactive next-stop predictions with uncertainty
intervals. The **Platform twin** tab accepts an optional prediction-results CSV,
then builds a 20–60 movement demo day, allocates configurable platforms, checks
train length and minimum clearance, shows an interactive Gantt chart, and
compares FCFS with the priority-aware weighted interval scheduler in SimPy.
It also shows local TreeSHAP feature contributions for uploaded predictions.
Streamlit prints a local address to open in your browser.

### Platform allocation and stress testing

Run the twin after installing the additional `simpy` dependency (included in
`requirements.txt`). The demo scheduler's default is six 700 m platforms and a
five-minute clearance. These are scenario assumptions and can be changed in the
dashboard. Weighted interval scheduling handles overlapping reservations;
priority weights determine conflict resolution and lower-priority reservations
may be moved if they have not started. No train is assigned if its length
exceeds every configured platform.

The twin compares the resulting schedule with a first-come, first-served
baseline using the same generated arrivals, dwell assumptions, and platform
configuration. The dashboard's 10,000-run stress button perturbs estimated
arrival times and dwell durations and sometimes removes one platform. Perturbation
ranges are stated in the output and are assumptions, not empirical failure
probabilities. The metrics report wait, utilization, throughput, clearance and
length violations, unassigned movements, runtime, and stress-test distributions.
These results describe only the configured synthetic scenario.

The Monte Carlo replay also records static platform conflict risk before queue
recovery. Its zero resource-collision count is guaranteed by single-capacity
platform queues in the replay; it is not an independent safety certification.

To save a reproducible default run (JSON metrics and both schedule CSVs), run:

```powershell
$env:PYTHONPATH = "src"
python src/run_platform_simulation.py --station NDLS --movements 36 --platforms 6 --demand moderate --seed 42
```

To consume model output, pass a CSV exported from **Make predictions** with a
`predicted_delay_min` column using `--predictions path\to\predictions.csv`.

## Separate station datasets

After the train histories are cached, create one model-ready CSV per station:

```powershell
python src/create_station_datasets.py --stations NDLS AGC GWL
```

This writes `NDLS.csv`, `AGC.csv`, and `GWL.csv` under
`data/processed/stations/`, plus a `summary.json`. Each CSV contains only
examples whose next-stop arrival target is that station, along with the shared
feature columns, date, train number, and delay target. If a selected station is
not in the currently cached corridor sample, it is skipped; add more train
histories or pass a larger raw CSV with `--csv` to include it.

## Evaluation design

Rows are split chronologically by journey date (60% training, 10% validation,
10% calibration, 20% final holdout). Each optimizer minimizes RMSE on the same
validation sample; the best method is selected by validation RMSE, with MAE as a
tie-breaker. The selected parameters are refit on train plus validation dates.
A 90% absolute-residual interval is calibrated on separate calibration dates
and reported with observed coverage on the final holdout. The pooled model is
evaluated overall and by target station. The NDLS-specific model gives a
separate future-date check.

This is an adaptation of Gao et al., not a reproduction of their experiment:
their study used dispatching-command and adjacent-train features, a 1.9-million
record Chinese high-speed rail dataset, GPU training, and much larger optimizer
budgets. Those command fields are unavailable in this Indian dataset. The
dashboard records the smaller search budget and selects only from results on
this project's own validation dates.

The source reports early/on-time running as zero, so its delay labels are
one-sided and the model cannot learn negative delay. Rows without a reported
stop status are excluded. Results describe this third-party dataset and should
not be presented as a live railway operations guarantee. Platform assignment,
train length, platform geometry, actual dispatch commands, and signaling rules
are absent and must be configured or sourced separately before evaluating a
platform scheduler.

## Initial sample result

The first completed run used four NDLS-serving train histories discovered from
the indexed viewer sample: 154,587 raw stop rows produced 89,941 consecutive,
reported-stop examples across 108 target station codes. The NDLS-specific
future-date holdout contained 62 examples (MAE 9.33 min, RMSE 11.81 min). The
pooled model scored 24,249 future-date examples over 80 other target stations
(MAE 6.22 min, RMSE 10.85 min). The 90% interval coverage was 88.7% for the
NDLS holdout and 86.8% overall. This small, four-train corridor sample is a
working baseline, not a representative national benchmark; its scores do not
meet the synopsis goal of MAE below 4.5 minutes. Full station-level results are
in `output/evaluation.json` after a training run.

## Source

`yadavsaurabh/indian-railways-runs` on Hugging Face, licensed GPL-3.0. The
dataset is an independent third-party collection and is not affiliated with
Indian Railways or the live-status service named in its dataset card. See the
dataset card before redistribution or public submission.

