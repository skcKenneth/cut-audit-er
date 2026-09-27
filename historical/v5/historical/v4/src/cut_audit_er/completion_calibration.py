"""One fixed, small calibration recipe using observable scores only.

Fitting receives explicit binary supervised targets; deployment receives no
graphs, identifiers, truth maps, utilities or evaluation results. Callers own
entity separation, first-occurrence physical-event deduplication, and exclusion
of logically forced events from statistical fitting. No resampling, balancing,
feature search or parameter search is performed here.

Paid logical overrides assume consistent noiseless purchased answers. Inference
does not authorize deletion or reduce the physical pair-query cost. Raw products
are never clipped: epsilon is used only when constructing a logit feature.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from numbers import Integral, Real
import time
import warnings


SCHEMA = "cut-audit-completion-calibration-v1"
LOGIT_EPSILON = 1e-12
KINDS = ("plan_depth", "plan_c0", "edge_negative")
MODES = ("logistic", "constant_laplace_no_events", "constant_laplace_one_class")
NOISELESS_ASSUMPTION = "consistent_noiseless_paid_answers"


def _probability(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Probability must be a real number")
    value = float(value)
    if not math.isfinite(value) or not 0. <= value <= 1.:
        raise ValueError("Probability must be finite and in [0,1]")
    return value


def _depth(value):
    if isinstance(value, bool) or not isinstance(value, Integral) or not 1 <= value <= 4:
        raise ValueError("Plan depth must be an integer from one through four")
    return int(value)


def _outcomes(values):
    out = []
    for value in values:
        if not isinstance(value, (bool, Integral)) or value not in (0, 1):
            raise ValueError("Fitting outcome must be binary bool/integer")
        out.append(int(value))
    return out


def feature_logit(probability):
    """Finite logit feature, without modifying the supplied raw probability."""
    p = min(1. - LOGIT_EPSILON, max(LOGIT_EPSILON, _probability(probability)))
    return math.log(p) - math.log1p(-p)


def _sigmoid(value):
    # These branches avoid exp overflow. Numerical saturation is not clipping.
    if value >= 0:
        return 1. / (1. + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1. + exponent)


def c0_eligible(outcomes):
    """The predeclared optional-ablation support rule; no tunable threshold."""
    values = _outcomes(outcomes)
    return sum(values) >= 10 and len(values) - sum(values) >= 10


def logical_plan_override(paid_constraints):
    """Read only paid logical facts; evaluator/identifier fields are unused."""
    if paid_constraints is None:
        return None
    if not isinstance(paid_constraints, Mapping):
        raise ValueError("Paid constraint description must be a mapping")
    if (paid_constraints.get("logical_assumption") != NOISELESS_ASSUMPTION or
            paid_constraints.get("history_consistent") is not True):
        raise ValueError("Logical override requires consistent noiseless paid history")
    value = paid_constraints.get("logical_all_negative_probability")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real) or value not in (0, 1):
        raise ValueError("Paid logical completion probability must be exactly zero/one or None")
    return float(value)


def logical_edge_override(paid_relation):
    """Noiseless paid equivalence relation, never a gold/evaluator relation."""
    if paid_relation == "unresolved":
        return None
    if paid_relation == "known_match":
        return 0.
    if paid_relation == "known_nonmatch":
        return 1.
    raise ValueError("Unknown paid edge relation")


def _specification(kind):
    names = ["logit_raw_product", "depth_minus_one"] if kind == "plan_depth" else [
        "logit_raw_product" if kind == "plan_c0" else "logit_negative_edge_score"]
    return {"C": 1., "regularization": "L2", "solver": "lbfgs", "max_iter": 1000,
            "tol": 1e-4, "fit_intercept": True, "class_weight": None,
            "sample_weight": "uniform_unit_weight", "random_state": 0,
            "feature_logit_epsilon": LOGIT_EPSILON, "feature_names": names,
            "raw_probability_clipped": False, "resampling": False,
            "logical_override_assumption": NOISELESS_ASSUMPTION}


@dataclass(frozen=True)
class LogisticCalibrationModel:
    kind: str
    mode: str
    coefficients: tuple[float, ...]
    intercept: float | None
    constant_probability: float | None
    n_samples: int
    n_positive: int
    n_negative: int
    converged: bool | None
    n_iter: int
    fit_warnings: tuple[str, ...]
    fit_seconds: float
    sklearn_version: str | None

    def __post_init__(self):
        if self.kind not in KINDS or self.mode not in MODES:
            raise ValueError("Unknown calibration kind/mode")
        for value in (self.n_samples, self.n_positive, self.n_negative, self.n_iter):
            if type(value) is not int or value < 0:
                raise ValueError("Invalid calibration count")
        if self.n_positive + self.n_negative != self.n_samples:
            raise ValueError("Calibration class counts disagree")
        if not isinstance(self.coefficients, tuple) or not isinstance(self.fit_warnings, tuple):
            raise ValueError("Coefficients/warnings must be immutable tuples")
        if not math.isfinite(self.fit_seconds) or self.fit_seconds < 0:
            raise ValueError("Invalid fit time")
        if not all(isinstance(value, str) for value in self.fit_warnings):
            raise ValueError("Invalid optimizer warnings")
        if self.mode == "logistic":
            size = 2 if self.kind == "plan_depth" else 1
            if (len(self.coefficients) != size or self.intercept is None or
                    not all(isinstance(v, Real) and math.isfinite(v) for v in (*self.coefficients, self.intercept)) or
                    self.constant_probability is not None or type(self.converged) is not bool or
                    not self.n_positive or not self.n_negative or not isinstance(self.sklearn_version, str)):
                raise ValueError("Invalid fitted logistic model")
        else:
            expected_mode = "constant_laplace_no_events" if self.n_samples == 0 else "constant_laplace_one_class"
            expected_probability = (self.n_positive + 1.) / (self.n_samples + 2.)
            if (self.mode != expected_mode or (self.n_positive and self.n_negative) or
                    self.coefficients or self.intercept is not None or self.converged is not None or
                    self.n_iter != 0 or self.sklearn_version is not None or
                    self.constant_probability != expected_probability):
                raise ValueError("Invalid explicit Laplace fallback model")

    def _predict(self, features):
        if self.mode != "logistic":
            return self.constant_probability
        value = self.intercept + math.fsum(c * x for c, x in zip(self.coefficients, features))
        return _sigmoid(value)

    def predict_plan(self, raw_product, depth, *, paid_constraints=None):
        if self.kind not in ("plan_depth", "plan_c0"):
            raise ValueError("Edge model cannot predict a plan directly")
        q, size = _probability(raw_product), _depth(depth)
        logical = logical_plan_override(paid_constraints)
        if logical is not None:
            return logical
        features = [feature_logit(q)]
        if self.kind == "plan_depth":
            features.append(size - 1)
        return self._predict(features)

    def predict_edge(self, negative_probability, *, paid_relation="unresolved"):
        if self.kind != "edge_negative":
            raise ValueError("Plan model cannot predict an edge marginal")
        value = _probability(negative_probability)
        logical = logical_edge_override(paid_relation)
        return logical if logical is not None else self._predict([feature_logit(value)])

    def to_dict(self):
        return {"schema": SCHEMA, "kind": self.kind, "mode": self.mode,
                "coefficients": list(self.coefficients), "intercept": self.intercept,
                "constant_probability": self.constant_probability,
                "n_samples": self.n_samples, "n_positive": self.n_positive, "n_negative": self.n_negative,
                "converged": self.converged, "n_iter": self.n_iter, "fit_warnings": list(self.fit_warnings),
                "fit_seconds": self.fit_seconds, "sklearn_version": self.sklearn_version,
                "specification": _specification(self.kind)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("kind") not in KINDS:
            raise ValueError("Unknown calibration artifact schema/kind")
        if value.get("specification") != _specification(value["kind"]):
            raise ValueError("Calibration specification differs from the fixed recipe")
        fields = {key: item for key, item in value.items() if key not in ("schema", "specification")}
        if set(fields) != set(cls.__dataclass_fields__):
            raise ValueError("Calibration artifact fields differ from schema")
        try:
            fields["coefficients"] = tuple(fields["coefficients"])
            fields["fit_warnings"] = tuple(fields["fit_warnings"])
            return cls(**fields)
        except (TypeError, OverflowError) as exc:
            raise ValueError("Invalid calibration artifact values") from exc


def _fit(kind, features, outcomes):
    started = time.perf_counter()
    positives, total = sum(outcomes), len(outcomes)
    if len(features) != total:
        raise ValueError("Features and fitting outcomes differ in length")
    if total == 0 or positives in (0, total):
        return LogisticCalibrationModel(kind, "constant_laplace_no_events" if total == 0 else "constant_laplace_one_class",
            (), None, (positives + 1.) / (total + 2.), total, positives, total - positives,
            None, 0, (), time.perf_counter() - started, None)
    import numpy as np
    import sklearn
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    # Default L2 avoids the deprecated penalty argument on the installed 1.9.x.
    estimator = LogisticRegression(C=1., solver="lbfgs", max_iter=1000, tol=1e-4,
                                   fit_intercept=True, class_weight=None, random_state=0)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        estimator.fit(np.asarray(features, dtype=float), np.asarray(outcomes, dtype=int))
    converged = not any(issubclass(w.category, ConvergenceWarning) for w in recorded)
    return LogisticCalibrationModel(kind, "logistic", tuple(float(v) for v in estimator.coef_[0]),
        float(estimator.intercept_[0]), None, total, positives, total - positives,
        converged, int(estimator.n_iter_[0]), tuple(str(w.message) for w in recorded),
        time.perf_counter() - started, sklearn.__version__)


def fit_plan_calibrator(raw_products, depths, outcomes, *, include_depth=True):
    """Fit first-occurrence, unresolved plan events assembled by the caller."""
    if type(include_depth) is not bool:
        raise ValueError("include_depth must be a bool")
    probabilities, sizes, targets = list(raw_products), list(depths), _outcomes(outcomes)
    if len(probabilities) != len(sizes):
        raise ValueError("Plan probabilities and depths differ in length")
    features = []
    for probability, size in zip(probabilities, sizes):
        row, size = [feature_logit(probability)], _depth(size)
        if include_depth:
            row.append(size - 1)
        features.append(row)
    return _fit("plan_depth" if include_depth else "plan_c0", features, targets)


def fit_edge_calibrator(negative_probabilities, outcomes):
    """Fit unique unresolved selected-edge negative events, with unit weights."""
    return _fit("edge_negative", [[feature_logit(p)] for p in negative_probabilities], _outcomes(outcomes))
