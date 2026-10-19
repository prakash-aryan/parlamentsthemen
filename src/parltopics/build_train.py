import argparse
import json
import random
from pathlib import Path

import pandas as pd

from parltopics.cards import load, render
from parltopics.systemone import request

HELD_OUT = ("66", "55", "2831", "2446", "2811")
SEED = 20261018


def question(card_text: str, label: bool) -> dict:
    q = request(card_text, "", None)["questions"]["topic"]
    q["label"] = bool(label)
    return q


def build(data: Path, cards: Path, digit_card: Path, n_federal: int, neg_ratio: float, neg_areas: int, max_chars: int,
          compact: bool = False, skip_digit: bool = False):
    rng = random.Random(SEED)
    text = pd.read_parquet(data / "affair_text.parquet", columns=["affair_id", "text", "year"]).set_index("affair_id")
    exclude = set(pd.read_parquet(data / "dev_sample.parquet", columns=["affair_id"])["affair_id"])
    exclude |= set(pd.read_parquet(data / "test_sample.parquet", columns=["affair_id"])["affair_id"])
    curia = pd.read_parquet(data / "curia.parquet")
    digit = pd.read_parquet(data / "digit.parquet", columns=["affair_id", "label", "split"])
    digit = digit[(digit.split == "dev") & ~digit.affair_id.isin(exclude)]
    digit_label = dict(zip(digit.affair_id, digit.label))
    area_cards = {p.stem.split("_", 1)[1]: render(load(p), compact) for p in sorted(cards.glob("curia_*.yaml"))}
    train_areas = [a for a in area_cards if a not in HELD_OUT]
    digit_text = render(load(digit_card), compact)
    if skip_digit:
        digit_label = {}

    records = []
    fed = curia[(curia.split == "train") & ~curia.affair_id.isin(exclude) & curia.affair_id.isin(text.index)]
    fed = fed.sample(n=min(n_federal, len(fed)), random_state=SEED)
    for row in fed.itertuples():
        pos = [a for a in row.topic_ids if a in area_cards and a not in HELD_OUT][:3]
        if not pos:
            continue
        negs = rng.sample([a for a in train_areas if a not in row.topic_ids], neg_areas)
        qs = [question(area_cards[a], True) for a in pos] + [question(area_cards[a], False) for a in negs]
        if row.affair_id in digit_label:
            qs.append(question(digit_text, digit_label[row.affair_id]))
        rng.shuffle(qs)
        records.append((row.affair_id, qs))

    used = {aid for aid, _ in records}
    pos_ids = [a for a, l in digit_label.items() if l and a not in used and a in text.index]
    neg_ids = [a for a, l in digit_label.items() if not l and a not in used and a in text.index]
    neg_ids = rng.sample(neg_ids, min(len(neg_ids), int(len(pos_ids) * neg_ratio)))
    for aid in pos_ids + neg_ids:
        records.append((aid, [question(digit_text, digit_label[aid])]))
    rng.shuffle(records)

    lines = []
    for aid, qs in records:
        lines.append({"state": text.at[aid, "text"][:max_chars],
                      "questions": {f"q{i}": q for i, q in enumerate(qs)},
                      "_meta": {"affair_id": int(aid)}})
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Kev-format training records from pre-2024 labels.")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--cards", type=Path, required=True)
    ap.add_argument("--digit-card", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-federal", type=int, default=4000)
    ap.add_argument("--neg-ratio", type=float, default=1.0)
    ap.add_argument("--neg-areas", type=int, default=3)
    ap.add_argument("--max-chars", type=int, default=3500)
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--skip-digit", action="store_true", help="leave digitalisation out of training entirely")
    args = ap.parse_args()
    lines = build(args.data, args.cards, args.digit_card, args.n_federal, args.neg_ratio, args.neg_areas, args.max_chars,
                  args.compact, args.skip_digit)
    with args.out.open("w", encoding="utf-8") as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_q = sum(len(r["questions"]) for r in lines)
    n_yes = sum(q["label"] for r in lines for q in r["questions"].values())
    print(f"{len(lines)} records, {n_q} questions, {n_yes} yes; held-out areas: {', '.join(HELD_OUT)}")


if __name__ == "__main__":
    main()
