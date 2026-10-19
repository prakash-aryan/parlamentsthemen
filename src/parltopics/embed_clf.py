import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from parltopics.encoder import area_ids

SEED = 20261018


def main() -> None:
    ap = argparse.ArgumentParser(description="Demokratis-style baseline: one logistic regression per topic on affair embeddings.")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--emb-dir", type=Path, required=True)
    ap.add_argument("--tag", default="harrier-oss-v1-0.6b")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-train", type=int, default=20000)
    args = ap.parse_args()
    E = np.load(args.emb_dir / f"embeddings_{args.tag}.npy", mmap_mode="r")
    ids = pd.read_parquet(args.emb_dir / f"embeddings_{args.tag}_ids.parquet")["affair_id"].to_numpy()
    row = {int(a): i for i, a in enumerate(ids)}
    vec = lambda frame: np.asarray(E[[row[int(a)] for a in frame.affair_id]], dtype=np.float32)
    args.out.mkdir(parents=True, exist_ok=True)

    def fit(x, y, frames, name):
        clf = LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced").fit(x, y)
        for split, f in frames.items():
            pd.DataFrame({"affair_id": f.affair_id, "score": clf.decision_function(vec(f))}).to_parquet(args.out / f"embclf_{split}_{name}.parquet", index=False)

    exclude = set()
    for s in ("dev_sample", "test_sample", "curia_dev_sample", "curia_test_sample"):
        exclude |= set(pd.read_parquet(args.data / f"{s}.parquet", columns=["affair_id"])["affair_id"])
    curia = pd.read_parquet(args.data / "curia.parquet")
    train = curia[(curia.split == "train") & ~curia.affair_id.isin(exclude) & curia.affair_id.isin(row.keys())]
    train = train.sample(n=min(args.n_train, len(train)), random_state=SEED)
    frames = {s: pd.read_parquet(args.data / f"curia_{s}_sample.parquet", columns=["affair_id"]) for s in ("dev", "test")}
    x = vec(train)
    names = Path(__file__).resolve().parents[2] / "cards" / "curia" / "names.csv"
    for a in area_ids(names):
        y = train.topic_ids.apply(lambda t: a in list(t)).to_numpy(int)
        if y.sum() >= 5:
            fit(x, y, frames, f"curia_{a}")
    digit = pd.read_parquet(args.data / "probe_train_digit.parquet", columns=["affair_id", "label"])
    digit = digit[digit.affair_id.isin(row.keys())]
    fit(vec(digit), digit.label.to_numpy(int), {s: pd.read_parquet(args.data / f"{s}_sample.parquet", columns=["affair_id"]) for s in ("dev", "test")},
        "digitalisation")
    print(f"EMBCLF_DONE curia train {len(train)}, digit train {len(digit)}")


if __name__ == "__main__":
    main()
