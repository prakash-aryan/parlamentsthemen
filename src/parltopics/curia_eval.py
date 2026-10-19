import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from parltopics.evaluate import best_threshold, weighted_prf
from sklearn.metrics import average_precision_score

SEED = 20261018


def make_samples(data: Path, train_jsonl: Path, n_test: int, n_dev: int, out: Path) -> None:
    text = pd.read_parquet(data / "affair_text.parquet", columns=["affair_id", "text", "lang", "text_source"])
    curia = pd.read_parquet(data / "curia.parquet").merge(text, on="affair_id")
    trained = {json.loads(l)["_meta"]["affair_id"] for l in train_jsonl.open(encoding="utf-8")}
    test = curia[curia.split == "test"].sample(n=n_test, random_state=SEED)
    dev = curia[(curia.split == "train") & ~curia.affair_id.isin(trained)].sample(n=n_dev, random_state=SEED)
    for name, df in (("curia_test_sample", test), ("curia_dev_sample", dev)):
        df = df.assign(topic_ids=df.topic_ids.apply(lambda t: [str(x) for x in t]))
        df.to_parquet(out / f"{name}.parquet", index=False)
        print(name, len(df))


def evaluate(sample_dir: Path, scores_dir: Path, prefix: str, held_out: set[str]) -> pd.DataFrame:
    rows = []
    dev = pd.read_parquet(sample_dir / "curia_dev_sample.parquet")
    test = pd.read_parquet(sample_dir / "curia_test_sample.parquet")
    for path in sorted(scores_dir.glob(f"{prefix}_test_curia_*.parquet")):
        area = path.stem.rsplit("_", 1)[1]
        dpath = scores_dir / path.name.replace("_test_", "_dev_")
        d = dev.merge(pd.read_parquet(dpath)[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        t = test.merge(pd.read_parquet(path)[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        yd = d.topic_ids.apply(lambda x: area in x).to_numpy(bool)
        yt = t.topic_ids.apply(lambda x: area in x).to_numpy(bool)
        if yt.sum() == 0 or yd.sum() == 0:
            continue
        thr = best_threshold(yd, d.score.to_numpy(float), np.ones(len(d)))
        pred = t.score.to_numpy(float) >= thr
        p, r, f = weighted_prf(yt, pred, np.ones(len(t)))
        rows.append({"area": area, "held_out": area in held_out, "test_pos": int(yt.sum()),
                     "AP": average_precision_score(yt, t.score), "precision": p, "recall": r, "F1": f,
                     "tp": int((yt & pred).sum()), "fp": int((~yt & pred).sum()), "fn": int((yt & ~pred).sum())})
    df = pd.DataFrame(rows).sort_values("test_pos", ascending=False)
    tp, fp, fn = df.tp.sum(), df.fp.sum(), df.fn.sum()
    micro_p, micro_r = tp / (tp + fp), tp / (tp + fn)
    print(df.round(3).to_string(index=False))
    print(f"\nmacro: AP {df.AP.mean():.3f} F1 {df.F1.mean():.3f} | micro: P {micro_p:.3f} R {micro_r:.3f} F1 {2 * micro_p * micro_r / (micro_p + micro_r):.3f}")
    if df.held_out.any():
        h = df[df.held_out]
        print(f"held-out areas: macro AP {h.AP.mean():.3f} F1 {h.F1.mean():.3f}; trained areas: macro AP {df[~df.held_out].AP.mean():.3f} F1 {df[~df.held_out].F1.mean():.3f}")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Curia Vista subject-area samples and multi-label evaluation.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("samples")
    s.add_argument("--data", type=Path, required=True)
    s.add_argument("--train-jsonl", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--n-test", type=int, default=1000)
    s.add_argument("--n-dev", type=int, default=600)
    e = sub.add_parser("evaluate")
    e.add_argument("--samples", type=Path, required=True)
    e.add_argument("--scores", type=Path, required=True)
    e.add_argument("--prefix", required=True)
    e.add_argument("--held-out", default="66,55,2831,2446,2811")
    e.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.cmd == "samples":
        make_samples(args.data, args.train_jsonl, args.n_test, args.n_dev, args.out)
    else:
        df = evaluate(args.samples, args.scores, args.prefix, set(args.held_out.split(",")))
        if args.out:
            df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
