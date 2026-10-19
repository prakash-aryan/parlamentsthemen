import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


def weighted_prf(y, pred, w):
    tp = float(np.sum(w * (y & pred)))
    fp = float(np.sum(w * (~y & pred)))
    fn = float(np.sum(w * (y & ~pred)))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def best_threshold(y, s, w):
    best = (-1.0, None)
    for t in np.unique(np.quantile(s, np.linspace(0.0, 1.0, 401))):
        f = weighted_prf(y, s >= t, w)[2]
        if f > best[0]:
            best = (f, float(t))
    return best[1]


def metrics(df: pd.DataFrame, threshold: float | None = None) -> dict:
    y = df["label"].to_numpy(bool)
    s = df["score"].to_numpy(float)
    w = df["weight"].to_numpy(float)
    out = {"n": int(len(df)), "positives": int(y.sum())}
    if y.all() or not y.any():
        return out
    out["avg_precision"] = float(average_precision_score(y, s, sample_weight=w))
    out["roc_auc"] = float(roc_auc_score(y, s, sample_weight=w))
    t = best_threshold(y, s, w) if threshold is None else threshold
    p, r, f = weighted_prf(y, s >= t, w)
    out.update(threshold=t, precision=p, recall=r, f1=f)
    return out


def platt(df: pd.DataFrame) -> tuple[float, float]:
    from sklearn.linear_model import LogisticRegression

    lr = LogisticRegression(C=1e6, max_iter=1000)
    lr.fit(df[["score"]].to_numpy(float), df["label"].to_numpy(int), sample_weight=df["weight"].to_numpy(float))
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def calibration_error(df: pd.DataFrame, a: float, b: float, bins: int = 10) -> dict:
    p = 1 / (1 + np.exp(-(a * df["score"].to_numpy(float) + b)))
    y = df["label"].to_numpy(float)
    w = df["weight"].to_numpy(float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece = sum(abs(np.average(y[idx == i], weights=w[idx == i]) - np.average(p[idx == i], weights=w[idx == i]))
              * w[idx == i].sum() for i in range(bins) if (idx == i).any()) / w.sum()
    brier = float(np.average((p - y) ** 2, weights=w))
    return {"ece": float(ece), "brier": brier}


def evaluate(sample: pd.DataFrame, scores: pd.DataFrame, groups: list[str], dev: pd.DataFrame | None = None) -> dict:
    df = sample.merge(scores[["affair_id", "score"]], on="affair_id", how="left")
    missing = int(df["score"].isna().sum())
    df = df.dropna(subset=["score"])
    threshold = None
    result = {"missing_scores": missing}
    if dev is not None:
        threshold = metrics(dev)["threshold"]
        a, b = platt(dev)
        result["platt"] = {"a": a, "b": b}
        result["calibration"] = calibration_error(df, a, b)
    overall = metrics(df, threshold)
    result["overall"] = overall
    for g in groups:
        result[g] = {str(k): metrics(part, overall.get("threshold")) for k, part in df.groupby(g)}
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Weighted precision, recall and ranking metrics for scored samples.")
    ap.add_argument("--sample", type=Path, required=True)
    ap.add_argument("--scores", type=Path, nargs="+", required=True)
    ap.add_argument("--dev-sample", type=Path, help="fix thresholds and calibration on this sample")
    ap.add_argument("--dev-scores", type=Path, nargs="*", help="dev scores, in the same order as --scores")
    ap.add_argument("--groups", nargs="*", default=["lang", "level", "text_source"])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    sample = pd.read_parquet(args.sample)
    dev_sample = pd.read_parquet(args.dev_sample) if args.dev_sample else None
    report = {}
    for i, path in enumerate(args.scores):
        dev = None
        if dev_sample is not None:
            dev = dev_sample.merge(pd.read_parquet(args.dev_scores[i])[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        report[path.stem] = evaluate(sample, pd.read_parquet(path), args.groups, dev)
    rows = []
    for name, r in report.items():
        o = r["overall"]
        rows.append({"system": name, "AP": o.get("avg_precision"), "ROC-AUC": o.get("roc_auc"),
                     "precision": o.get("precision"), "recall": o.get("recall"), "F1": o.get("f1"),
                     "ECE": r.get("calibration", {}).get("ece"), "missing": r["missing_scores"]})
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
