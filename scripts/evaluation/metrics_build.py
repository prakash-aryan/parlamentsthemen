import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, "/home/merabro/hackapertus-liebefeld/src")
from parltopics.evaluate import best_threshold, metrics, weighted_prf

REPO = Path("/home/merabro/hackapertus-liebefeld")
H = Path(sys.argv[1])
OUT = REPO / "docs/comparison"
OUT.mkdir(parents=True, exist_ok=True)

ddev = pd.read_parquet(H / "dev_sample.parquet")
dtest = pd.read_parquet(H / "test_sample.parquet")
cdev = pd.read_parquet(H / "curia_dev_sample.parquet")
ctest = pd.read_parquet(H / "curia_test_sample.parquet")
sdev = pd.read_parquet(H / "sg_dev_sample.parquet")
stest = pd.read_parquet(H / "sg_test_sample.parquet")
areas = pd.read_csv(REPO / "cards/curia/names.csv", dtype={"topic_id": str})
s1 = REPO / "runs/stage1"
TR = H / "trained"

SYSTEMS = [
    ("keyword", "Keyword search with the card's terms", "card", "stage1:keyword_v2", "local_curia:keyword"),
    ("bge_m3", "BGE-M3 similarity to the card", "card", "stage1:bge_m3_v2", None),
    ("laya", "Laya multilingual (open decision model)", "card", "stage1:laya_v2", None),
    ("kev9b", "Kev-9B (open decision model on Qwen)", "card", "stage1:kev9b_v2", None),
    ("decisio", "decisio (open decision model on Gemma-4-31B)", "card", "stage1:decisio_v2", None),
    ("apertus8b", "Apertus 1.5 8B, untrained, yes/no readout", "card", "stage1:apertus8b_v2", "local_curia:apertus8b"),
    ("apertus70b", "Apertus 1.5 70B, untrained, yes/no readout", "card", "stage1:apertus70b_v2", "local_curia:apertus70b"),
    ("run_A", "Run A: trained Apertus 8B, softened labels", "card", "trained:A_main", "trained:A_main"),
    ("run_B", "Run B: trained Apertus 8B, plain labels", "card", "trained:B_hard", "trained:B_hard"),
    ("run_C", "Run C: trained Apertus 8B, no digitalisation", "card", "trained:C_nodigit", "trained:C_nodigit"),
    ("run_D", "Run D: run C with more federal affairs", "card", "trained:D_more", "trained:D_more"),
    ("run_E", "Run E: run C with two epochs", "card", "trained:E_2ep", "trained:E_2ep"),
    ("run_F", "Run F: run C plus Thurgau scheme", "card", "trained:F_tg", "trained:F_tg"),
    ("parltopics8b", "Apertus-ParlTopics-8B (run C plus 400 descriptors)", "card", "trained:G_desc", "trained:G_desc"),
    ("probe", "Classifier on Apertus 8B hidden states", "labels", "flat:probe_scores/probe", "flat:probe_scores/probe"),
    ("xlmr_legal", "legal XLM-RoBERTa large (2023 study method)", "labels", "flat:xlmr/xlmr", "flat:xlmr/xlmr"),
    ("mmbert", "mmBERT base, same method", "labels", "flat:encoders/mmbert", "flat:encoders/mmbert"),
    ("mmbert2k", "mmBERT base, 2,048 tokens, same method", "labels", "flat:encoders/mmbert2k", "flat:encoders/mmbert2k"),
    ("xlmr_general", "XLM-RoBERTa large (general), same method", "labels", "flat:encoders/xlmrgen", "flat:encoders/xlmrgen"),
    ("granite", "granite-embedding-311m-multilingual-r2, same method", "labels", "flat:encoders/granite", "flat:encoders/granite"),
    ("embclf", "Embedding classifier (harrier + logistic regression, Demokratis method)", "labels", "flat:embclf/embclf", "flat:embclf/embclf"),
]


