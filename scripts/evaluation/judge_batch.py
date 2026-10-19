import os
import argparse
import json
import sys
from pathlib import Path

import anthropic
import duckdb
import pandas as pd

sys.path.insert(0, "/home/merabro/hackapertus-liebefeld/src")
from parltopics.cards import load, render

J = Path(os.environ.get("JUDGE_DIR", "runs/judge"))
REPO = Path("/home/merabro/hackapertus-liebefeld")
OUT = J / "batch"
SEED = 20261018
MAXC = 6000
MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}

SINGLE = """You classify Swiss parliamentary affairs by topic. Read the topic definition, then the affair, and decide whether the affair is about the topic. Follow the definition, including what it excludes. Reply with JSON only, in this form:
{"answer": "yes" or "no", "passage": "a short quote from the affair that decides it, or an empty string", "reason": "one sentence"}

Topic definition:
"""

SCHEME = """You classify Swiss parliamentary affairs into the topics of one classification scheme: {scheme}. Read the topic definitions, then the affair, and list every topic the affair is about. A topic that the affair mentions only in passing does not count. Reply with JSON only, in this form:
{{"topics": ["<topic id>", ...], "reason": "one sentence"}}

Topic definitions:
"""

APS = """You classify Swiss parliamentary affairs into the two-level scheme of Annee Politique Suisse (APS): 22 chapters, each with its topics. Read the chapter definitions and the topic list, then the affair. List every chapter the affair is about, and within those chapters every topic the affair is about. A chapter or topic that the affair mentions only in passing does not count. Reply with JSON only, in this form:
{"chapters": ["<chapter code, e.g. 6.1>", ...], "topics": ["<topic code, e.g. 6.1.9>", ...], "reason": "one sentence"}

"""


def scheme_prompt(name: str, cards: dict[str, dict]) -> str:
    return SCHEME.format(scheme=name) + "\n\n".join(f"Topic id {cid}:\n{render(c)}" for cid, c in cards.items())


def aps_prompt() -> str:
    t = pd.read_excel(REPO / "data/labels/aps_topics.xlsx", "Topics", dtype=str)
    t["chap"] = t.code.str.rsplit(".", n=1).str[0]
    parts = []
    for chap, g in t.groupby("chap", sort=False):
        card = load(REPO / f"cards/aps/aps_{chap.replace('.', '_')}.yaml")
        topics = "\n".join(f"  {r.code}: {r.topic_de} / {r.topic_fr}" for r in g.itertuples())
        parts.append(f"Chapter {chap}: {g.chapter_de.iloc[0]} / {g.chapter_fr.iloc[0]}\n{render(card, compact=True)}\nTopics:\n{topics}")
    return APS + "\n\n".join(parts)


def cards_from(folder: Path, ids_from_stem=lambda s: s) -> dict[str, dict]:
    return {ids_from_stem(p.stem): load(p) for p in sorted(folder.glob("*.yaml"))}


