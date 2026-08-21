from __future__ import annotations

import numpy as np
from cfpb_triage.modeling.router import multiclass_brier


def test_brier_penalizes_unseen_true_label_with_missing_class_probability() -> None:
    probabilities = np.asarray([[0.7, 0.3]])
    score = multiclass_brier(
        probabilities,
        labels=["Unseen product"],
        classes=np.asarray(["Credit card", "Mortgage"]),
    )
    # Known-class probabilities contribute .7^2 + .3^2 and the unavailable true
    # class contributes (0 - 1)^2. Omitting the latter understates unseen-label risk.
    assert score == 1.58
