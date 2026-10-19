import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import average_precision_score

from parltopics.evaluate import best_threshold, weighted_prf

SEED = 20261018
DEFINITIONS = {
    "tg": 'Affairs of the cantonal parliament of Thurgau filed under "{}".',
    "zug": 'Affairs of the city parliament of Zug that fall under "{}".',
    "descriptor": 'Federal parliamentary affairs that the Parliamentary Services index with the keyword "{}".',
}
CURIA_TO_APS = {
    "15": ["8.1"], "2841": ["5.1"], "4": ["1.1", "1.2", "2.1", "2.2"], "24": ["8.2", "8.3"], "52": ["6.4"],
    "8": ["3.1"], "28": ["4.1"], "9": ["7.2"], "48": ["6.1"], "2811": ["4.1"], "34": ["4.4", "6.1"],
    "55": ["8.4"], "66": ["6.2"], "44": ["8.5"], "10": ["3.1"], "12": ["7.1"], "32": ["4.2"],
    "2836": ["5.2", "5.1"], "2846": ["6.3"], "2446": ["8.2"], "1236": ["7.1"], "1216": ["7.1"], "2831": ["4.3"],
    "36": ["4.2"], "421": ["1.2"], "1211": ["7.1"], "1231": ["3.1", "7.1"], "1221": ["1.2", "7.1"],
}


def split_names(value) -> list[str]:
    return [x.strip() for x in str(value).split("|") if x.strip()] if isinstance(value, str) else []


def texts(data: Path) -> pd.DataFrame:
    t = pd.read_parquet(data / "affair_text.parquet", columns=["affair_id", "text"])
    return t[t.text.fillna("").str.strip().str.len() > 0]


def excluded(data: Path, train_jsonl: Path | None) -> set[int]:
    ids = set()
    for s in ("dev_sample", "test_sample", "curia_dev_sample", "curia_test_sample", "sg_dev_sample", "sg_test_sample"):
        if (data / f"{s}.parquet").exists():
            ids |= set(pd.read_parquet(data / f"{s}.parquet", columns=["affair_id"]).affair_id.astype(int))
    if train_jsonl:
        ids |= {json.loads(line)["_meta"]["affair_id"] for line in train_jsonl.open(encoding="utf-8")}
    return ids


