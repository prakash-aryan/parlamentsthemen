import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

REPO = Path("/home/merabro/hackapertus-liebefeld")
sys.path.insert(0, str(REPO / "src"))
from parltopics.cards import load, render  # noqa: E402

J = Path(os.environ.get("JUDGE_DIR", "runs/judge"))
EMB = REPO / "runs/emb"
MODEL = "microsoft/harrier-oss-v1-0.6b"
QUERY = "Instruct: Given a search query, retrieve Swiss parliamentary affairs that match it\nQuery: "


def affair_vectors(ids):
    order = pd.read_parquet(EMB / "embeddings_harrier-oss-v1-0.6b_ids.parquet").iloc[:, 0].to_numpy()
    pos = {int(a): i for i, a in enumerate(order)}
    mat = np.load(EMB / "embeddings_harrier-oss-v1-0.6b.npy", mmap_mode="r")
    keep = [a for a in ids if a in pos]
    return keep, np.stack([np.asarray(mat[pos[a]], dtype=np.float32) for a in keep])


def macro_ap(model, cards: dict[str, dict], test: pd.DataFrame, has) -> tuple[float, int]:
    ids, x = affair_vectors([int(a) for a in test.affair_id])
    test = test.set_index("affair_id").loc[ids].reset_index()
    q = model.encode([QUERY + render(c) for c in cards.values()], normalize_embeddings=True)
    x = x / np.linalg.norm(x, axis=1, keepdims=True)
    aps = []
    for (cid, _), v in zip(cards.items(), q):
        y = test.apply(lambda r: has(r, cid), axis=1).to_numpy(int)
        if y.sum():
            aps.append(average_precision_score(y, x @ v))
    return float(np.mean(aps)), len(aps)


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL, device="cpu")
    rows = []
    sg = {p.stem.split("_")[1]: load(p) for p in sorted((REPO / "cards/sg").glob("sg_*.yaml"))}
    test = pd.read_parquet(J / "data/sg_test_sample.parquet")
    ap, n = macro_ap(model, sg, test, lambda r, c: c in [str(t) for t in r.topic_ids])
    rows.append({"set": "St. Gallen, 868 test affairs", "system": "harrier embeddings, card similarity (no labels)", "topics": n, "macro_AP": round(ap, 3)})
    names = json.loads((J / "cards/descriptor/labels.json").read_text())
    desc = {p.stem: load(p) for p in sorted((J / "cards/descriptor").glob("descriptor*.yaml"))}
    test = pd.read_parquet(J / "data/descriptor_test_sample.parquet")
    ap, n = macro_ap(model, desc, test, lambda r, c: names.get(c) in list(r.labels))
    rows.append({"set": "30 new topics, 1,500 federal affairs", "system": "harrier embeddings, card similarity (no labels)", "topics": n, "macro_AP": round(ap, 3)})
    df = pd.DataFrame(rows)
    df.to_csv(REPO / "docs/results/zero_shot_embeddings.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
