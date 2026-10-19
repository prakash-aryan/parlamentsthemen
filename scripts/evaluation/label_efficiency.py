import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

REPO = Path("/home/merabro/hackapertus-liebefeld")
J = Path(os.environ.get("JUDGE_DIR", "runs/judge"))
EMB = REPO / "runs/emb"
SIZES = (25, 50, 100, 200, 400, 600)
SEEDS = range(5)


def embeddings(ids: list[int]) -> dict[int, np.ndarray]:
    order = pd.read_parquet(EMB / "embeddings_harrier-oss-v1-0.6b_ids.parquet").iloc[:, 0].to_numpy()
    pos = {int(a): i for i, a in enumerate(order)}
    mat = np.load(EMB / "embeddings_harrier-oss-v1-0.6b.npy", mmap_mode="r")
    return {a: np.asarray(mat[pos[a]], dtype=np.float32) for a in ids if a in pos}


def main() -> None:
    dev, test = pd.read_parquet(J / "data/sg_dev_sample.parquet"), pd.read_parquet(J / "data/sg_test_sample.parquet")
    vec = embeddings([int(a) for a in pd.concat([dev.affair_id, test.affair_id])])
    dev, test = dev[dev.affair_id.isin(vec)].reset_index(drop=True), test[test.affair_id.isin(vec)].reset_index(drop=True)
    xd, xt = np.stack([vec[int(a)] for a in dev.affair_id]), np.stack([vec[int(a)] for a in test.affair_id])
    areas = sorted({str(t) for v in pd.concat([dev.topic_ids, test.topic_ids]) for t in v})
    lab = lambda df, a: df.topic_ids.apply(lambda v: a in [str(x) for x in v]).to_numpy(int)
    rows = []
    for n in SIZES:
        for seed in SEEDS:
            idx = np.random.default_rng(seed).choice(len(dev), min(n, len(dev)), replace=False)
            aps = []
            for a in areas:
                y, yt = lab(dev, a)[idx], lab(test, a)
                if yt.sum() == 0:
                    continue
                if y.sum() == 0 or y.sum() == len(y):
                    aps.append(yt.mean())
                    continue
                clf = LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced").fit(xd[idx], y)
                aps.append(average_precision_score(yt, clf.decision_function(xt)))
            rows.append({"labelled_affairs": n, "seed": seed, "macro_AP": float(np.mean(aps))})
            if n >= len(dev):
                break
    df = pd.DataFrame(rows).groupby("labelled_affairs").macro_AP.agg(["mean", "std", "count"]).round(3)
    df.to_csv(REPO / "docs/results/label_efficiency_st_gallen.csv")
    print(df.to_string())
    print("test affairs", len(test), "areas", len(areas), "dev affairs", len(dev))


if __name__ == "__main__":
    main()
