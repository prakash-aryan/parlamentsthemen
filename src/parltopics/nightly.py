import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from parltopics.cards import render
from parltopics.db import EMB_MODEL, OVERLAY_DDL, ROOT, calibration_for, card_index, connect, decide_rows, read_env, upsert_topics
from parltopics.outcome import category
from parltopics.prepare import BODY_CHARS, FEDERAL_TEXT_ORDER, SENTINEL
from parltopics.readout import build_messages, parse
from parltopics.systemone_multi import build_request, logit

OPD = "https://api.openparldata.ch/v1"
MAX_CHARS = 3500
TAGS = re.compile(r"<[^>]+>")
ENTITIES = re.compile(r"&[a-zA-Z#0-9]+;")
SPACES = re.compile(r"[\t\n\f\r ]+")
BRACKETED = re.compile(r"^\[.*\]$")
AFFAIR_COLS = ["openparldata_id", "body_key", "body_name", "level", "number", "affair_type", "year", "begin_date", "lang", "title",
               "url_external", "text_hash", "state", "outcome", "title_only"]
SCOPED = {"curia_vista": "CHE", "sg": "SG"}


def clean(s: str | None) -> str | None:
    if s is None:
        return None
    return SPACES.sub(" ", ENTITIES.sub(" ", TAGS.sub(" ", s))).strip(" ")


def title_ok(s: str | None) -> str | None:
    if s is None or s.strip(" ") == "" or BRACKETED.match(s.strip(" ")):
        return None
    return clean(s)


def pick_lang(body_key: str, body_lang: str | None, titles: dict) -> str | None:
    if body_key == "CHE" and titles.get("de"):
        return "de"
    if body_lang in ("de", "fr", "it") and titles.get(body_lang):
        return body_lang
    for lang in ("de", "fr", "it", "rm"):
        if titles.get(lang):
            return lang
    return None


def federal_body(texts: list[dict]) -> str | None:
    parts = []
    for t in texts:
        kind = (t.get("type") or {}).get("de")
        value = (t.get("text") or {}).get("de") if isinstance(t.get("text"), dict) else None
        if kind in FEDERAL_TEXT_ORDER and value is not None:
            parts.append((FEDERAL_TEXT_ORDER[kind], clean(value)))
    joined = "\n\n".join(p for _, p in sorted(parts, key=lambda x: x[0]))
    return joined or None


def document_body(docs: list[dict]) -> str | None:
    usable = [d["text"] for d in docs if d.get("text") is not None and d["text"].strip(" ") not in ("", SENTINEL)]
    if not usable:
        return None
    return clean(max(usable, key=len)[:20000])[:BODY_CHARS]


def bodies(c: httpx.Client) -> dict[str, dict]:
    out, offset = {}, 0
    while True:
        page = c.get(f"{OPD}/bodies/", params={"limit": 500, "offset": offset}).json()
        for b in page["data"]:
            out[b["body_key"]] = {"level": b.get("type"), "lang": (b.get("lang") or "").lower() or None,
                                  "name": (b.get("name") or {}).get("de")}
        if not page["meta"].get("has_more"):
            return out
        offset += 500


def changed_since(c: httpx.Client, since: date, limit: int | None) -> list[dict]:
    out, offset, cutoff = [], 0, since.isoformat()
    while True:
        page = c.get(f"{OPD}/affairs/", params={"sort_by": "-updated_at", "limit": 100, "offset": offset}).json()
        for a in page["data"]:
            if (a.get("updated_at") or "")[:10] < cutoff:
                return out
            if a.get("body_key") != "LIE":
                out.append(a)
                if limit and len(out) >= limit:
                    return out
        if not page["meta"].get("has_more"):
            return out
        offset += 100


def build_affair(c: httpx.Client, a: dict, body_info: dict) -> dict | None:
    titles = {lang: title_ok(v) for lang, v in (a.get("title") or {}).items() if lang in ("de", "fr", "it", "rm")}
    info = body_info.get(a["body_key"], {})
    lang = pick_lang(a["body_key"], info.get("lang"), titles)
    if lang is None:
        return None
    title, body, source = titles[lang], None, "title_only"
    if a["body_key"] == "CHE":
        texts = c.get(f"{OPD}/affairs/{a['id']}/texts", params={"limit": 50}).json().get("data", [])
        fed = federal_body(texts)
        if fed is not None:
            body, source = fed[:BODY_CHARS], "texts"
    if body is None:
        docs = c.get(f"{OPD}/affairs/{a['id']}/docs", params={"limit": 100}).json().get("data", [])
        body = document_body(docs)
        if body is not None:
            source = "docs"
    text = "\n\n".join(x for x in (title, body) if x is not None)
    begin = (a.get("begin_date") or "")[:10] or None
    state = a.get("state_name")
    state = (state.get("de") or state.get("fr") or state.get("it")) if isinstance(state, dict) else state
    kind = a.get("type_harmonized")
    url = a.get("url_external")
    if isinstance(url, dict):
        url = next((url[k] for k in (lang, "de", "fr", "it", "rm", "en") if url.get(k)), None)
    return {"openparldata_id": int(a["id"]), "body_key": a["body_key"], "body_name": info.get("name"), "level": info.get("level"),
            "number": a.get("number"), "affair_type": (kind or {}).get("en") if isinstance(kind, dict) and kind.get("en") else "unknown",
            "year": int(begin[:4]) if begin else None, "begin_date": begin, "lang": lang, "title": title,
            "url_external": url, "text_hash": hashlib.md5(text.encode("utf-8")).hexdigest(), "state": state,
            "outcome": category(state), "title_only": source == "title_only", "text": text, "text_source": source}


