import os
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/merabro/hackapertus-liebefeld/src")
from parltopics.evaluate import best_threshold
from parltopics.schemes import CURIA_TO_APS

J = Path(os.environ.get("JUDGE_DIR", "runs/judge"))
REPO = Path("/home/merabro/hackapertus-liebefeld")


def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def judge(model):
    out = {}
    for line in (J / f"batch/results_{model}.jsonl").open():
        r = json.loads(line)
        out[r["custom_id"]] = parse(r.get("text")) if r["type"] == "succeeded" else None
    return out


def prf(truth, pred, topics):
    tp = sum(len(truth[a] & pred[a]) for a in truth)
    fp = sum(len(pred[a] - truth[a]) for a in truth)
    fn = sum(len(truth[a] - pred[a]) for a in truth)
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    f1s = []
    for t in topics:
        tt = sum(1 for a in truth if t in truth[a] and t in pred[a])
        ff = sum(1 for a in truth if t not in truth[a] and t in pred[a])
        nn = sum(1 for a in truth if t in truth[a] and t not in pred[a])
        if tt + nn:
            f1s.append(2 * tt / max(2 * tt + ff + nn, 1))
    return {"micro_P": round(p, 3), "micro_R": round(r, 3), "micro_F1": round(2 * p * r / max(p + r, 1e-9), 3),
            "macro_F1": round(float(np.mean(f1s)), 3) if f1s else None, "exact": round(float(np.mean([truth[a] == pred[a] for a in truth])), 3)}


def kappa(a, b, topics):
    x = np.array([t in a[i] for i in a for t in topics]); y = np.array([t in b[i] for i in a for t in topics])
    po = (x == y).mean(); pe = x.mean() * y.mean() + (1 - x.mean()) * (1 - y.mean())
    return round(float((po - pe) / (1 - pe)), 3)


def decided_topics(prefix_dev, prefix_test, dev, test, label_of, topics, scores=J / "scores"):
    pred = {a: set() for a in test.affair_id}
    for t in topics:
        dp, tp = scores / f"{prefix_dev}{t}.parquet", scores / f"{prefix_test}{t}.parquet"
        if not dp.exists() or not tp.exists():
            continue
        d = dev.merge(pd.read_parquet(dp)[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        y = d.apply(lambda r: t in label_of(r), axis=1).to_numpy(bool)
        if y.sum() == 0:
            continue
        thr = best_threshold(y, d.score.to_numpy(float), np.ones(len(d)))
        s = pd.read_parquet(tp).set_index("affair_id").score
        for a in pred:
            if a in s.index and s[a] >= thr:
                pred[a].add(t)
    return pred


def main():
    man = pd.read_parquet(J / "batch/manifest.parquet")
    op = judge("opus")
    rows = []
    for task, key in (("curia", "topics"), ("sg", "topics"), ("tg", "topics"), ("zug", "topics"), ("descriptor", "topics")):
        m = man[man.task == task]
        truth = {a: set(json.loads(l)) for a, l in zip(m.affair_id, m.labels)}
        pred = {a: {str(x) for x in (op.get(f"{task}-{a}") or {}).get(key, [])} for a in truth}
        topics = sorted({t for v in truth.values() for t in v} | {t for v in pred.values() for t in v})
        rows.append({"set": task, "system": "Claude Opus 5.5", "n": len(truth), **prf(truth, pred, topics)})
        if task == "curia":
            dev = pd.read_parquet(J / "curia_dev_sample.parquet"); test = pd.read_parquet(J / "curia_test_sample.parquet")
            g = decided_topics("G_desc_dev_curia_", "G_desc_test_curia_", dev, test[test.affair_id.isin(truth)], lambda r: [str(x) for x in r.topic_ids], topics)
        elif task == "sg":
            dev = pd.read_parquet(J / "data/sg_dev_sample.parquet"); test = pd.read_parquet(J / "data/sg_test_sample.parquet")
            g = decided_topics("G_desc_dev_sg_", "G_desc_test_sg_", dev, test[test.affair_id.isin(truth)], lambda r: [str(x) for x in r.topic_ids], topics)
        else:
            g = None
        if g is not None:
            rows.append({"set": task, "system": "Apertus-ParlTopics-8B", "n": len(truth), **prf(truth, g, topics)})
            rows.append({"set": task, "system": "kappa Opus vs Apertus-ParlTopics-8B", "n": len(truth), "micro_F1": kappa(pred, g, topics)})
    m = man[man.task == "aps"]
    fed = m[m.labels != "null"]
    truth = {a: {c for t in json.loads(l) for c in CURIA_TO_APS.get(str(t), [])} for a, l in zip(fed.affair_id, fed.labels)}
    jch = {a: {str(x) for x in (op.get(f"aps-{a}") or {}).get("chapters", [])} for a in m.affair_id}
    chapters = sorted({c for v in CURIA_TO_APS.values() for c in v})
    rows.append({"set": "aps chapters, federal (vs Curia mapping)", "system": "Claude Opus 5.5", "n": len(truth), **prf(truth, {a: jch[a] for a in truth}, chapters)})
    dev = pd.read_parquet(J / "curia_dev_sample.parquet"); test = pd.read_parquet(J / "curia_test_sample.parquet")
    lab = lambda r: [c.replace(".", "_") for t in r.topic_ids for c in CURIA_TO_APS.get(str(t), [])]
    gch = decided_topics("G_desc_dev_aps_", "G_desc_test_aps_", dev, test[test.affair_id.isin(truth)], lab, [c.replace(".", "_") for c in chapters])
    gch = {a: {c.replace("_", ".") for c in v} for a, v in gch.items()}
    rows.append({"set": "aps chapters, federal (vs Curia mapping)", "system": "Apertus-ParlTopics-8B", "n": len(truth), **prf(truth, gch, chapters)})
    rows.append({"set": "aps chapters, federal (vs Curia mapping)", "system": "kappa Opus vs Apertus-ParlTopics-8B", "n": len(truth), "micro_F1": kappa({a: jch[a] for a in truth}, gch, chapters)})
    rows.append({"set": "aps chapters, federal: Apertus-ParlTopics-8B scored against Opus as reference", "system": "Apertus-ParlTopics-8B", "n": len(truth), **prf({a: jch[a] for a in truth}, gch, chapters)})
    df = pd.DataFrame(rows)
    df.to_csv(J / "judge_scores_opus.csv", index=False)
    print(df.to_string(index=False))
    n_ch = np.mean([len(v) for v in jch.values()])
    lv = man[man.task == "aps"].assign(level=lambda d: np.where(d.labels != "null", "federal", "cantonal or city"))
    print(f"\nOpus APS: mean chapters per affair {n_ch:.2f}; parse failures {sum(1 for k, v in op.items() if v is None or v == {})}")


if __name__ == "__main__":
    main()