def digit_paths(spec):
    kind, name = spec.split(":")
    if kind == "stage1":
        return s1 / f"dev_{name}.parquet", s1 / f"test_{name}.parquet"
    if kind == "trained":
        return TR / name / f"{name}_dev_digitalisation.parquet", TR / name / f"{name}_test_digitalisation.parquet"
    return H / f"{name}_dev_digitalisation.parquet", H / f"{name}_test_digitalisation.parquet"


def curia_path(spec, split, area):
    kind, name = spec.split(":")
    if kind == "local_curia":
        return REPO / "runs/curia" / f"{name}_{split}_curia_{area}.parquet"
    if kind == "trained":
        return TR / name / f"{name}_{split}_curia_{area}.parquet"
    return H / f"{name}_{split}_curia_{area}.parquet"


def load_scores(path):
    return pd.read_parquet(path)[["affair_id", "score"]] if path.exists() else None


rows, dec = [], {}
digit_scores = {}
for key, label, family, dspec, _ in SYSTEMS:
    dp, tp = digit_paths(dspec)
    d, t = load_scores(dp), load_scores(tp)
    if d is None or t is None:
        print("missing digit", key, dp.exists(), tp.exists())
        continue
    dd = ddev[["affair_id", "label", "weight"]].merge(d, on="affair_id").dropna(subset=["score"])
    tt = dtest[["affair_id", "label", "weight"]].merge(t, on="affair_id").dropna(subset=["score"])
    thr = metrics(dd)["threshold"]
    m = metrics(tt, thr)
    digit_scores[key] = (dd, tt, thr)
    rows.append({"task": "digitalisation", "system": key, "description": label, "family": family, "n_test": m["n"],
                 "AP": m["avg_precision"], "ROC_AUC": m["roc_auc"], "precision": m["precision"], "recall": m["recall"], "F1": m["f1"]})
    dec[("digitalisation", key)] = tt.assign(decision=(tt.score >= thr).astype(int))[["affair_id", "score", "decision"]]


def blend(a, b, name, label):
    da, ta, _ = digit_scores[a]
    db, tb, _ = digit_scores[b]
    d = da.merge(db[["affair_id", "score"]], on="affair_id", suffixes=("_a", "_b"))
    t = ta.merge(tb[["affair_id", "score"]], on="affair_id", suffixes=("_a", "_b"))
    mu, sd = d[["score_a", "score_b"]].mean(), d[["score_a", "score_b"]].std()
    lr = LogisticRegression(C=1.0, max_iter=1000).fit((d[["score_a", "score_b"]] - mu) / sd, d.label.astype(int), sample_weight=d.weight)
    d["score"] = lr.decision_function((d[["score_a", "score_b"]] - mu) / sd)
    t["score"] = lr.decision_function((t[["score_a", "score_b"]] - mu) / sd)
    thr = metrics(d)["threshold"]
    m = metrics(t, thr)
    digit_scores[name] = (d, t, thr)
    rows.append({"task": "digitalisation", "system": name, "description": label, "family": "blend", "n_test": m["n"],
                 "AP": m["avg_precision"], "ROC_AUC": m["roc_auc"], "precision": m["precision"], "recall": m["recall"], "F1": m["f1"]})
    dec[("digitalisation", name)] = t.assign(decision=(t.score >= thr).astype(int))[["affair_id", "score", "decision"]]


blend("run_C", "embclf", "run_C+embclf", "Run C and embedding classifier, logistic blend fitted on dev (recomputed here)")
blend("parltopics8b", "embclf", "parltopics8b+embclf", "Apertus-ParlTopics-8B and embedding classifier, logistic blend fitted on dev (recomputed here)")

