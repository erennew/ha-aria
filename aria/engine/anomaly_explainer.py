"""IsolationForest anomaly explanation via path tracing.

Traces the isolation path of a sample across all trees in an
IsolationForest ensemble. Features that appear at split nodes more
frequently are more responsible for isolating (flagging) the sample.

Tier 3+ only — called from MLEngine when anomaly is detected.
"""

import numpy as np


class AnomalyExplainer:
    """Explain anomalies by tracing IsolationForest isolation paths."""

    def explain(
        self,
        iso_forest,
        X_sample: np.ndarray,
        feature_names: list[str],
        top_n: int = 3,
    ) -> list[dict]:
        """Identify top contributing features for an anomaly.

        Traces the decision path through each tree in the ensemble,
        counting how often each feature appears at a split node.
        Features used more often in the isolation path contribute
        more to the anomaly score.

        Args:
            iso_forest: Trained IsolationForest model.
            X_sample: Single sample as (1, n_features) array.
            feature_names: List of feature names (or empty for index-based).
            top_n: Number of top contributors to return.

        Returns:
            List of dicts with "feature" and "contribution" keys,
            sorted by contribution descending.
        """
        n_features = X_sample.shape[1]
        contributions = np.zeros(n_features)

        for estimator in iso_forest.estimators_:
            tree = estimator.tree_
            # decision_path returns sparse CSR matrix
            node_indicator = estimator.decision_path(X_sample)
            node_indices = node_indicator.indices

            for node_id in node_indices:
                feature_id = tree.feature[node_id]
                if feature_id >= 0:  # -2 means leaf node
                    contributions[feature_id] += 1.0

        # Normalize to sum to 1.0
        total = contributions.sum()
        if total > 0:
            contributions /= total

        # Build names — fall back to index if names not provided
        names = feature_names if len(feature_names) == n_features else [f"feature_{i}" for i in range(n_features)]

        # Sort by contribution descending, take top_n
        top_indices = np.argsort(contributions)[::-1][: min(top_n, n_features)]

        return [
            {
                "feature": names[i],
                "contribution": round(float(contributions[i]), 4),
            }
            for i in top_indices
            if contributions[i] > 0
        ]
