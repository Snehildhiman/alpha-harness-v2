"""Train, test and keep the models.

**Honest testing.** Alphas are ordered by when they were simulated; the newest 20% are held
out and never seen in training, and the reported accuracy is on them. A random split would
flatter the models: near-copies of one idea land on both sides and the test is memorised.
Early stopping uses the newest slice of the *training* rows, never the test rows.

**Baselines.** Every figure is reported beside what a model that knows nothing would score
(the training median for a number, a coin flip's 0.5 AUC for pass/fail), so a model that has
not learned anything cannot look good.

Once tested, each model is fitted again on every labelled Alpha with the same number of
trees, and that is the one kept and used.
"""

import json
import math
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from .features import (
    RESULT_COLUMNS,
    FieldInfo,
    Parsed,
    Vocabulary,
    categorical_columns,
    date_of,
    fit_vocabulary,
    matrix,
    read_expression,
    result_matrix,
    targets_of,
)

log = structlog.get_logger(__name__)

#: Share of Alphas, newest first, held out for testing.
TEST_SHARE = 0.2
#: Share of the training rows, newest first, used to decide when to stop adding trees.
VALID_SHARE = 0.15
#: Fewest labelled Alphas a target needs before a model is trained for it.
MIN_LABELS = 300
#: Fewest of the rarer class a pass/fail target needs in training.
MIN_CLASS = 40

PARAMS: dict[str, Any] = {
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "seed": 7,
    "num_threads": max(1, (os.cpu_count() or 2) - 1),
}
ROUNDS, PATIENCE = 2000, 50

#: What each regression target means, for the screen.
LABELS = {
    "prod_corr": "Prod correlation",
    "power_pool_corr": "Power Pool correlation",
    "self_corr": "Self-correlation",
    "sharpe": "Sharpe",
    "fitness": "Fitness",
    "turnover": "Turnover",
    "post:prod_corr": "Prod correlation, once simulated",
    "post:power_pool_corr": "Power Pool correlation, once simulated",
    "post:self_corr": "Self-correlation, once simulated",
}
#: Targets re-learned with BRAIN's reported results as extra inputs (see ``RESULT_COLUMNS``).
POST_TARGETS = ("prod_corr", "power_pool_corr", "self_corr")
POST = "post:"


def label_of(target: str) -> str:
    if target.startswith("check:"):
        # BRAIN names checks by the failure (LOW_SHARPE, HIGH_TURNOVER); say what passing means.
        name = target.removeprefix("check:")
        for prefix in ("LOW_", "HIGH_"):
            name = name.removeprefix(prefix)
        words = name.replace("_", " ").lower()
        return f"Passes the {words.replace('sharpe', 'Sharpe')} check"
    return LABELS.get(target, target)


@dataclass(slots=True)
class Report:
    target: str
    label: str
    kind: str  # regression | classification | skipped
    labelled: int
    trained: bool
    n_train: int = 0
    n_test: int = 0
    #: Regression: mae, spearman, baseline_mae. Classification: auc, base_rate, accuracy.
    metrics: dict[str, float] = field(default_factory=dict)
    trees: int = 0
    top_features: list[tuple[str, float]] = field(default_factory=list)
    note: str | None = None


