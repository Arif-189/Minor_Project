"""SHAP explanations using XGBoost's native TreeSHAP implementation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb


def shap_contributions(pipeline, frame: pd.DataFrame, original_features: list[str]) -> pd.DataFrame:
    """Return local TreeSHAP values grouped back to original input columns.

    The fitted sklearn pipeline transforms categoricals into one-hot columns.
    Their individual SHAP values are summed so the caller sees one contribution
    per original project feature. The final `baseline_value` is the SHAP bias;
    baseline plus all feature contributions equals the XGBoost prediction.
    """
    transformer = pipeline.named_steps["features"]
    regressor = pipeline.named_steps["regressor"]
    encoded = transformer.transform(frame[original_features])
    encoded_names = transformer.get_feature_names_out()
    raw = regressor.get_booster().predict(xgb.DMatrix(encoded), pred_contribs=True)
    grouped = np.zeros((len(frame), len(original_features)), dtype=float)
    for column_index, encoded_name in enumerate(encoded_names):
        name = str(encoded_name)
        matches = [i for i, feature in enumerate(original_features)
                   if name == f"num__{feature}" or name.startswith(f"cat__{feature}_")]
        if matches:
            grouped[:, matches[0]] += raw[:, column_index]
    result = pd.DataFrame(grouped, columns=original_features, index=frame.index)
    result["baseline_value"] = raw[:, -1]
    return result