def active_topics(con, wanted: list[str] | None) -> dict[str, dict]:
    cards = card_index()
    names = json.loads((ROOT / "cards/topic_names.json").read_text(encoding="utf-8"))
    if wanted:
        codes = wanted
    else:
        stored = {r[0] for r in con.execute("SELECT DISTINCT topic_code FROM affair_topics WHERE run_id = 'parltopics8b_corpus'").fetchall()}
        codes = sorted(stored | {c for c, n in names.items() if n["scheme"] in SCOPED and not n.get("parent")})
    return {c: {"card": cards[c], "scheme": names[c]["scheme"], "name": names[c]["de"]} for c in codes if c in cards and c in names}


def applies(topic: dict, body_key: str) -> bool:
    return SCOPED.get(topic["scheme"], body_key) == body_key


def stored_state(con, ids: list[int]) -> tuple[dict, dict]:
    hashes = dict(con.execute("SELECT openparldata_id, text_hash FROM affairs WHERE openparldata_id = ANY(%s)", (ids,)).fetchall())
    cards: dict[int, dict] = {}
    for a, t, h, m in con.execute("SELECT openparldata_id, topic_code, card_hash, model_revision FROM affair_topics_current "
                                  "WHERE openparldata_id = ANY(%s)", (ids,)).fetchall():
        cards.setdefault(a, {})[t] = (h, m)
    return hashes, cards


def llm_settings() -> tuple[str, str, dict]:
    url = os.environ.get("LLM_BASE_URL") or os.environ.get("PARLTOPICS_LLM_URL", "https://gateway.keera.ch/api/v1")
    model = os.environ.get("LLM_NAME") or os.environ.get("PARLTOPICS_LLM_MODEL", "apertus-v1-5-8b")
    key = os.environ.get("LLM_API_KEY")
    auth = Path(os.environ.get("PARLTOPICS_AUTH_HEADER", Path.home() / ".config/keera/auth_header"))
    if key:
        return url, model, {"Authorization": f"Bearer {key}"}
    if auth.exists():
        name, value = auth.read_text().strip().split(": ", 1)
        return url, model, {name: value}
    return url, model, {}


def score_llm(affair: dict, topics: dict, codes: list[str], concurrency: int) -> dict[str, float]:
    url, model, headers = llm_settings()

    def one(code: str) -> tuple[str, float]:
        body = {"model": model, "max_tokens": 1, "temperature": 0, "logprobs": True, "top_logprobs": 20,
                "messages": build_messages(render(topics[code]["card"]), affair["text"][:MAX_CHARS])}
        for attempt in range(4):
            try:
                r = httpx.post(f"{url}/chat/completions", headers=headers, json=body, timeout=60)
                r.raise_for_status()
                out = parse(r.json()["choices"][0])
                return code, out["lp_yes"] - out["lp_no"]
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    with ThreadPoolExecutor(concurrency) as pool:
        return dict(pool.map(one, codes))


def score_systemone(affair: dict, topics: dict, codes: list[str], decision_url: str) -> dict[str, float]:
    req = build_request(affair["text"][:MAX_CHARS], {c: topics[c]["card"] for c in codes}, compact=True)
    r = httpx.post(f"{decision_url.rstrip('/')}/v1/systemone", json=req, timeout=600)
    r.raise_for_status()
    answers = r.json()["answers"]
    return {c: logit(float(answers[c]["noul"])) for c in codes}


def topic_rows(affair: dict, topics: dict, scores: dict[str, float], tag: str, revision: str, run_id: str) -> pd.DataFrame:
    now = datetime.now(timezone.utc).isoformat()
    frames = []
    for code, score in scores.items():
        df = decide_rows(pd.DataFrame({"openparldata_id": [affair["openparldata_id"]], "score": [score]}), calibration_for(code, tag))
        frames.append(df.assign(body_key=affair["body_key"], lang=affair["lang"], scheme=topics[code]["scheme"], topic_code=code,
                                topic_name=topics[code]["name"], card_hash=topics[code]["card"]["hash"], second_opinion_model=None,
                                second_opinion_probability=None, evidence_quote=None, evidence_start=None, evidence_end=None,
                                evidence_source=None, reason=None, model_revision=revision, run_id=run_id, created_at=now))
    return pd.concat(frames, ignore_index=True)


def upsert_affairs(con, rows: list[dict]) -> None:
    cols = ", ".join(AFFAIR_COLS)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in AFFAIR_COLS[1:])
    with con.cursor() as cur:
        cur.executemany(f"INSERT INTO affairs ({cols}) VALUES ({', '.join(['%s'] * len(AFFAIR_COLS))}) "
                        f"ON CONFLICT (openparldata_id) DO UPDATE SET {sets}", [[r[c] for c in AFFAIR_COLS] for r in rows])