curia_dec = {}
for key, label, family, _, cspec in SYSTEMS:
    if cspec is None:
        continue
    per = []
    tp_all = fp_all = fn_all = 0
    frames = []
    for area in areas.topic_id:
        dp, tp = curia_path(cspec, "dev", area), curia_path(cspec, "test", area)
        d, t = load_scores(dp), load_scores(tp)
        if d is None or t is None:
            continue
        dd = cdev.merge(d, on="affair_id").dropna(subset=["score"])
        tt = ctest.merge(t, on="affair_id").dropna(subset=["score"])
        yd = dd.topic_ids.apply(lambda x: area in [str(v) for v in x]).to_numpy(bool)
        yt = tt.topic_ids.apply(lambda x: area in [str(v) for v in x]).to_numpy(bool)
        if yt.sum() == 0 or yd.sum() == 0:
            continue
        thr = best_threshold(yd, dd.score.to_numpy(float), np.ones(len(dd)))
        pred = tt.score.to_numpy(float) >= thr
        p, r, f = weighted_prf(yt, pred, np.ones(len(tt)))
        per.append({"area": area, "AP": average_precision_score(yt, tt.score), "AUC": roc_auc_score(yt, tt.score), "F1": f})
        tp_all += int((yt & pred).sum()); fp_all += int((~yt & pred).sum()); fn_all += int((yt & ~pred).sum())
        frames.append(pd.DataFrame({"affair_id": tt.affair_id, "topic": area, "label": yt.astype(int), "score": tt.score, "decision": pred.astype(int)}))
    if len(per) < 20:
        print("curia incomplete", key, len(per))
        continue
    per = pd.DataFrame(per)
    mp, mr = tp_all / (tp_all + fp_all), tp_all / (tp_all + fn_all)
    held = per[per.area.isin(["66", "55", "2831", "2446", "2811"])]
    rows.append({"task": "curia", "system": key, "description": label, "family": family, "n_test": len(ctest), "areas": len(per),
                 "AP": per.AP.mean(), "ROC_AUC": per.AUC.mean(), "macro_F1": per.F1.mean(), "precision": mp, "recall": mr,
                 "F1": 2 * mp * mr / (mp + mr), "AP_5_held_out_areas": held.AP.mean() if len(held) == 5 else np.nan})
    curia_dec[key] = pd.concat(frames)


def curia_blend(a, b, name, label):
    per, held = [], []
    for area in areas.topic_id:
        spec = dict((k, c) for k, *_, c in SYSTEMS)
        paths = [(curia_path(spec[x], "dev", area), curia_path(spec[x], "test", area)) for x in (a, b)]
        if not all(dp.exists() and tp.exists() for dp, tp in paths):
            continue
        d = cdev.merge(load_scores(paths[0][0]), on="affair_id").merge(load_scores(paths[1][0]), on="affair_id", suffixes=("_a", "_b")).dropna(subset=["score_a", "score_b"])
        t = ctest.merge(load_scores(paths[0][1]), on="affair_id").merge(load_scores(paths[1][1]), on="affair_id", suffixes=("_a", "_b")).dropna(subset=["score_a", "score_b"])
        yd = d.topic_ids.apply(lambda x: area in [str(v) for v in x]).to_numpy(bool)
        yt = t.topic_ids.apply(lambda x: area in [str(v) for v in x]).to_numpy(bool)
        if yd.sum() == 0 or yt.sum() == 0:
            continue
        X = d[["score_a", "score_b"]]
        mu, sd = X.mean(), X.std()
        lr = LogisticRegression(C=1.0, max_iter=1000).fit((X - mu) / sd, yd.astype(int))
        ap = average_precision_score(yt, lr.decision_function((t[["score_a", "score_b"]] - mu) / sd))
        per.append(ap)
        if area in ["66", "55", "2831", "2446", "2811"]:
            held.append(ap)
    rows.append({"task": "curia", "system": name, "description": label, "family": "blend", "n_test": len(ctest), "areas": len(per),
                 "AP": float(np.mean(per)), "AP_5_held_out_areas": float(np.mean(held)) if len(held) == 5 else np.nan})


curia_blend("parltopics8b", "embclf", "parltopics8b+embclf", "Apertus-ParlTopics-8B and embedding classifier, logistic blend per area fitted on dev")

