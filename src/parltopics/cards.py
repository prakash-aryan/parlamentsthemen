import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx
import yaml

DRAFT_PROMPT = """You help define topics for classifying Swiss parliamentary affairs (motions, postulates, interpellations, questions) from federal, cantonal and city parliaments.

Write a topic card for the topic described below. Return only JSON with these keys:
"name": short topic name in English,
"definition": two or three sentences that say what the topic covers,
"include": list of 6 to 10 short phrases naming what belongs to the topic,
"exclude": list of 4 to 6 short phrases naming related things that do not belong,
"terms": object with keys "de", "fr", "it", "rm", each a list of 8 to 15 words or short phrases that affairs on this topic typically use in that language.

Topic description:
{description}"""


def card_hash(card: dict) -> str:
    body = {k: card[k] for k in ("name", "definition", "include", "exclude", "terms")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def load(path: Path) -> dict:
    card = yaml.safe_load(path.read_text())
    card["hash"] = card_hash(card)
    return card


def render(card: dict, compact: bool = False) -> str:
    lines = [f"Topic: {card['name']}", f"Definition: {card['definition']}"]
    if compact:
        return "\n".join(lines + ["Belongs to the topic: " + "; ".join(card["include"])])
    lines.append("Belongs to the topic: " + "; ".join(card["include"]))
    lines.append("Does not belong to the topic: " + "; ".join(card["exclude"]))
    for lang in ("de", "fr", "it", "rm"):
        if card["terms"].get(lang):
            lines.append(f"Typical terms ({lang}): " + ", ".join(card["terms"][lang]))
    return "\n".join(lines)


def draft(description: str, base_url: str, model: str, auth_header: Path) -> dict:
    name, value = auth_header.read_text().strip().split(": ", 1)
    for attempt in range(5):
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={name: value},
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": 1500,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": DRAFT_PROMPT.format(description=description)}],
            },
            timeout=300,
        )
        if resp.status_code < 500 or attempt == 4:
            break
        time.sleep(10 * (attempt + 1))
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def main() -> None:
    ap = argparse.ArgumentParser(description="Draft a topic card with Apertus from a short description.")
    ap.add_argument("--description", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base-url", default="https://gateway.keera.ch/api/v1")
    ap.add_argument("--model", default="apertus-v1-5-70b")
    ap.add_argument("--auth-header", type=Path, default=Path.home() / ".config/keera/auth_header")
    args = ap.parse_args()
    card = {"id": args.id, "version": 1, "source_description": args.description}
    card.update(draft(args.description, args.base_url, args.model, args.auth_header))
    args.out.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=100))
    print(args.out.read_text())


if __name__ == "__main__":
    main()