def write_cards(kind: str, names: list[str], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for i, name in enumerate(sorted(names)):
        cid = f"{kind}{i:03d}"
        card = {"id": cid, "version": 1, "name": name, "definition": DEFINITIONS[kind].format(name), "include": [name], "exclude": [], "terms": {}}
        (out / f"{cid}.yaml").write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False))
        mapping[cid] = name
    (out / "labels.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1))


def save(kind: str, dev: pd.DataFrame, test: pd.DataFrame, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for split, df in (("dev", dev), ("test", test)):
        df[["affair_id", "text", "labels"]].to_parquet(out / f"{kind}_{split}_sample.parquet", index=False)
    print(kind, "dev", len(dev), "test", len(test), "topics", len({n for ls in pd.concat([dev, test]).labels for n in ls}))


def build_cantonal(kind: str, body: str, labels: Path, text: pd.DataFrame, n_dev: int, n_test: int):
    kw = pd.read_csv(labels / "cantonal_affairs_keywords.csv", usecols=["openparldata_id", "body_key", "begin_date", "keywords"], dtype=str)
    kw = kw[kw.body_key == body].assign(labels=lambda d: d.keywords.map(split_names), affair_id=lambda d: d.openparldata_id.astype(int))
    df = kw[kw.labels.map(len) > 0].merge(text, on="affair_id")
    dev, test = df[df.begin_date.str[:4] < "2024"], df[df.begin_date.str[:4] >= "2024"]
    return dev.sample(n=min(n_dev, len(dev)), random_state=SEED), test.sample(n=min(n_test, len(test)), random_state=SEED)


def build_descriptors(labels: Path, text: pd.DataFrame, exclude: set[int], top: int, n_topics: int,
                      n_pos_dev: int, n_pos_test: int, n_rand_dev: int, n_rand_test: int):
    kw = pd.read_csv(labels / "che_affairs_keywords.csv", usecols=["openparldata_id", "descriptors_de"], dtype=str)
    kw["names"] = kw.descriptors_de.map(split_names)
    ranked = [n for n, _ in Counter(n for ns in kw.names for n in ns).most_common()]
    pool = kw[kw.names.map(len) > 0].assign(affair_id=lambda d: d.openparldata_id.astype(int))
    pool = pool[~pool.affair_id.isin(exclude)].merge(text, on="affair_id").reset_index(drop=True)
    pool_freq = Counter(n for ns in pool.names for n in ns)
    candidates = [n for n in ranked[top:] if pool_freq[n] >= n_pos_dev + n_pos_test]
    rng = np.random.default_rng(SEED)
    chosen = set(rng.choice(candidates, size=min(n_topics, len(candidates)), replace=False).tolist())
    dev_ids, test_ids = set(), set()
    for name in sorted(chosen):
        have = [a for a, ns in zip(pool.affair_id, pool.names) if name in ns and a not in dev_ids | test_ids]
        pick = rng.permutation(have)
        test_ids |= set(pick[:n_pos_test].tolist())
        dev_ids |= set(pick[n_pos_test:n_pos_test + n_pos_dev].tolist())
    rest = rng.permutation([a for a in pool.affair_id if a not in dev_ids | test_ids])
    test_ids |= set(rest[:n_rand_test].tolist())
    dev_ids |= set(rest[n_rand_test:n_rand_test + n_rand_dev].tolist())
    pool["labels"] = pool.names.map(lambda ns: [n for n in ns if n in chosen])
    return pool[pool.affair_id.isin(dev_ids)], pool[pool.affair_id.isin(test_ids)], sorted(chosen)


def build_languages(data: Path, out: Path) -> None:
    fed = pd.read_parquet(data / "affair_text.parquet", columns=["affair_id", "fed_de", "fed_fr", "fed_it"])
    for s in ("curia_dev_sample", "curia_test_sample"):
        df = pd.read_parquet(data / f"{s}.parquet").drop(columns=["text"]).merge(fed, on="affair_id")
        df = df[df[["fed_de", "fed_fr", "fed_it"]].notna().all(axis=1)]
        df = df[df[["fed_de", "fed_fr", "fed_it"]].apply(lambda r: min(len(x.strip()) for x in r) > 0, axis=1)]
        for lang in ("de", "fr", "it"):
            (out / f"lang_{lang}").mkdir(parents=True, exist_ok=True)
            df.assign(text=df[f"fed_{lang}"]).drop(columns=["fed_de", "fed_fr", "fed_it"]).to_parquet(out / f"lang_{lang}" / f"{s}.parquet", index=False)
        print(s, len(df), "affairs with all three languages")


def aps_shortlist(data: Path, scores: Path, prefix: str, k: int, out: Path) -> None:
    test = pd.read_parquet(data / "curia_test_sample.parquet", columns=["affair_id", "text"])
    frames = [pd.read_parquet(p).assign(chapter=p.stem.split("_test_")[1]) for p in scores.glob(f"{prefix}_test_aps_*.parquet")]
    s = pd.concat(frames).dropna(subset=["score"])
    top = s.sort_values("score", ascending=False).groupby("affair_id").head(k)
    out.mkdir(parents=True, exist_ok=True)
    for chapter, part in top.groupby("chapter"):
        test[test.affair_id.isin(part.affair_id)].to_parquet(out / f"{chapter}.parquet", index=False)
        print(chapter, part.affair_id.nunique())


def evaluate(dev: pd.DataFrame, test: pd.DataFrame, scores: Path, prefix: str, labels: dict[str, str], min_pos: int) -> pd.DataFrame:
    rows = []
    for cid, name in labels.items():
        tp, dp = scores / f"{prefix}_test_{cid}.parquet", scores / f"{prefix}_dev_{cid}.parquet"
        if not tp.exists() or not dp.exists():
            continue
        d = dev.merge(pd.read_parquet(dp)[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        t = test.merge(pd.read_parquet(tp)[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        yd, yt = d.labels.map(lambda x: name in x).to_numpy(bool), t.labels.map(lambda x: name in x).to_numpy(bool)
        if yt.sum() < min_pos or yd.sum() == 0:
            continue
        thr = best_threshold(yd, d.score.to_numpy(float), np.ones(len(d)))
        pred = t.score.to_numpy(float) >= thr
        p, r, f = weighted_prf(yt, pred, np.ones(len(t)))
        rows.append({"topic": name, "test_pos": int(yt.sum()), "base_rate": round(yt.mean(), 3), "AP": average_precision_score(yt, t.score),
                     "precision": p, "recall": r, "F1": f, "tp": int((yt & pred).sum()), "fp": int((~yt & pred).sum()), "fn": int((yt & ~pred).sum())})
    df = pd.DataFrame(rows).sort_values("test_pos", ascending=False)
    tp, fp, fn = df.tp.sum(), df.fp.sum(), df.fn.sum()
    mp, mr = tp / (tp + fp), tp / (tp + fn)
    print(df.round(3).to_string(index=False))
    print(f"\n{len(df)} topics | macro: AP {df.AP.mean():.3f} F1 {df.F1.mean():.3f} base rate {df.base_rate.mean():.3f} | "
          f"micro: P {mp:.3f} R {mr:.3f} F1 {2 * mp * mr / (mp + mr):.3f}")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluation sets for further label sources, and a generic multi-label evaluation.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--data", type=Path, required=True)
    b.add_argument("--labels", type=Path, required=True)
    b.add_argument("--train-jsonl", type=Path)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--cards", type=Path, required=True)
    sl = sub.add_parser("shortlist")
    sl.add_argument("--data", type=Path, required=True)
    sl.add_argument("--scores", type=Path, required=True)
    sl.add_argument("--prefix", required=True)
    sl.add_argument("--k", type=int, default=3)
    sl.add_argument("--out", type=Path, required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--kind", required=True, choices=["tg", "zug", "descriptor", "aps"])
    e.add_argument("--samples", type=Path, required=True)
    e.add_argument("--scores", type=Path, required=True)
    e.add_argument("--prefix", required=True)
    e.add_argument("--cards", type=Path, required=True)
    e.add_argument("--min-pos", type=int, default=3)
    e.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.cmd == "build":
        text = texts(args.data)
        for kind, body, n_test in (("tg", "TG", 1000), ("zug", "1711", 600)):
            dev, test = build_cantonal(kind, body, args.labels, text, 400, n_test)
            save(kind, dev, test, args.out)
            write_cards(kind, sorted({n for ls in pd.concat([dev, test]).labels for n in ls}), args.cards / kind)
        dev, test, chosen = build_descriptors(args.labels, text, excluded(args.data, args.train_jsonl), 400, 30, 10, 25, 300, 750)
        save("descriptor", dev, test, args.out)
        write_cards("descriptor", chosen, args.cards / "descriptor")
        build_languages(args.data, args.out)
    elif args.cmd == "shortlist":
        aps_shortlist(args.data, args.scores, args.prefix, args.k, args.out)
    elif args.kind == "aps":
        dev = pd.read_parquet(args.samples / "curia_dev_sample.parquet")
        test = pd.read_parquet(args.samples / "curia_test_sample.parquet")
        for df in (dev, test):
            df["labels"] = df.topic_ids.map(lambda ts: sorted({c for t in ts for c in CURIA_TO_APS.get(str(t), [])}))
        chapters = {p.stem: p.stem.removeprefix("aps_").replace("_", ".") for p in args.cards.glob("aps_*.yaml") if p.stem.count("_") == 2}
        df = evaluate(dev, test, args.scores, args.prefix, chapters, args.min_pos)
    else:
        dev = pd.read_parquet(args.samples / f"{args.kind}_dev_sample.parquet")
        test = pd.read_parquet(args.samples / f"{args.kind}_test_sample.parquet")
        df = evaluate(dev, test, args.scores, args.prefix, json.loads((args.cards / "labels.json").read_text()), args.min_pos)
    if args.cmd == "evaluate" and args.out:
        df.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
