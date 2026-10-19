import argparse
import asyncio
import json
import re
from pathlib import Path

import httpx
import pandas as pd

from parltopics.cards import load, render

PROMPT = """{card}

Affair:
{text}

The affair above was classified as belonging to the topic. Return only JSON with two keys:
"quote": one sentence or phrase copied exactly, character for character, from the affair that best shows the topic,
"reason": one short sentence in the language of the affair explaining why the affair belongs to the topic."""


def normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def locate(quote: str, text: str) -> tuple[int, int] | None:
    q = normalise(quote).strip(" \"'«»„“")
    if len(q) < 12:
        return None
    flat = normalise(text)
    i = flat.find(q)
    if i < 0:
        i = flat.lower().find(q.lower())
    return (i, i + len(q)) if i >= 0 else None


def nearest_sentence(quote: str, text: str) -> tuple[int, int] | None:
    flat = normalise(text)
    words = set(re.findall(r"\w+", quote.lower()))
    if not words:
        return None
    best, best_span = 0.0, None
    for m in re.finditer(r"[^.!?;]{20,400}[.!?;]?", flat):
        sent = set(re.findall(r"\w+", m.group().lower()))
        overlap = len(words & sent) / len(words)
        if overlap > best:
            best, best_span = overlap, (m.start(), m.end())
    return best_span if best >= 0.5 else None


async def explain_one(client, sem, url, headers, model, row, card_text, max_chars):
    text = row["text"][:max_chars]
    body = {"model": model, "temperature": 0, "max_tokens": 300, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT.format(card=card_text, text=text)}]}
    async with sem:
        for attempt in range(4):
            try:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content[content.index("{"): content.rindex("}") + 1])
                raw = str(data.get("quote", ""))
                span, source = locate(raw, text), "model"
                if span is None:
                    span, source = nearest_sentence(raw, text), "nearest_sentence"
                return {"affair_id": row["affair_id"], "quote": normalise(text)[span[0]:span[1]].strip() if span else None,
                        "quote_start": span[0] if span else None, "quote_end": span[1] if span else None,
                        "quote_verified": span is not None, "quote_source": source if span else None,
                        "reason": data.get("reason"), "error": None}
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                if attempt == 3:
                    return {"affair_id": row["affair_id"], "quote_verified": False, "error": repr(exc)[:200]}
                await asyncio.sleep(2 ** attempt)


async def run(df, card_text, base_url, model, headers, concurrency, max_chars):
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=180) as client:
        tasks = [explain_one(client, sem, f"{base_url}/chat/completions", headers, model, r, card_text, max_chars)
                 for r in df.to_dict("records")]
        return pd.DataFrame(await asyncio.gather(*tasks))


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask Apertus for a verbatim quote and a reason for each positive affair, and verify the quote.")
    ap.add_argument("--input", type=Path, required=True, help="parquet with affair_id and text")
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="apertus-v1-5-8b")
    ap.add_argument("--base-url", default="https://gateway.keera.ch/api/v1")
    ap.add_argument("--auth-header", type=Path, default=Path.home() / ".config/keera/auth_header")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--max-chars", type=int, default=3500)
    args = ap.parse_args()
    name, value = args.auth_header.read_text().strip().split(": ", 1)
    df = pd.read_parquet(args.input, columns=["affair_id", "text"])
    res = asyncio.run(run(df, render(load(args.card)), args.base_url, args.model, {name: value}, args.concurrency, args.max_chars))
    res.to_parquet(args.out, index=False)
    exact = (res["quote_source"] == "model").mean()
    print(f"{len(res)} affairs; quote found in text: {res['quote_verified'].mean():.1%} (exact model quote {exact:.1%})")


if __name__ == "__main__":
    main()