def corpus(where: str, n: int, seed_offset: int) -> pd.DataFrame:
    q = f"select affair_id, text, level, body_key, lang from '{REPO}/data/affair_text.parquet' where text is not null and length(trim(text)) > 0 and {where}"
    t = duckdb.sql(q).df()
    return t.sample(n=min(n, len(t)), random_state=SEED + seed_offset)


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prompts, rows = {}, []
    curia_cards = cards_from(REPO / "cards/curia", lambda s: s.split("_")[1])
    prompts["curia"] = ("opus", scheme_prompt("Curia Vista subject areas of the Swiss Parliamentary Services", curia_cards), 500)
    sg_cards = cards_from(REPO / "cards/sg", lambda s: s.split("_")[1])
    prompts["sg"] = ("opus", scheme_prompt("subject areas of the cantonal law collection of St. Gallen", sg_cards), 400)
    for kind, title in (("tg", "subject areas of the cantonal parliament of Thurgau"), ("zug", "responsible departments of the city parliament of Zug"),
                        ("descriptor", "keywords of the Swiss Parliamentary Services thesaurus")):
        prompts[kind] = ("opus", scheme_prompt(title, cards_from(J / f"cards/{kind}")), 500)
    prompts["adhoc"] = ("opus", scheme_prompt("ad-hoc topics", cards_from(REPO / "cards/adhoc", lambda s: s.removeprefix("adhoc_"))), 400)
    prompts["aps"] = ("opus", aps_prompt(), 700)
    digit = SINGLE + render(load(REPO / "cards/digitalisation_v2.yaml"))
    for task in ("digit", "dvs", "spot"):
        prompts[task] = ("sonnet", digit, 300)

    def add(task, df, labels=None):
        for i, r in enumerate(df.itertuples()):
            rows.append({"task": task, "affair_id": int(r.affair_id), "text": str(r.text)[:MAXC],
                         "labels": json.dumps(labels[i] if labels is not None else None, ensure_ascii=False)})

    ct = pd.read_parquet(J / "curia_test_sample.parquet")
    c = ct.sample(300, random_state=SEED)
    add("curia", c, [[str(x) for x in v] for v in c.topic_ids])
    s = pd.read_parquet(J / "data/sg_test_sample.parquet").sample(200, random_state=SEED)
    add("sg", s, [[str(x) for x in v] for v in s.topic_ids])
    for kind, n in (("tg", 200), ("zug", 100), ("descriptor", 200)):
        d = pd.read_parquet(J / f"data/{kind}_test_sample.parquet")
        d = d.sample(min(n, len(d)), random_state=SEED)
        names = {v: k for k, v in json.loads((J / f"cards/{kind}/labels.json").read_text()).items()}
        add(kind, d, [[names[x] for x in v if x in names] for v in d.labels])
    t = pd.read_parquet(J / "test_sample.parquet").sample(300, random_state=SEED)
    add("digit", t, [bool(x) for x in t.label])
    add("aps", ct.sample(500, random_state=SEED + 1), [[str(x) for x in v] for v in ct.sample(500, random_state=SEED + 1).topic_ids])
    add("aps", corpus("year >= 2024 and level = 'canton'", 500, 2))
    add("aps", corpus("year >= 2024 and level in ('city', 'municipality')", 200, 3))
    add("adhoc", corpus("year >= 2024", 400, 4))
    dvs = pd.read_csv(J.parent / "opd_check/dvs_digitalisierung.csv")
    add("dvs", duckdb.sql(f"select affair_id, text from '{REPO}/data/affair_text.parquet' where affair_id in ({','.join(map(str, dvs.openparldata_id))})").df())
    add("spot", corpus("true", 1000, 5))
    man = pd.DataFrame(rows)
    man.drop(columns=["text"]).to_parquet(OUT / "manifest.parquet", index=False)
    reqs = {"sonnet": [], "opus": []}
    for r in rows:
        short, system, mt = prompts[r["task"]]
        reqs[short].append({"custom_id": f"{r['task']}-{r['affair_id']}", "params": {
            "model": MODELS[short], "max_tokens": mt,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "messages": [{"role": "user", "content": f"Affair:\n{r['text']}"}]}})
    for short, rq in reqs.items():
        seen, uniq = set(), []
        for q in rq:
            if q["custom_id"] not in seen:
                seen.add(q["custom_id"]); uniq.append(q)
        (OUT / f"requests_{short}.jsonl").write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in uniq))
        print(short, len(uniq), "requests")
    print(man.groupby("task").size().to_string())


def client() -> anthropic.Anthropic:
    home = Path.home() / ".config/anthropic"
    return anthropic.Anthropic(api_key=(home / "project_api_key").read_text().strip(),
                               default_headers={"anthropic-workspace-id": (home / "project_workspace_id").read_text().strip()})


def submit() -> None:
    c, ids = client(), {}
    for short in MODELS:
        reqs = [json.loads(l) for l in (OUT / f"requests_{short}.jsonl").read_text().splitlines()]
        b = c.messages.batches.create(requests=reqs)
        ids[short] = b.id
        print(short, b.id, b.processing_status, len(reqs))
    (OUT / "batch_ids.json").write_text(json.dumps(ids))


def status() -> bool:
    c, done = client(), True
    for short, bid in json.loads((OUT / "batch_ids.json").read_text()).items():
        b = c.messages.batches.retrieve(bid)
        print(short, b.processing_status, b.request_counts)
        done &= b.processing_status == "ended"
    return done


def fetch() -> None:
    c = client()
    for short, bid in json.loads((OUT / "batch_ids.json").read_text()).items():
        with (OUT / f"results_{short}.jsonl").open("w") as f:
            for e in c.messages.batches.results(bid):
                row = {"custom_id": e.custom_id, "type": e.result.type}
                if e.result.type == "succeeded":
                    m = e.result.message
                    row.update({"text": "".join(b.text for b in m.content if b.type == "text"), "input": m.usage.input_tokens,
                                "output": m.usage.output_tokens, "cache_read": m.usage.cache_read_input_tokens or 0,
                                "cache_write": m.usage.cache_creation_input_tokens or 0})
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(short, "fetched")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "submit", "status", "fetch"])
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "submit":
        submit()
    elif a.cmd == "status":
        sys.exit(0 if status() else 1)
    else:
        fetch()
