import argparse
import json
import random
from collections import Counter
from pathlib import Path

import pandas as pd

from parltopics.build_train import question
from parltopics.cards import render

SEED = 20261018
DEFINITIONS = {
    "descriptor": 'Federal parliamentary affairs that the Parliamentary Services index with the keyword "{}".',
    "tg": 'Affairs of the cantonal parliament of Thurgau filed under "{}".',
}


def card_text(name: str, kind: str) -> str:
    return render({"name": name, "definition": DEFINITIONS[kind].format(name), "include": [name]}, compact=True)


def split_names(value) -> list[str]:
    return [x.strip() for x in str(value).split("|") if x.strip()] if isinstance(value, str) else []


def pairs_descriptor(labels: Path, exclude: set, n_affairs: int, top: int) -> list[tuple[int, list[str]]]:
    kw = pd.read_csv(labels / "che_affairs_keywords.csv", usecols=["openparldata_id", "descriptors_de"], dtype=str)
    kw["names"] = kw.descriptors_de.map(split_names)
    freq = Counter(n for names in kw.names for n in names)
    keep = {n for n, _ in freq.most_common(top)}
    kw["names"] = kw.names.map(lambda ns: [n for n in ns if n in keep])
    kw = kw[kw.names.map(len) > 0]
    kw = kw[~kw.openparldata_id.astype(int).isin(exclude)]
    kw = kw.sample(n=min(n_affairs, len(kw)), random_state=SEED)
    return [(int(a), ns) for a, ns in zip(kw.openparldata_id, kw.names)]


def pairs_tg(labels: Path, exclude: set) -> list[tuple[int, list[str]]]:
    kw = pd.read_csv(labels / "cantonal_affairs_keywords.csv", usecols=["openparldata_id", "body_key", "begin_date", "keywords"], dtype=str)
    kw = kw[(kw.body_key == "TG") & (kw.begin_date.str[:4] < "2024")]
    kw["names"] = kw.keywords.map(split_names)
    kw = kw[(kw.names.map(len) > 0) & ~kw.openparldata_id.astype(int).isin(exclude)]
    return [(int(a), ns) for a, ns in zip(kw.openparldata_id, kw.names)]


def main() -> None:
    ap = argparse.ArgumentParser(description="Add training records for extra topic sets to an existing Kev training file.")
    ap.add_argument("--kind", choices=sorted(DEFINITIONS), required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--base", type=Path, required=True, help="existing training file to extend")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-affairs", type=int, default=3000)
    ap.add_argument("--top", type=int, default=400, help="most frequent descriptors kept as topics")
    ap.add_argument("--n-pos", type=int, default=2)
    ap.add_argument("--n-neg", type=int, default=3)
    ap.add_argument("--max-chars", type=int, default=3500)
    args = ap.parse_args()
    rng = random.Random(SEED)
    exclude = set()
    for s in ("dev_sample", "test_sample", "curia_dev_sample", "curia_test_sample", "sg_dev_sample", "sg_test_sample"):
        path = args.data / f"{s}.parquet"
        if path.exists():
            exclude |= set(pd.read_parquet(path, columns=["affair_id"]).affair_id.astype(int))
    pairs = pairs_descriptor(args.labels, exclude, args.n_affairs, args.top) if args.kind == "descriptor" else pairs_tg(args.labels, exclude)
    text = pd.read_parquet(args.data / "affair_text.parquet", columns=["affair_id", "text"]).set_index("affair_id")
    pool = sorted({n for _, ns in pairs for n in ns})
    extra = []
    for aid, names in pairs:
        if aid not in text.index or not str(text.at[aid, "text"]).strip():
            continue
        pos = rng.sample(names, min(args.n_pos, len(names)))
        negs = rng.sample([n for n in pool if n not in names], min(args.n_neg, len(pool) - len(names)))
        qs = [question(card_text(n, args.kind), True) for n in pos] + [question(card_text(n, args.kind), False) for n in negs]
        rng.shuffle(qs)
        extra.append({"state": text.at[aid, "text"][:args.max_chars], "questions": {f"q{i}": q for i, q in enumerate(qs)},
                      "_meta": {"affair_id": aid, "source": args.kind}})
    base = [json.loads(line) for line in args.base.open(encoding="utf-8")]
    lines = base + extra
    rng.shuffle(lines)
    with args.out.open("w", encoding="utf-8") as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(base)} base records + {len(extra)} {args.kind} records ({len(pool)} topics) = {len(lines)}")


if __name__ == "__main__":
    main()
