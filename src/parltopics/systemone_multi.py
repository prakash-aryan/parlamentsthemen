import argparse
import asyncio
import math
from pathlib import Path

import httpx
import pandas as pd

from parltopics.cards import load, render


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def build_request(state: str, cards: dict, compact: bool) -> dict:
    return {"state": state, "questions": {
        code: {"type": "noul",
               "instructions": f"{render(card, compact)}\n\nIs this parliamentary affair about the topic defined above?",
               "criteria": {"true": "The affair is about this topic.", "false": "The affair is not about this topic."}}
        for code, card in cards.items()}}


async def score_one(client, sem, url, row, cards, compact, max_chars, retries=4):
    async with sem:
        for attempt in range(retries):
            try:
                resp = await client.post(url, json=build_request(row["text"][:max_chars], cards, compact))
                resp.raise_for_status()
                answers = resp.json()["answers"]
                return [{"affair_id": row["affair_id"], "topic": code, "score": logit(float(answers[code]["noul"]))}
                        for code in cards]
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                if attempt == retries - 1:
                    return [{"affair_id": row["affair_id"], "topic": code, "score": None, "error": repr(exc)[:200]} for code in cards]
                await asyncio.sleep(2 ** attempt)


async def run(df, cards, base_url, compact, concurrency, max_chars):
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=600) as client:
        tasks = [score_one(client, sem, f"{base_url}/v1/systemone", r, cards, compact, max_chars) for r in df.to_dict("records")]
        rows = []
        for i, fut in enumerate(asyncio.as_completed(tasks), 1):
            rows.extend(await fut)
            if i % 200 == 0:
                print(f"{i}/{len(tasks)}", flush=True)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask a System One server all topic questions for each affair in one request.")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--cards", type=Path, nargs="+", required=True, help="card files; the card id is the topic code")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--prefix", required=True, help="output files are <prefix>_<split>_<topic>.parquet")
    ap.add_argument("--split", required=True)
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-chars", type=int, default=3500)
    args = ap.parse_args()
    cards = {load(p)["id"]: load(p) for p in args.cards}
    df = pd.read_parquet(args.input, columns=["affair_id", "text"])
    res = asyncio.run(run(df, cards, args.base_url, args.compact, args.concurrency, args.max_chars))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for code, part in res.groupby("topic"):
        part.drop(columns=["topic"]).to_parquet(args.out_dir / f"{args.prefix}_{args.split}_{code}.parquet", index=False)
    print(f"{len(df)} affairs x {len(cards)} topics; missing scores: {int(res['score'].isna().sum())}")


if __name__ == "__main__":
    main()