for key, label, family, _, cspec in SYSTEMS:
    if family != "card" or cspec is None:
        continue
    kind, name = cspec.split(":")
    per, frames = [], []
    for code in sorted({str(c) for ts in stest.topic_ids for c in ts}):
        if kind == "trained":
            dp, tp = TR / name / f"{name}_dev_sg_{code}.parquet", TR / name / f"{name}_test_sg_{code}.parquet"
        elif name == "apertus8b":
            dp, tp = REPO / f"runs/sg/apertus8b_dev_sg_{code}.parquet", REPO / f"runs/sg/apertus8b_test_sg_{code}.parquet"
        else:
            continue
        d, t = load_scores(dp), load_scores(tp)
        if d is None or t is None:
            continue
        dd = sdev.merge(d, on="affair_id").dropna(subset=["score"])
        tt = stest.merge(t, on="affair_id").dropna(subset=["score"])
        yd = dd.topic_ids.apply(lambda x: code in [str(v) for v in x]).to_numpy(bool)
        yt = tt.topic_ids.apply(lambda x: code in [str(v) for v in x]).to_numpy(bool)
        if yt.sum() == 0 or yd.sum() == 0:
            continue
        thr = best_threshold(yd, dd.score.to_numpy(float), np.ones(len(dd)))
        pred = tt.score.to_numpy(float) >= thr
        p, r, f = weighted_prf(yt, pred, np.ones(len(tt)))
        per.append({"AP": average_precision_score(yt, tt.score), "AUC": roc_auc_score(yt, tt.score), "F1": f})
        frames.append(pd.DataFrame({"affair_id": tt.affair_id, "topic": code, "label": yt.astype(int), "score": tt.score, "decision": pred.astype(int)}))
    if not per:
        continue
    per = pd.DataFrame(per)
    rows.append({"task": "st_gallen", "system": key, "description": label, "family": family, "n_test": len(stest), "areas": len(per),
                 "AP": per.AP.mean(), "ROC_AUC": per.AUC.mean(), "macro_F1": per.F1.mean()})
    curia_dec[("sg", key)] = pd.concat(frames)

met = pd.DataFrame(rows)
met.round(4).to_csv(OUT / "metrics.csv", index=False)
print(met.round(3).to_string(index=False))

parts = []
w = dtest[["affair_id", "label", "weight"]].rename(columns={"label": "label"})
digit = w.assign(task="digitalisation", topic="digitalisation", label=w.label.astype(int))
for (task, key), d in dec.items():
    digit = digit.merge(d[["affair_id", "decision"]].rename(columns={"decision": key}), on="affair_id", how="left")
parts.append(digit)
cur = None
for key, d in curia_dec.items():
    if isinstance(key, tuple):
        continue
    x = d[["affair_id", "topic", "label", "decision"]].rename(columns={"decision": key})
    cur = x if cur is None else cur.merge(x, on=["affair_id", "topic", "label"], how="outer")
parts.append(cur.assign(task="curia", weight=1.0))
sg = None
for key, d in curia_dec.items():
    if not isinstance(key, tuple):
        continue
    x = d[["affair_id", "topic", "label", "decision"]].rename(columns={"decision": key[1]})
    sg = x if sg is None else sg.merge(x, on=["affair_id", "topic", "label"], how="outer")
parts.append(sg.assign(task="st_gallen", weight=1.0))
allp = pd.concat(parts, ignore_index=True)
cols = ["task", "affair_id", "topic", "label", "weight"] + [k for k, *_ in SYSTEMS] + ["run_C+embclf", "parltopics8b+embclf"]
allp = allp[[c for c in cols if c in allp.columns]]
for c in allp.columns[5:]:
    allp[c] = allp[c].astype("Int64")
allp.to_csv(OUT / "decisions.csv", index=False)
print("decisions rows", len(allp))
pickle_path = H.parent / "scores.pkl"
pd.to_pickle({"digit": digit_scores, "curia": curia_dec}, pickle_path)