@dataclass(slots=True)
class ModelSet:
    vocab: Vocabulary
    boosters: dict[str, Any]
    reports: list[Report]
    trained_at: str
    alphas: int
    test_from: str | None
    #: Per target, the held-out predictions made before the final refit: ``(alpha ids,
    #: predictions, labels)``. Kept in memory only, for the gate that decides whether a newly
    #: trained set may replace the one in use.
    holdout: dict[str, tuple[list[str], np.ndarray, np.ndarray]] = field(default_factory=dict)

    # -- use ---------------------------------------------------------------------

    def predict(
        self, rows: list[dict[str, Any]], fields: dict[str, FieldInfo]
    ) -> list[dict[str, float]]:
        parsed = [read_expression(r.get("expression")) for r in rows]
        x = matrix(rows, parsed, fields, self.vocab)
        out: list[dict[str, float]] = [{} for _ in rows]
        for target, booster in self.boosters.items():
            if target.startswith(POST):
                continue  # needs the results of a simulation: see predict_post
            values = np.asarray(booster.predict(x), dtype=np.float64)
            for i, v in enumerate(values):
                out[i][target] = float(v)
        return out

    def predict_post(
        self, rows: list[dict[str, Any]], fields: dict[str, FieldInfo]
    ) -> list[dict[str, float]]:
        """The ``post:`` targets for simulated Alphas, keyed without the prefix."""
        posts = {t: b for t, b in self.boosters.items() if t.startswith(POST)}
        out: list[dict[str, float]] = [{} for _ in rows]
        if not posts or not rows:
            return out
        parsed = [read_expression(r.get("expression")) for r in rows]
        x = np.hstack([matrix(rows, parsed, fields, self.vocab), result_matrix(rows)])
        for target, booster in posts.items():
            values = np.asarray(booster.predict(x), dtype=np.float64)
            for i, v in enumerate(values):
                out[i][target.removeprefix(POST)] = float(v)
        return out

    # -- storage -----------------------------------------------------------------

    def save(self, folder: Path) -> None:
        """Written to a fresh folder and swapped in, so a crash never leaves half a set."""
        folder.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="models-", dir=folder.parent))
        (staging / "vocab.json").write_text(json.dumps(self.vocab.to_json()))
        (staging / "report.json").write_text(
            json.dumps(
                {
                    "trained_at": self.trained_at,
                    "alphas": self.alphas,
                    "test_from": self.test_from,
                    "reports": [asdict(r) for r in self.reports],
                    "models": {t: _file(t) for t in self.boosters},
                },
                indent=1,
            )
        )
        for target, booster in self.boosters.items():
            booster.save_model(str(staging / _file(target)))
        old = folder.with_name(folder.name + ".old")
        if old.exists():
            shutil.rmtree(old)
        if folder.exists():
            folder.rename(old)
        staging.rename(folder)
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)

    @classmethod
    def load(cls, folder: Path) -> ModelSet | None:
        report_file = folder / "report.json"
        if not report_file.exists():
            return None
        import lightgbm as lgb

        raw = json.loads(report_file.read_text())
        vocab = Vocabulary.from_json(json.loads((folder / "vocab.json").read_text()))
        boosters = {
            target: lgb.Booster(model_file=str(folder / name))
            for target, name in (raw.get("models") or {}).items()
            if (folder / name).exists()
        }
        reports = [_report(r) for r in raw.get("reports", [])]
        return cls(
            vocab=vocab,
            boosters=boosters,
            reports=reports,
            trained_at=raw.get("trained_at", ""),
            alphas=int(raw.get("alphas", 0)),
            test_from=raw.get("test_from"),
        )


def _report(raw: dict[str, Any]) -> Report:
    return Report(
        target=str(raw["target"]),
        label=str(raw["label"]),
        kind=str(raw["kind"]),
        labelled=int(raw["labelled"]),
        trained=bool(raw["trained"]),
        n_train=int(raw.get("n_train", 0)),
        n_test=int(raw.get("n_test", 0)),
        metrics={str(k): float(v) for k, v in (raw.get("metrics") or {}).items()},
        trees=int(raw.get("trees", 0)),
        top_features=[(str(n), float(g)) for n, g in raw.get("top_features") or []],
        note=raw.get("note"),
    )


def _file(target: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in target) + ".txt"


# -- metrics ------------------------------------------------------------------------