def upsert_texts(con, rows: list[dict]) -> None:
    with con.cursor() as cur:
        cur.executemany("INSERT INTO affair_texts (openparldata_id, text, text_source, text_hash) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (openparldata_id) DO UPDATE SET text = EXCLUDED.text, text_source = EXCLUDED.text_source, "
                        "text_hash = EXCLUDED.text_hash, updated_at = now() WHERE affair_texts.text_hash IS DISTINCT FROM EXCLUDED.text_hash",
                        [[r["openparldata_id"], r["text"], r["text_source"], r["text_hash"]] for r in rows])


def embed(con, rows: list[dict]) -> int:
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMB_MODEL, device="cpu")
    except Exception as exc:
        print(f"warning: embeddings skipped ({type(exc).__name__})", flush=True)
        return 0
    model.max_seq_length = 512
    vectors = model.encode_document([r["text"] for r in rows], batch_size=8, normalize_embeddings=True, convert_to_numpy=True)
    with con.cursor() as cur:
        cur.executemany("INSERT INTO affair_embeddings (openparldata_id, model, text_hash, embedding) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (openparldata_id, model) DO UPDATE SET text_hash = EXCLUDED.text_hash, embedding = EXCLUDED.embedding",
                        [[r["openparldata_id"], EMB_MODEL, r["text_hash"], "[" + ",".join(f"{x:.5g}" for x in np.asarray(v, dtype=np.float32)) + "]"]
                         for r, v in zip(rows, vectors)])
    return len(rows)


def main() -> int:
    read_env()
    ap = argparse.ArgumentParser(description="Classify parliamentary affairs that are new or changed since a date and store the results.")
    ap.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--topics", type=lambda s: [t.strip() for t in s.split(",") if t.strip()])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    t0 = time.monotonic()
    decision_url = os.environ.get("PARLTOPICS_DECISION_URL")
    tag, revision = ("parltopics8b", "apertus-parltopics-8b") if decision_url else ("apertus8b", f"{llm_settings()[1]} yes/no readout")
    run_id = f"nightly_{date.today().isoformat()}"
    summary = {"since": args.since.isoformat(), "path": "systemone" if decision_url else "llm", "fetched": 0, "unchanged": 0,
               "scored_affairs": 0, "rows": 0, "embedded": 0, "failed": 0, "skipped_no_title": 0}
    with httpx.Client(timeout=60) as c, connect() as con:
        info = bodies(c)
        listed = changed_since(c, args.since, args.limit)
        affairs = []
        for a in listed:
            try:
                built = build_affair(c, a, info)
            except (httpx.HTTPError, ValueError) as exc:
                print(f"fetch failed for {a['id']}: {type(exc).__name__}", flush=True)
                summary["failed"] += 1
                continue
            if built is None:
                summary["skipped_no_title"] += 1
            else:
                affairs.append(built)
        summary["fetched"] = len(affairs)
        topics = active_topics(con, args.topics)
        hashes, stored = stored_state(con, [a["openparldata_id"] for a in affairs])
        todo, unchanged = [], []
        for a in affairs:
            same_text = hashes.get(a["openparldata_id"]) == a["text_hash"]
            have = stored.get(a["openparldata_id"], {})
            codes = [c for c, t in topics.items() if applies(t, a["body_key"]) and not (same_text and have.get(c) == (t["card"]["hash"], revision))]
            if codes:
                todo.append((a, codes, not same_text))
            else:
                unchanged.append(a)
        summary["unchanged"] = len(unchanged)
        if args.dry_run:
            for a, codes, text_changed in todo:
                print(f"would score {a['openparldata_id']} {a['body_key']} {a['number']}: {len(codes)} topics, text changed: {text_changed}")
            summary["would_score"] = len(todo)
        else:
            con.execute(OVERLAY_DDL)
            upsert_texts(con, unchanged)
            con.commit()
            done, new_text = [], []
            for a, codes, text_changed in todo:
                try:
                    scores = score_systemone(a, topics, codes, decision_url) if decision_url else score_llm(a, topics, codes, args.concurrency)
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    print(f"scoring failed for {a['openparldata_id']}: {type(exc).__name__}", flush=True)
                    summary["failed"] += 1
                    continue
                upsert_affairs(con, [a])
                upsert_texts(con, [a])
                summary["rows"] += upsert_topics(con, topic_rows(a, topics, scores, tag, revision, run_id))
                con.commit()
                done.append(a)
                if text_changed:
                    new_text.append(a)
            summary["scored_affairs"] = len(done)
            if new_text and not args.no_embed:
                summary["embedded"] = embed(con, new_text)
                con.commit()
    summary["seconds"] = round(time.monotonic() - t0, 1)
    print("NIGHTLY_SUMMARY " + json.dumps(summary), flush=True)
    return 1 if summary["failed"] and not summary["scored_affairs"] and not summary["unchanged"] else 0


if __name__ == "__main__":
    sys.exit(main())
