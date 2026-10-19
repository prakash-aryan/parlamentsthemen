import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge_batch import J, MAXC, MODELS, aps_prompt, cards_from, client, scheme_prompt  # noqa: E402
from judge_score import CURIA_TO_APS, judge, parse, prf, decided_topics  # noqa: E402

REPO = Path("/home/merabro/hackapertus-liebefeld")
OUT = J / "batch/results_opus_extended.jsonl"
TASKS = ("sg", "curia", "aps")


def prompts() -> dict[str, str]:
    return {"sg": scheme_prompt("subject areas of the cantonal law collection of St. Gallen", cards_from(REPO / "cards/sg", lambda s: s.split("_")[1])),
            "curia": scheme_prompt("Curia Vista subject areas of the Swiss Parliamentary Services", cards_from(REPO / "cards/curia", lambda s: s.split("_")[1])),
            "aps": aps_prompt()}


def samples() -> dict[str, pd.DataFrame]:
    curia = pd.read_parquet(J / "curia_test_sample.parquet")
    return {"sg": pd.read_parquet(J / "data/sg_test_sample.parquet"), "curia": curia, "aps": curia}


def texts(ids: list[int]) -> dict[int, str]:
    import duckdb
    t = duckdb.sql(f"select affair_id, text from '{REPO}/data/affair_text.parquet' where affair_id in ({','.join(map(str, ids))})").df()
    return dict(zip(t.affair_id, t.text))


def ask(c, system: str, max_tokens: int, cid: str, text: str) -> dict:
    try:
        r = c.messages.create(model=MODELS["opus"], max_tokens=max_tokens, system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                              messages=[{"role": "user", "content": f"Affair:\n{str(text)[:MAXC]}"}])
        return {"custom_id": cid, "type": "succeeded", "text": "".join(b.text for b in r.content if b.type == "text"),
                "usage": {"input": r.usage.input_tokens, "cache_read": r.usage.cache_read_input_tokens or 0, "output": r.usage.output_tokens}}
    except Exception as e:
        return {"custom_id": cid, "type": "errored", "text": None, "error": str(e)[:200]}


def run() -> None:
    have = set(judge("opus"))
    if OUT.exists():
        have |= {json.loads(l)["custom_id"] for l in OUT.open() if json.loads(l)["type"] == "succeeded"}
    sys_prompts, c, todo = prompts(), client(), []
    for task, df in samples().items():
        ids = [int(a) for a in df.affair_id if f"{task}-{int(a)}" not in have]
        tx = texts(ids)
        todo += [(task, f"{task}-{a}", tx[a]) for a in ids if a in tx]
    print(len(todo), "requests", pd.Series([t for t, *_ in todo]).value_counts().to_dict(), flush=True)
    with ThreadPoolExecutor(int(os.environ.get("JUDGE_WORKERS", "8"))) as ex, OUT.open("a") as f:
        futures = [ex.submit(ask, c, sys_prompts[t], 700 if t == "aps" else 400, cid, text) for t, cid, text in todo]
        for i, fu in enumerate(futures, 1):
            f.write(json.dumps(fu.result(), ensure_ascii=False) + "\n")
            f.flush()
            if i % 100 == 0:
                print(i, "done", flush=True)


def answers() -> dict[str, dict | None]:
    out = judge("opus")
    if OUT.exists():
        for line in OUT.open():
            r = json.loads(line)
            if r["type"] == "succeeded":
                out[r["custom_id"]] = parse(r["text"])
    return out


def bootstrap(truth, a, b, topics, n=1000, seed=20261018) -> tuple[float, float]:
    rng, ids = np.random.default_rng(seed), list(truth)
    diffs = []
    for _ in range(n):
        s = rng.choice(ids, len(ids))
        t = {i: truth[x] for i, x in enumerate(s)}
        diffs.append(prf(t, {i: a[x] for i, x in enumerate(s)}, topics)["micro_F1"] - prf(t, {i: b[x] for i, x in enumerate(s)}, topics)["micro_F1"])
    return round(float(np.percentile(diffs, 2.5)), 3), round(float(np.percentile(diffs, 97.5)), 3)


def score() -> None:
    op, rows = answers(), []
    sm = samples()
    for task in ("sg", "curia"):
        test = sm[task]
        truth = {int(a): {str(x) for x in v} for a, v in zip(test.affair_id, test.topic_ids)}
        truth = {a: v for a, v in truth.items() if op.get(f"{task}-{a}") is not None}
        pred = {a: {str(x) for x in op[f"{task}-{a}"].get("topics", [])} for a in truth}
        topics = sorted({t for v in truth.values() for t in v} | {t for v in pred.values() for t in v})
        dev = pd.read_parquet(J / ("data/sg_dev_sample.parquet" if task == "sg" else "curia_dev_sample.parquet"))
        g = decided_topics(f"G_desc_dev_{task}_", f"G_desc_test_{task}_", dev, test[test.affair_id.isin(truth)], lambda r: [str(x) for x in r.topic_ids], topics)
        lo, hi = bootstrap(truth, g, pred, topics)
        rows += [{"set": task, "system": "Claude Opus 5.5", "n": len(truth), **prf(truth, pred, topics)},
                 {"set": task, "system": "Apertus-ParlTopics-8B", "n": len(truth), **prf(truth, g, topics), "diff_CI95": f"{lo} to {hi}"}]
    test = sm["aps"]
    truth = {int(a): {c for t in v for c in CURIA_TO_APS.get(str(t), [])} for a, v in zip(test.affair_id, test.topic_ids)}
    truth = {a: v for a, v in truth.items() if op.get(f"aps-{a}") is not None}
    chapters = sorted({c for v in CURIA_TO_APS.values() for c in v})
    pred = {a: {str(x) for x in op[f"aps-{a}"].get("chapters", [])} for a in truth}
    dev = pd.read_parquet(J / "curia_dev_sample.parquet")
    lab = lambda r: [c.replace(".", "_") for t in r.topic_ids for c in CURIA_TO_APS.get(str(t), [])]
    g = decided_topics("G_desc_dev_aps_", "G_desc_test_aps_", dev, test[test.affair_id.isin(truth)], lab, [c.replace(".", "_") for c in chapters])
    g = {a: {c.replace("_", ".") for c in v} for a, v in g.items()}
    lo, hi = bootstrap(truth, g, pred, chapters)
    rows += [{"set": "aps chapters vs Curia mapping", "system": "Claude Opus 5.5", "n": len(truth), **prf(truth, pred, chapters)},
             {"set": "aps chapters vs Curia mapping", "system": "Apertus-ParlTopics-8B", "n": len(truth), **prf(truth, g, chapters), "diff_CI95": f"{lo} to {hi}"}]
    df = pd.DataFrame(rows)
    df.to_csv(REPO / "docs/results/judge/judge_scores_full_test_sets.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    {"run": run, "score": score}[sys.argv[1]]()
