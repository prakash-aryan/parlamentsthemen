import argparse
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd
from rapidfuzz import process
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[2]
VOCAB = ROOT / "models" / "vocabulary.parquet"
TEXTS = ROOT / "data" / "affair_text.parquet"
WORD = re.compile(r"[^\W\d_]{3,}")
MIN_COUNT = 3
TRUSTED = 20


def build(texts: Path = TEXTS, out: Path | None = VOCAB) -> pd.DataFrame:
    counts: Counter = Counter()
    for col in ("title", "title_de", "title_fr", "title_it"):
        for (value,) in duckdb.sql(f"SELECT {col} FROM read_parquet('{texts}') WHERE {col} IS NOT NULL").fetchall():
            counts.update(w.lower() for w in WORD.findall(value))
    df = pd.DataFrame(((w, n) for w, n in counts.items() if n >= MIN_COUNT), columns=["word", "count"])
    df = df.sort_values("count", ascending=False).reset_index(drop=True)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
    return df


@lru_cache(maxsize=1)
def vocabulary() -> tuple[dict[str, int], dict[tuple[str, int], list[str]]]:
    if VOCAB.exists():
        df = pd.read_parquet(VOCAB)
    elif TEXTS.exists():
        df = build(TEXTS, None)
    else:
        return {}, {}
    freq = dict(zip(df["word"], df["count"].astype(int)))
    buckets: dict[tuple[str, int], list[str]] = defaultdict(list)
    for w in freq:
        buckets[(w[0], len(w))].append(w)
    return freq, dict(buckets)


def best(token: str) -> str | None:
    freq, buckets = vocabulary()
    if not freq:
        return None
    known = freq.get(token, 0)
    if known >= TRUSTED:
        return None
    dist = 1 if len(token) <= 6 else 2
    pool = [w for n in range(len(token) - dist, len(token) + dist + 1) for w in buckets.get((token[0], n), [])]
    found = process.extract(token, pool, scorer=Levenshtein.distance, score_cutoff=dist, limit=None)
    found = [(w, d) for w, d, _ in found if w != token and freq[w] >= TRUSTED and (known == 0 or freq[w] >= 50 * known)]
    if not found:
        return None
    return min(found, key=lambda x: (x[1], -freq[x[0]]))[0]


def recase(original: str, word: str) -> str:
    if original.isupper() and len(original) > 1:
        return word.upper()
    if original[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def suggest(query: str) -> str | None:
    if not query:
        return None
    out, changed, last = [], False, 0
    for m in WORD.finditer(query):
        token = m.group(0)
        fix = best(token.lower()) if len(token) >= 4 else None
        out.append(query[last:m.start()])
        if fix:
            out.append(recase(token, fix))
            changed = True
        else:
            out.append(token)
        last = m.end()
    out.append(query[last:])
    return "".join(out) if changed else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Word frequencies of all affair titles, for spelling suggestions.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--texts", type=Path, default=TEXTS)
    b.add_argument("--out", type=Path, default=VOCAB)
    s = sub.add_parser("suggest")
    s.add_argument("query", nargs="+")
    args = ap.parse_args()
    if args.cmd == "build":
        df = build(args.texts, args.out)
        print(f"{len(df)} words seen at least {MIN_COUNT} times")
    else:
        for q in args.query:
            print(f"{q!r} -> {suggest(q)!r}")


if __name__ == "__main__":
    main()
