import argparse
import asyncio
import math
import time
from pathlib import Path

import httpx
import pandas as pd

from parltopics.cards import load, render


def request(card_text: str, affair_text: str, model: str | None) -> dict:
    body = {
        "state": affair_text,
        "questions": {
            "topic": {
                "type": "noul",
                "instructions": f"{card_text}\n\nIs this parliamentary affair about the topic defined above?",
                "criteria": {"true": "The affair is about this topic.", "false": "The affair is not about this topic."},
            }
        },
    }
    if model:
        body["model"] = model
    return body


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


async def score_one(client, sem, url, row, card_text, model, max_chars, retries=4):
    async with sem:
        for attempt in range(retries):
            t0 = time.monotonic()
            try:
                resp = await client.post(url, json=request(card_text, row["text"][:max_chars], model))
                resp.raise_for_status()
                p = float(resp.json()["answers"]["topic"]["noul"])
                return {"affair_id": row["affair_id"], "p_yes": p, "score": logit(p),
                        "latency": time.monotonic() - t0, "error": None}
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                if attempt == retries - 1:
                    return {"affair_id": row["affair_id"], "score": None, "error": repr(exc)[:200]}
                await asyncio.sleep(2 ** attempt)


async def run(df, card_text, base_url, model, concurrency, max_chars):
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=300) as client:
        tasks = [score_one(client, sem, f"{base_url}/v1/systemone", row, card_text, model, max_chars)
                 for row in df.to_dict("records")]
        out = []
        for i, fut in enumerate(asyncio.as_completed(tasks), 1):
            out.append(await fut)
            if i % 200 == 0:
                print(f"{i}/{len(tasks)}", flush=True)
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score affairs with a System One compatible decision model (Kev, decisio).")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--model")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-chars", type=int, default=3500)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--compact", action="store_true", help="render the card in the compact form used for training")
    args = ap.parse_args()
    card = load(args.card)
    df = pd.read_parquet(args.input, columns=["affair_id", "text"])
    if args.limit:
        df = df.head(args.limit)
    t0 = time.monotonic()
    res = asyncio.run(run(df, render(card, args.compact), args.base_url, args.model, args.concurrency, args.max_chars))
    res["model"] = args.name
    res["card_hash"] = card["hash"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_parquet(args.out, index=False)
    ok = res["score"].notna()
    print(f"{ok.sum()}/{len(res)} scored in {time.monotonic() - t0:.0f}s; errors: {(~ok).sum()}")


if __name__ == "__main__":
    main()
