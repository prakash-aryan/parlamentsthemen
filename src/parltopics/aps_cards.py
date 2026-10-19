import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yaml

from parltopics.cards import draft


def jobs(xlsx: Path) -> list[tuple[str, str]]:
    t = pd.read_excel(xlsx, "Topics", dtype=str)
    out = []
    for (code, chap_de, chap_fr, dom_de), _ in t.assign(chap_code=t.code.str.rsplit(".", n=1).str[0]).groupby(
            ["chap_code", "chapter_de", "chapter_fr", "domain_de"], sort=False):
        topics = "; ".join(t[t.chapter_de == chap_de].topic_de)
        out.append((f"aps_{code.replace('.', '_')}",
                    f'The chapter "{chap_de}" ("{chap_fr}") of the domain "{dom_de}" in the Année Politique Suisse classification of '
                    f"Swiss politics. It contains these topics: {topics}. Cover what parliamentary affairs in this chapter are typically about."))
    for r in t.itertuples():
        out.append((f"aps_{r.code.replace('.', '_')}",
                    f'The topic "{r.topic_de}" ("{r.topic_fr}") in the chapter "{r.chapter_de}" of the domain "{r.domain_de}" in the '
                    f"Année Politique Suisse classification of Swiss politics. Cover what parliamentary affairs on this topic are typically about, "
                    f"and what belongs to neighbouring topics of the same chapter instead."))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Draft topic cards for the APS chapters and topics with Apertus.")
    ap.add_argument("--xlsx", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base-url", default="https://gateway.keera.ch/api/v1")
    ap.add_argument("--model", default="apertus-v1-5-70b")
    ap.add_argument("--auth-header", type=Path, default=Path.home() / ".config/keera/auth_header")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    todo = [(cid, d) for cid, d in jobs(args.xlsx) if not (args.out / f"{cid}.yaml").exists()]
    print(f"{len(todo)} cards to draft", flush=True)

    def one(cid: str, description: str) -> str:
        card = {"id": cid, "version": 1, "source_description": description}
        card.update(draft(description, args.base_url, args.model, args.auth_header))
        (args.out / f"{cid}.yaml").write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=100))
        return cid

    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(one, cid, d): cid for cid, d in todo}
        for f in as_completed(futures):
            try:
                print(f"{f.result()} ok", flush=True)
            except Exception as e:
                print(f"{futures[f]} FAILED {type(e).__name__}", flush=True)
    print("APS_CARDS_DONE", flush=True)


if __name__ == "__main__":
    main()
