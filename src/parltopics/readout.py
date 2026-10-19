import argparse
import asyncio
import math
import time
from pathlib import Path

import httpx
import pandas as pd

from parltopics.cards import load, render

SYSTEM = (
    "You classify Swiss parliamentary affairs by topic. You read the topic definition and the affair, "
    "then answer with a single letter. You judge only what the affair is about, never the political position it takes."
)

QUESTION = (
    "Is this affair about the topic defined above?\n"
    "A) yes\n"
    "B) no\n"
    "Answer with A or B."
)


def build_messages(card_text: str, affair_text: str) -> list[dict]:
    user = f"{card_text}\n\nAffair:\n{affair_text}\n\n{QUESTION}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def option_logprob(top: list[dict], letter: str) -> float | None:
    vals = [t["logprob"] for t in top if t["token"].strip() == letter]
    if not vals:
        return None
    m = max(vals)
    return m + math.log(sum(math.exp(v - m) for v in vals))


def parse(choice: dict) -> dict:
    top = choice["logprobs"]["content"][0]["top_logprobs"]
    floor = min(t["logprob"] for t in top) - 1.0
    a, b = option_logprob(top, "A"), option_logprob(top, "B")
    return {
        "lp_yes": a if a is not None else floor,
        "lp_no": b if b is not None else floor,
        "yes_missing": a is None,
        "no_missing": b is None,
        "answer": choice["message"]["content"],
    }


async def score_one(client, sem, url, headers, model, row, card_text, max_chars, retries=5):
    body = {
        "model": model,
        "max_tokens": 1,
        "temperature": 0,
        "logprobs": True,
        "top_logprobs": 20,
        "messages": build_messages(card_text, row["text"][:max_chars]),
    }
    async with sem:
        for attempt in range(retries):
            t0 = time.monotonic()
            try:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError("retry", request=resp.request, response=resp)
                resp.raise_for_status()
                data = resp.json()
                out = parse(data["choices"][0])
                out.update(affair_id=row["affair_id"], prompt_tokens=data["usage"]["prompt_tokens"],
                           latency=time.monotonic() - t0, error=None)
                out["score"] = out["lp_yes"] - out["lp_no"]
                return out
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                if attempt == retries - 1:
                    return {"affair_id": row["affair_id"], "score": None, "error": repr(exc)[:200]}
                await asyncio.sleep(2 ** attempt)


async def run(df, card_text, base_url, model, headers, concurrency, max_chars):
    sem = asyncio.Semaphore(concurrency)
    url = f"{base_url}/chat/completions"
    async with httpx.AsyncClient(timeout=180) as client:
        tasks = [score_one(client, sem, url, headers, model, row, card_text, max_chars)
                 for row in df.to_dict("records")]
        results = []
        for i, fut in enumerate(asyncio.as_completed(tasks), 1):
            results.append(await fut)
            if i % 200 == 0:
                print(f"{i}/{len(tasks)}", flush=True)
    return pd.DataFrame(results)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score affairs against a topic card with a yes/no probability readout.")
    ap.add_argument("--input", type=Path, required=True, help="parquet with affair_id and text")
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="apertus-v1-5-8b")
    ap.add_argument("--base-url", default="https://gateway.keera.ch/api/v1")
    ap.add_argument("--auth-header", type=Path, default=Path.home() / ".config/keera/auth_header")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--max-chars", type=int, default=3500)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    card = load(args.card)
    df = pd.read_parquet(args.input, columns=["affair_id", "text"])
    if args.limit:
        df = df.head(args.limit)
    headers = {}
    if args.auth_header and args.auth_header.exists():
        name, value = args.auth_header.read_text().strip().split(": ", 1)
        headers[name] = value
    t0 = time.monotonic()
    res = asyncio.run(run(df, render(card), args.base_url, args.model, headers, args.concurrency, args.max_chars))
    res["model"] = args.model
    res["card_hash"] = card["hash"]
    res["max_chars"] = args.max_chars
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_parquet(args.out, index=False)
    ok = res["score"].notna()
    print(f"{ok.sum()}/{len(res)} scored in {time.monotonic() - t0:.0f}s; errors: {(~ok).sum()}")


if __name__ == "__main__":
    main()