def _ranks(values: np.ndarray) -> np.ndarray:
    order = values.argsort(kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.arange(1, len(values) + 1)
    # Average ties so equal values share a rank.
    sorted_values = values[order]
    start = 0
    for end in range(1, len(values) + 1):
        if end == len(values) or sorted_values[end] != sorted_values[start]:
            ranks[order[start:end]] = (start + 1 + end) / 2
            start = end
    return ranks


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return math.nan
    ra, rb = _ranks(a), _ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return math.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    positives = labels == 1
    n_pos, n_neg = int(positives.sum()), int((~positives).sum())
    if n_pos == 0 or n_neg == 0:
        return math.nan
    ranks = _ranks(scores)
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


# -- training -----------------------------------------------------------------------


def _order(rows: list[dict[str, Any]]) -> list[int]:
    """Oldest first; undated Alphas count as oldest."""
    return sorted(
        range(len(rows)),
        key=lambda i: (date_of(rows[i].get("date_created")) or date.min, i),
    )


def train_all(
    rows: list[dict[str, Any]],
    fields: dict[str, FieldInfo],
    *,
    min_labels: int = MIN_LABELS,
    progress: Any = None,
) -> ModelSet:
    """Train one model per target with enough labels, test each on the newest Alphas."""
    import lightgbm as lgb

    order = _order(rows)
    rows = [rows[i] for i in order]
    parsed: list[Parsed] = [read_expression(r.get("expression")) for r in rows]
    cut = int(len(rows) * (1 - TEST_SHARE))
    vocab = fit_vocabulary(rows[:cut], parsed[:cut], fields)
    pre = matrix(rows, parsed, fields, vocab)
    post_x = np.hstack([pre, result_matrix(rows)])
    columns = vocab.columns()
    post_columns = [*columns, *(f"result:{c}" for c in RESULT_COLUMNS)]
    categorical = categorical_columns(vocab)
    labels = [targets_of(r) for r in rows]
    # The same correlation labels again, for models that also see the simulation's results.
    for found in labels:
        for target in POST_TARGETS:
            if target in found:
                found[POST + target] = found[target]
    counts: dict[str, int] = {}
    for found in labels:
        for target in found:
            counts[target] = counts.get(target, 0) + 1

    targets = sorted(counts, key=lambda t: (t.startswith("check:"), t))
    boosters: dict[str, Any] = {}
    reports: list[Report] = []
    holdout: dict[str, tuple[list[str], np.ndarray, np.ndarray]] = {}
    for done, target in enumerate(targets, start=1):
        if progress is not None:
            progress(done, len(targets), target)
        kind = "classification" if target.startswith("check:") else "regression"
        x = post_x if target.startswith(POST) else pre
        names = post_columns if target.startswith(POST) else columns
        have = np.array([i for i, found in enumerate(labels) if target in found], dtype=np.int64)
        y_all = np.array([labels[i][target] for i in have], dtype=np.float64)
        report = Report(target, label_of(target), kind, labelled=len(have), trained=False)
        reports.append(report)
        if len(have) < min_labels:
            report.kind, report.note = "skipped", f"Needs {min_labels} labelled Alphas"
            continue
        train_mask, test_mask = have < cut, have >= cut
        train_idx, test_idx = have[train_mask], have[test_mask]
        y_train, y_test = y_all[train_mask], y_all[test_mask]
        if len(test_idx) < 30 or len(train_idx) < min_labels // 2:
            report.kind, report.note = "skipped", "Too few labelled Alphas among the newest"
            continue
        if kind == "regression" and float(y_train.max() - y_train.min()) == 0.0:
            report.kind, report.note = "skipped", "Always the same value; nothing to learn yet"
            continue
        if kind == "classification":
            minority = min(int(y_train.sum()), int(len(y_train) - y_train.sum()))
            if minority < MIN_CLASS:
                report.kind = "skipped"
                report.note = "Almost always the same result; nothing to learn yet"
                continue
        stop = int(len(train_idx) * (1 - VALID_SHARE))
        params = {
            **PARAMS,
            "objective": "binary" if kind == "classification" else "huber",
            "metric": "auc" if kind == "classification" else "l1",
        }
        fit = lgb.Dataset(
            x[train_idx[:stop]],
            y_train[:stop],
            categorical_feature=categorical,
            free_raw_data=False,
        )
        valid = lgb.Dataset(
            x[train_idx[stop:]],
            y_train[stop:],
            categorical_feature=categorical,
            reference=fit,
            free_raw_data=False,
        )
        booster = lgb.train(
            params,
            fit,
            num_boost_round=ROUNDS,
            valid_sets=[valid],
            callbacks=[lgb.early_stopping(PATIENCE, verbose=False)],
        )
        trees = max(1, booster.best_iteration or booster.current_iteration())
        predicted = np.asarray(booster.predict(x[test_idx], num_iteration=trees), dtype=np.float64)
        if kind == "classification":
            report.metrics = {
                "auc": auc(y_test, predicted),
                "base_rate": float(y_test.mean()),
                "accuracy": float(((predicted >= 0.5) == (y_test == 1)).mean()),
            }
        else:
            median = float(np.median(y_train))
            report.metrics = {
                "mae": float(np.abs(predicted - y_test).mean()),
                "baseline_mae": float(np.abs(median - y_test).mean()),
                "spearman": spearman(predicted, y_test),
            }
        # A score that cannot be computed (one class, a constant) is left out, never NaN.
        report.metrics = {k: v for k, v in report.metrics.items() if math.isfinite(v)}
        # Kept model: every labelled Alpha, same number of trees.
        full = lgb.Dataset(
            x[have],
            y_all,
            categorical_feature=categorical,
            free_raw_data=False,
        )
        final = lgb.train(params, full, num_boost_round=trees)
        gains = final.feature_importance(importance_type="gain")
        top = sorted(zip(names, gains, strict=True), key=lambda c: -c[1])[:12]
        total = float(sum(gains)) or 1.0
        report.top_features = [(name, round(float(g) / total, 4)) for name, g in top if g > 0]
        holdout[target] = (
            [str(rows[i].get("alpha_id")) for i in test_idx],
            predicted,
            y_test,
        )
        report.n_train, report.n_test, report.trees, report.trained = (
            len(train_idx),
            len(test_idx),
            trees,
            True,
        )
        boosters[target] = final

    test_from = date_of(rows[cut].get("date_created")) if cut < len(rows) else None
    return ModelSet(
        vocab=vocab,
        boosters=boosters,
        reports=reports,
        trained_at=datetime.now(UTC).isoformat(timespec="seconds"),
        alphas=len(rows),
        test_from=test_from.isoformat() if test_from else None,
        holdout=holdout,
    )


# -- the gate -----------------------------------------------------------------------

#: Fewest Alphas the old set never saw before a comparison means anything.
GATE_MIN_ROWS = 30
#: How much worse, on average, a new set may score and still replace the old (noise).
GATE_TOLERANCE = 0.01
#: The targets the gate weighs: what decides submission.
GATE_TARGETS = ("prod_corr", "power_pool_corr", "sharpe", "fitness")


@dataclass(slots=True)
class Gate:
    accepted: bool
    reason: str
    #: ``(target, old score, new score, Alphas compared)``.
    compared: list[tuple[str, float, float, int]] = field(default_factory=list)


def _quality(target: str, predicted: np.ndarray, labels: np.ndarray) -> float:
    if target.startswith("check:"):
        return auc(labels, predicted)
    return spearman(predicted, labels)


def gate(
    old: ModelSet,
    new: ModelSet,
    rows: dict[str, dict[str, Any]],
    fields: dict[str, FieldInfo],
) -> Gate:
    """Whether ``new`` may replace ``old``: scored on Alphas ``old`` never trained on.

    Those are the new set's held-out Alphas simulated after ``old`` was trained. The new set is
    scored by its held-out predictions (made before it saw them), the old set by its own
    predictions; it is replaced unless it does worse on average beyond noise.
    """
    cutoff = old.trained_at[:10]
    compared: list[tuple[str, float, float, int]] = []
    for target, (ids, predicted, labels) in new.holdout.items():
        weighed = target in GATE_TARGETS or target.startswith("check:")
        if not weighed or target not in old.boosters:
            continue
        keep = [
            i
            for i, alpha_id in enumerate(ids)
            if str((rows.get(alpha_id) or {}).get("date_created") or "")[:10] > cutoff
        ]
        if len(keep) < GATE_MIN_ROWS:
            continue
        unseen = [rows[ids[i]] for i in keep]
        old_predicted = np.array([p.get(target, np.nan) for p in old.predict(unseen, fields)])
        old_score = _quality(target, old_predicted, labels[keep])
        new_score = _quality(target, predicted[keep], labels[keep])
        if math.isfinite(old_score) and math.isfinite(new_score):
            compared.append((target, old_score, new_score, len(keep)))
    if not compared:
        return Gate(True, "Not enough new Alphas to compare yet; the larger set is kept.")
    change = float(np.mean([n - o for _, o, n, _ in compared]))
    if change >= -GATE_TOLERANCE:
        return Gate(True, f"Scores {change:+.3f} on Alphas the old models never saw.", compared)
    return Gate(
        False, f"Scores {change:+.3f} on Alphas the old models never saw; kept the old.", compared
    )
