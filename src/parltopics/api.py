import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import duckdb
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from parltopics.cards import load, render
from parltopics.db import LEGACY, read_env
from parltopics.explain import PROMPT, locate, nearest_sentence, normalise
from parltopics.outcome import OUTCOMES
from parltopics.readout import build_messages, parse
from parltopics.spelling import suggest
from parltopics.speech import router as speech_router
from parltopics.review import router as review_router
from parltopics.systemone_multi import build_request, logit
from parltopics.vectors import Index

OPD = "https://api.openparldata.ch/v1"
ROOT = Path(os.environ.get("PARLTOPICS_ROOT", Path(__file__).resolve().parents[2]))
read_env(ROOT / ".env")
TABLE = os.environ.get("PARLTOPICS_TABLE", str(ROOT / "runs" / "export" / "affair_topics_*.parquet"))
AUTH_FILE = Path(os.environ.get("PARLTOPICS_AUTH_HEADER", Path.home() / ".config/keera/auth_header"))
LLM_URL = (os.environ.get("LLM_BASE_URL") or os.environ.get("PARLTOPICS_LLM_URL")
           or ("https://gateway.keera.ch/api/v1" if AUTH_FILE.exists() else None))
LLM_MODEL = os.environ.get("LLM_NAME") or os.environ.get("PARLTOPICS_LLM_MODEL", "apertus-v1-5-8b")
DECISION_URL = os.environ.get("PARLTOPICS_DECISION_URL") or None
DECISION_MODEL = "apertus-parltopics-8b" if DECISION_URL else LLM_MODEL
CAL_TAG = "parltopics8b" if DECISION_URL else "apertus8b"
LIVE = bool(DECISION_URL or LLM_URL)
NO_LIVE = "live classification needs an Apertus endpoint: set LLM_BASE_URL or PARLTOPICS_DECISION_URL in .env"
NO_EXPLAIN = "explanations need an Apertus chat endpoint: set LLM_BASE_URL in .env"
LLM_KEY = os.environ.get("LLM_API_KEY")
MAX_CHARS = 3500
LOW, HIGH = 0.2, 0.6
EMB_DIR = Path(os.environ.get("PARLTOPICS_EMB_DIR", ROOT / "runs" / "emb"))
EMB_MODEL = os.environ.get("PARLTOPICS_EMB_MODEL", "microsoft/harrier-oss-v1-0.6b")
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("PARLTOPICS_DATABASE_URL")
TEXTS = Path(os.environ.get("PARLTOPICS_TEXTS", ROOT / "data" / "affair_text.parquet"))
OUTCOME_FILE = Path(os.environ.get("PARLTOPICS_OUTCOMES", ROOT / "data" / "affair_outcome.parquet"))
WEB_OUT = Path(os.environ.get("PARLTOPICS_WEB", ROOT / "web" / "out"))
DEV_ORIGINS = [o for o in os.environ.get("PARLTOPICS_DEV_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o]
QUERY_PROMPT = "Instruct: Given a search query, retrieve Swiss parliamentary affairs that match it\nQuery: "
SCOPES = {"curia_vista": {"level": "country", "body": "CHE"}, "sg": {"level": "canton", "body": "SG"}}
OVERVIEW_POOL = 100
AFFAIR_COLS = ("a.openparldata_id, a.body_key, a.body_name, a.level, a.number, a.affair_type, a.year, a.lang, a.title, a.outcome, "
               "a.title_only, a.title_de, a.title_fr, a.title_it")
LEVEL = "^(country|canton|city|municipality)$"
BODY = "^[A-Za-z0-9]{1,8}$"

@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=warm_encoder, daemon=True).start()
    yield


app = FastAPI(title="Topic classification for Swiss parliamentary affairs", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Review-Token"])
app.include_router(speech_router)
app.include_router(review_router)


def llm_headers() -> dict:
    if LLM_KEY:
        return {"Authorization": f"Bearer {LLM_KEY}"}
    if AUTH_FILE.exists():
        name, value = AUTH_FILE.read_text().strip().split(": ", 1)
        return {name: value}
    return {}


def canonical(topic: str | None) -> str | None:
    return LEGACY.get(topic, topic) if topic else topic


def cards() -> dict:
    out = {}
    for path in sorted((ROOT / "cards").rglob("*.yaml")):
        card = load(path)
        cal = ROOT / "models" / f"calibration_{card['id']}_{CAL_TAG}.json"
        out[card["id"]] = {"card": card, "path": path, "calibration": json.loads(cal.read_text()) if cal.exists() else None}
    for old, new in LEGACY.items():
        if new in out:
            out[old] = out[new]
    return out


@lru_cache(maxsize=1)
def topic_names() -> dict:
    path = ROOT / "cards" / "topic_names.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def names(card_id: str, english: str) -> dict:
    n = topic_names().get(canonical(card_id))
    if n:
        return {lang: n[lang] for lang in ("de", "fr", "it", "rm", "en")}
    return {lang: english for lang in ("de", "fr", "it", "rm", "en")}


def scheme_of(topic: str) -> str:
    n = topic_names().get(canonical(topic))
    if n:
        return n["scheme"]
    return "curia_vista" if topic.startswith("curia_") else "sg" if topic.startswith("sg_") else "adhoc"


def topic_scope(topic: str) -> dict:
    return dict(SCOPES.get(scheme_of(topic), {}))


def outcome_names() -> dict:
    return OUTCOMES


def pg():
    import psycopg

    return psycopg.connect(DATABASE_URL)


def pg_rows(sql: str, params=None) -> list[dict]:
    with pg() as con, con.cursor() as cur:
        cur.execute(sql, params or {})
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@lru_cache(maxsize=4)
def _stored(bucket: int) -> dict:
    if DATABASE_URL:
        return {r["topic_code"]: r["n"] for r in pg_rows("SELECT topic_code, count(*) AS n FROM affair_topics GROUP BY topic_code")}
    try:
        with duckdb.connect() as con:
            rows = con.execute(f"SELECT topic_code, count(*) FROM read_parquet('{TABLE}') GROUP BY topic_code").fetchall()
        return {canonical(t): n for t, n in rows}
    except duckdb.Error:
        return {}


def stored_topics() -> dict:
    return _stored(int(time.time() // 60))


def strip_html(s: str) -> str:
    return normalise(re.sub(r"<[^>]+>", " ", s or ""))


def first(value, lang_order=("de", "fr", "it", "rm")):
    if isinstance(value, dict):
        for lang in lang_order:
            if value.get(lang):
                return value[lang], lang
    return (value, None) if isinstance(value, str) else (None, None)


def fetch_affair(affair_id: int) -> dict:
    with httpx.Client(timeout=20) as c:
        a = c.get(f"{OPD}/affairs/{affair_id}")
        if a.status_code == 404:
            raise HTTPException(404, f"affair {affair_id} not found in OpenParlData")
        a.raise_for_status()
        affair = a.json()
        title, lang = first(affair.get("title"))
        body = ""
        texts = c.get(f"{OPD}/affairs/{affair_id}/texts", params={"limit": 20}).json().get("data", [])
        parts = [strip_html(first(t.get("text"), (lang or "de",) + ("de", "fr", "it"))[0] or "") for t in texts]
        body = " ".join(p for p in parts if p)
        if not body:
            docs = c.get(f"{OPD}/affairs/{affair_id}/docs", params={"limit": 50}).json().get("data", [])
            docs = [d for d in docs if d.get("text") and d["text"].strip() not in ("", "[extraction_failed]")]
            if docs:
                body = normalise(max(docs, key=lambda d: len(d["text"]))["text"][:20000])
    text = "\n\n".join(x for x in (strip_html(title or ""), body[:3000]) if x)
    return {"affair_id": affair_id, "body_key": affair.get("body_key"), "lang": lang, "title": title, "text": text,
            "text_source": "texts" if texts and body else ("docs" if body else "title_only")}


def stored_texts(ids: list[int]) -> dict[int, dict]:
    if not ids or not DATABASE_URL:
        return {}
    rows = pg_rows("SELECT x.openparldata_id, a.body_key, a.lang, a.title, x.text, x.text_source, x.text_hash FROM affair_texts x "
                   "JOIN affairs a USING (openparldata_id) WHERE x.openparldata_id = ANY(%s)", [[int(i) for i in ids]])
    return {int(r["openparldata_id"]): r for r in rows}


def local_affairs(ids: list[int]) -> dict[int, dict]:
    out = {}
    if ids and TEXTS.exists():
        with duckdb.connect() as con:
            rows = con.execute(f"SELECT affair_id, body_key, lang, title, text, text_source, md5(text) FROM read_parquet('{TEXTS}') "
                               f"WHERE affair_id IN (SELECT unnest(?))", [[int(i) for i in ids]]).fetchall()
        out = {int(r[0]): {"affair_id": int(r[0]), "body_key": r[1], "lang": r[2], "title": r[3], "text": r[4], "text_source": r[5],
                           "text_hash": r[6]} for r in rows}
    for i, r in stored_texts(ids).items():
        if r["text"] and (i not in out or (r["text_hash"] and out[i]["text_hash"] != r["text_hash"])):
            out[i] = {"affair_id": i, "body_key": r["body_key"], "lang": r["lang"], "title": r["title"], "text": r["text"],
                      "text_source": r["text_source"], "text_hash": r["text_hash"]}
    return out


def decide(c: httpx.Client, text: str, card: dict, calibration: dict | None) -> dict:
    if DECISION_URL:
        r = c.post(f"{DECISION_URL.rstrip('/')}/v1/systemone", json=build_request(text[:MAX_CHARS], {card["id"]: card}, True))
        r.raise_for_status()
        score = logit(float(r.json()["answers"][card["id"]]["noul"]))
    else:
        r = c.post(f"{LLM_URL}/chat/completions", headers=llm_headers(), json={
            "model": LLM_MODEL, "max_tokens": 1, "temperature": 0, "logprobs": True, "top_logprobs": 20,
            "messages": build_messages(render(card), text[:MAX_CHARS])})
        r.raise_for_status()
        out = parse(r.json()["choices"][0])
        score = out["lp_yes"] - out["lp_no"]
    result = {"score": round(score, 3)}
    if calibration:
        p = 1 / (1 + math.exp(-(calibration["a"] * score + calibration["b"])))
        result.update(probability=round(p, 4), threshold=calibration["threshold"],
                      decision="yes" if score >= calibration["threshold"] else "no",
                      confidence="low" if LOW <= p < HIGH else "high", second_opinion_probability=None)
    else:
        result.update(probability=None, decision="yes" if score > 0 else "no", confidence="low")
    return result


def classify_text(text: str, card: dict, calibration: dict | None, lang: str | None = None) -> dict:
    headers = llm_headers()
    with httpx.Client(timeout=120) as c:
        result = decide(c, text, card, calibration)
        if not LLM_URL:
            result.update(evidence_quote=None, evidence_source=None, reason=None, explanation_unavailable=NO_EXPLAIN)
        elif result["decision"] == "yes" or result["confidence"] == "low":
            e = c.post(f"{LLM_URL}/chat/completions", headers=headers, json={
                "model": LLM_MODEL, "temperature": 0, "max_tokens": 300, "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": PROMPT.replace("in the language of the affair", f"in {LANGUAGE_NAMES.get(lang or 'de', 'German')}, calling the affair \"{AFFAIR_WORDS.get(lang or 'de', 'affair')}\"").format(card=render(card), text=text[:MAX_CHARS])}]}).json()
            content = e["choices"][0]["message"]["content"]
            data = json.loads(content[content.index("{"): content.rindex("}") + 1])
            span, source = locate(str(data.get("quote", "")), text), "model"
            if span is None:
                span, source = nearest_sentence(str(data.get("quote", "")), text), "nearest_sentence"
            result.update(evidence_quote=normalise(text)[span[0]:span[1]].strip() if span else None,
                          evidence_source=source if span else None, reason=data.get("reason"))
    return result


class ClassifyRequest(BaseModel):
    topic: str
    affair_id: int | None = None
    text: str | None = None
    lang: str | None = None


LANGUAGE_NAMES = {"de": "German", "fr": "French", "it": "Italian", "rm": "Romansh", "en": "English"}
AFFAIR_WORDS = {"de": "Geschäft", "fr": "objet", "it": "oggetto", "rm": "fatg", "en": "affair"}


FLAGS = Path(os.environ.get("PARLTOPICS_FLAGS", ROOT / "runs" / "flags.ndjson"))


class FlagRequest(BaseModel):
    affair_id: int
    topic: str
    note: str | None = None


@app.get("/", response_class=HTMLResponse)
def index():
    page = WEB_OUT / "index.html"
    if not page.exists():
        page = Path(__file__).parent / "static" / "index.html"
    return page.read_text(encoding="utf-8")


@app.post("/flags")
def add_flag(req: FlagRequest):
    topic, note = canonical(req.topic), (req.note or "")[:500] or None
    if DATABASE_URL:
        with pg() as con:
            con.execute("INSERT INTO affair_topic_flags (openparldata_id, topic_code, note) VALUES (%s, %s, %s)", [req.affair_id, topic, note])
        return {"stored": True}
    FLAGS.parent.mkdir(parents=True, exist_ok=True)
    with FLAGS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"affair_id": req.affair_id, "topic": topic, "note": note,
                            "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
    return {"stored": True}


@app.get("/flags")
def list_flags(affair_id: int | None = None, topic: str | None = None, limit: int = Query(100, ge=1, le=1000)):
    topic = canonical(topic)
    if DATABASE_URL:
        rows = pg_rows("SELECT openparldata_id AS affair_id, topic_code AS topic, note, created_at AS at FROM affair_topic_flags "
                       "WHERE (%(a)s::bigint IS NULL OR openparldata_id = %(a)s) AND (%(t)s::text IS NULL OR topic_code = %(t)s) "
                       "ORDER BY created_at DESC LIMIT %(n)s", {"a": affair_id, "t": topic, "n": limit})
        return [{**r, "at": r["at"].isoformat()} for r in rows]
    if not FLAGS.exists():
        return []
    rows = [json.loads(line) for line in FLAGS.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if (affair_id is None or r["affair_id"] == affair_id) and (topic is None or r["topic"] == topic)]
    return rows[::-1][:limit]


@app.get("/health")
def health():
    return {"status": "ok", "model": DECISION_MODEL, "explanations": LLM_MODEL if LLM_URL else None, "database": bool(DATABASE_URL),
            "live": LIVE, "encoder": "ready" if query_model.cache_info().currsize else "loading"}


def decide_retry(text: str, card: dict, calibration: dict | None, attempts: int = 2, timeout: float = 8.0) -> dict:
    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=timeout) as c:
                return decide(c, text, card, calibration)
        except httpx.HTTPError:
            if attempt == attempts - 1:
                raise
    raise RuntimeError("unreachable")


def run_parallel(fn, items: list, fallback, workers: int = 10, deadline: float = 25.0) -> list:
    pool = ThreadPoolExecutor(workers)
    futures = [pool.submit(fn, x) for x in items]
    wait(futures, timeout=deadline)
    pool.shutdown(wait=False, cancel_futures=True)
    return [f.result() if f.done() and not f.cancelled() and f.exception() is None else fallback(x) for f, x in zip(futures, items)]


@app.get("/topics")
def list_topics():
    stored = stored_topics()
    out = []
    for k, v in cards().items():
        if k in LEGACY or (not LIVE and k not in stored):
            continue
        n = topic_names().get(k, {})
        out.append({"id": k, "name": n.get("de", v["card"]["name"]), "names": names(k, v["card"]["name"]), "card_hash": v["card"]["hash"],
                    "calibrated": v["calibration"] is not None, "stored": k in stored, "scheme": scheme_of(k),
                    "parent": n.get("parent"), "scope": topic_scope(k) or None})
    return out


def answer(row: dict) -> dict:
    out = {"probability": row["probability"], "decision": row["decision"], "confidence": row["confidence"], "threshold": row["threshold"]}
    if "corrected" in row:
        out["corrected"] = bool(row["corrected"])
        if row["corrected"]:
            out["original_decision"] = row["original_decision"]
    return out


@app.get("/affairs/{affair_id}/topics")
def affair_topics(affair_id: int):
    if DATABASE_URL:
        rows = pg_rows("SELECT t.openparldata_id, t.scheme, t.topic_code, p.parent, t.topic_name, t.probability, t.decision, t.confidence, t.threshold, "
                       "t.calibrated, t.evidence_quote, t.reason, t.model_revision, t.run_id, t.created_at, t.corrected, t.original_decision, "
                       "t.correction_reason, t.corrected_by, t.corrected_at, t.card_hash, t.evidence_source FROM affair_topics_current t "
                       "LEFT JOIN topics p USING (topic_code) WHERE t.openparldata_id = %s ORDER BY t.probability DESC", [affair_id])
        return [{**r, "created_at": r["created_at"].isoformat(), "corrected_at": r["corrected_at"] and r["corrected_at"].isoformat()}
                for r in rows]
    with duckdb.connect() as con:
        rows = con.execute(f"SELECT * FROM read_parquet('{TABLE}') WHERE openparldata_id = ? ORDER BY probability DESC", [affair_id]).df()
    return json.loads(rows.to_json(orient="records", force_ascii=False))


@app.get("/affairs/{affair_id}/topics/live")
def affair_topics_live(affair_id: int):
    rows, have = [], set()
    if DATABASE_URL:
        for r in pg_rows("SELECT topic_code, probability, decision, confidence, threshold, corrected, original_decision "
                         "FROM affair_topics_current WHERE openparldata_id = %s", [affair_id]):
            have.add(r["topic_code"])
            rows.append({"topic": r["topic_code"], "name": names(r["topic_code"], r["topic_code"])["de"],
                         "names": names(r["topic_code"], r["topic_code"]), **answer(r)})
    if not LIVE:
        return sorted(rows, key=lambda r: -(r.get("probability") or 0))
    affair = local_affairs([affair_id]).get(affair_id) or fetch_affair(affair_id)
    if affair.get("text"):
        body = affair.get("body_key")
        todo = [(k, v) for k, v in cards().items() if k not in LEGACY and k not in have
                and v["calibration"] is not None and topic_scope(k).get("body", body) == body]

        def one(item):
            code, entry = item
            try:
                return {"topic": code, "name": names(code, entry["card"]["name"])["de"], "names": names(code, entry["card"]["name"]),
                        **decide_retry(affair["text"], entry["card"], entry["calibration"])}
            except httpx.HTTPError:
                return None

        rows += [r for r in run_parallel(one, todo, lambda _: None) if r]
    return sorted(rows, key=lambda r: -(r.get("probability") or 0))


@lru_cache(maxsize=1)
def vector_index() -> Index | None:
    tag = EMB_MODEL.split("/")[-1]
    return Index(EMB_DIR, tag) if (EMB_DIR / f"embeddings_{tag}.npy").exists() else None


def vector_literal(v) -> str:
    return "[" + ",".join(f"{float(x):.6g}" for x in v) + "]"


def pg_filters(level, body, year_from, year_to) -> tuple[str, dict]:
    sql, p = [], {}
    if level:
        sql.append("a.level = %(level)s")
        p["level"] = level
    if body:
        sql.append("a.body_key = %(body)s")
        p["body"] = body
    if year_from:
        sql.append("a.year >= %(yf)s")
        p["yf"] = year_from
    if year_to:
        sql.append("a.year <= %(yt)s")
        p["yt"] = year_to
    return "".join(f" AND {s}" for s in sql), p


def hit(row: dict) -> dict:
    out = {k: row[k] for k in ("openparldata_id", "body_key", "body_name", "level", "number", "affair_type", "year", "lang", "title", "outcome", "title_only")}
    out.update({k: row[k] for k in ("title_de", "title_fr", "title_it") if row.get(k)})
    out["similarity"] = round(float(row.get("similarity") or 0.0), 4)
    if row.get("decision"):
        out["topic_answer"] = answer(row)
    return out


def pg_rank(qv, limit: int, level=None, body=None, year_from=None, year_to=None, topic=None, restrict=False) -> list[dict]:
    where, p = pg_filters(level, body, year_from, year_to)
    p.update(v=vector_literal(qv), model=EMB_MODEL, n=limit, topic=topic)
    join = ""
    if topic:
        join = (" LEFT JOIN LATERAL (SELECT t.probability, t.decision, t.confidence, t.threshold, t.corrected, t.original_decision FROM affair_topics_current t "
                "WHERE t.openparldata_id = a.openparldata_id AND t.topic_code = %(topic)s) t ON true")
        if restrict:
            where += " AND t.decision = 'yes'"
    sql = (f"SELECT {AFFAIR_COLS}, 1 - (e.embedding <=> %(v)s::halfvec) AS similarity"
           f"{', t.probability, t.decision, t.confidence, t.threshold, t.corrected, t.original_decision' if topic else ''} "
           f"FROM affair_embeddings e JOIN affairs a ON a.openparldata_id = e.openparldata_id{join} "
           f"WHERE e.model = %(model)s{where} ORDER BY e.embedding <=> %(v)s::halfvec LIMIT %(n)s")
    with pg() as con, con.cursor() as cur:
        cur.execute("SET hnsw.ef_search = 200")
        cur.execute("SET hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, p)
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return sorted((hit(r) for r in rows), key=lambda h: -h["similarity"])


def pg_browse(topic: str, limit: int, level=None, body=None, year_from=None, year_to=None) -> list[dict]:
    where, p = pg_filters(level, body, year_from, year_to)
    p.update(topic=topic, n=limit)
    rows = pg_rows(f"SELECT {AFFAIR_COLS}, t.probability AS similarity, t.probability, t.decision, t.confidence, t.threshold, t.corrected, t.original_decision "
                   f"FROM affair_topics_current t JOIN affairs a ON a.openparldata_id = t.openparldata_id "
                   f"WHERE t.topic_code = %(topic)s AND t.decision = 'yes'{where} "
                   f"ORDER BY a.year DESC NULLS LAST, t.probability DESC LIMIT %(n)s", p)
    return [hit(r) for r in rows]


def file_rank(qv, limit: int, level=None, body=None, year_from=None, year_to=None) -> list[dict]:
    index = vector_index()
    if index is None:
        raise HTTPException(503, "embeddings are not available on this server")
    mask = index.mask(level, year_from, year_to)
    if body and index.meta is not None:
        in_body = (index.meta.reindex(index.ids)["body_key"] == body).fillna(False).to_numpy()
        mask = in_body if mask is None else mask & in_body
    return index.rank(qv, limit, mask)


@lru_cache(maxsize=1)
def _bodies(bucket: int) -> list[dict]:
    if DATABASE_URL:
        return pg_rows("SELECT body_key, body_name, level, count(*) AS affairs FROM affairs WHERE body_key IS NOT NULL "
                       "GROUP BY 1, 2, 3 ORDER BY 3, 2")
    index = vector_index()
    if index is None or index.meta is None:
        return []
    m = index.meta.groupby(["body_key", "body_name", "level"], dropna=True).size().reset_index(name="affairs")
    return json.loads(m.sort_values(["level", "body_name"]).to_json(orient="records", force_ascii=False))


@app.get("/bodies")
def bodies():
    return _bodies(int(time.time() // 3600))


@app.get("/affairs/{affair_id}/similar")
def similar_affairs(affair_id: int, limit: int = Query(8, ge=1, le=50)):
    if DATABASE_URL:
        row = pg_rows("SELECT embedding::text AS v FROM affair_embeddings WHERE openparldata_id = %s AND model = %s", [affair_id, EMB_MODEL])
        if not row:
            return []
        qv = json.loads(row[0]["v"])
        return [h for h in pg_rank(qv, limit + 1) if h["openparldata_id"] != affair_id][:limit]
    index = vector_index()
    if index is None:
        raise HTTPException(503, "embeddings are not available on this server")
    return index.similar(affair_id, limit)


@app.get("/topics/{topic}/affairs")
def topic_affairs(topic: str, decision: str | None = Query(None, pattern="^(yes|no)$"),
                  confidence: str | None = Query(None, pattern="^(high|low)$"),
                  min_probability: float = 0.0, limit: int = Query(50, le=1000),
                  order: str = Query("uncertain", pattern="^(uncertain|probability|newest)$"), since: str | None = None,
                  until: str | None = None):
    topic = canonical(topic)
    if DATABASE_URL:
        order_by = {"uncertain": "abs(t.probability - 0.4)", "probability": "t.probability DESC",
                    "newest": "a.begin_date DESC NULLS LAST"}[order]
        rows = pg_rows("SELECT t.openparldata_id, t.body_key, a.body_name, a.level, a.number, a.title, a.title_de, a.title_fr, a.title_it, a.begin_date, t.lang, t.topic_code, "
                       "t.probability, t.decision, t.confidence, t.threshold, t.calibrated, t.corrected, t.original_decision, t.card_hash, t.model_revision, t.run_id "
                       "FROM affair_topics_current t JOIN affairs a USING (openparldata_id) WHERE t.topic_code = %(t)s "
                       "AND (%(d)s::text IS NULL OR t.decision = %(d)s) AND (%(c)s::text IS NULL OR t.confidence = %(c)s) "
                       "AND t.probability >= %(p)s AND (%(s)s::date IS NULL OR a.begin_date >= %(s)s::date) "
                       "AND (%(u)s::date IS NULL OR a.begin_date <= %(u)s::date) "
                       f"ORDER BY {order_by} LIMIT %(n)s",
                       {"t": topic, "d": decision, "c": confidence, "p": min_probability, "s": since, "u": until, "n": limit})
        return rows
    legacy = {v: k for k, v in LEGACY.items()}.get(topic, topic)
    with duckdb.connect() as con:
        rows = con.execute(f"SELECT * FROM read_parquet('{TABLE}') WHERE topic_code IN (?, ?) AND decision = coalesce(?, decision) "
                           f"AND confidence = coalesce(?, confidence) AND probability >= ? "
                           f"ORDER BY abs(probability - 0.4) LIMIT ?", [topic, legacy, decision, confidence, min_probability, limit]).df()
    return json.loads(rows.to_json(orient="records", force_ascii=False))


@app.get("/topics/{topic}/summary")
def topic_summary(topic: str):
    topic = canonical(topic)
    sql = (f"SELECT count(*) AS total, count(*) FILTER (WHERE decision = 'yes') AS yes, "
           f"count(*) FILTER (WHERE probability >= {LOW} AND probability < {HIGH}) AS uncertain, "
           f"count(*) FILTER (WHERE second_opinion_model IS NOT NULL AND confidence = 'high') AS settled, "
           f"count(*) FILTER (WHERE confidence = 'low') AS low")
    if DATABASE_URL:
        return pg_rows(f"{sql} FROM affair_topics_current WHERE topic_code = %s", [topic])[0]
    legacy = {v: k for k, v in LEGACY.items()}.get(topic, topic)
    with duckdb.connect() as con:
        row = con.execute(f"{sql} FROM read_parquet('{TABLE}') WHERE topic_code IN (?, ?)", [topic, legacy]).fetchone()
    return dict(zip(("total", "yes", "uncertain", "settled", "low"), row))


@app.post("/classify")
def classify(req: ClassifyRequest):
    all_cards = cards()
    if req.topic not in all_cards:
        raise HTTPException(404, f"unknown topic {req.topic!r}; see /topics")
    if req.affair_id is None and not req.text:
        raise HTTPException(422, "give affair_id or text")
    if not LIVE:
        raise HTTPException(503, NO_LIVE)
    if req.affair_id is not None:
        affair = local_affairs([req.affair_id]).get(req.affair_id) or fetch_affair(req.affair_id)
    else:
        affair = {"affair_id": None, "text": req.text}
    entry = all_cards[req.topic]
    result = classify_text(affair["text"], entry["card"], entry["calibration"], req.lang or affair.get("lang"))
    return {**{k: v for k, v in affair.items() if k != "text"}, "excerpt": normalise(affair["text"])[:1600],
            "topic": canonical(req.topic), "topic_name": entry["card"]["name"], "card_hash": entry["card"]["hash"],
            "model": DECISION_MODEL, "explanation_model": LLM_MODEL, **result}


@lru_cache(maxsize=1)
def query_model():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMB_MODEL, device="cpu")


ENCODE_LOCK = threading.Lock()


@lru_cache(maxsize=256)
def query_vector(text: str):
    with ENCODE_LOCK:
        return query_model().encode([QUERY_PROMPT + text], normalize_embeddings=True)[0]


def warm_encoder() -> None:
    query_vector("Digitalisierung der Verwaltung")


def resolve_topic(topic: str | None, level, body):
    if not topic:
        return None, level, body
    topic = canonical(topic)
    all_cards = cards()
    if topic not in all_cards:
        raise HTTPException(404, f"unknown topic {topic!r}; see /topics")
    scope = topic_scope(topic)
    return all_cards[topic], scope.get("level", level), scope.get("body", body)


def topic_text(entry: dict) -> str:
    return f"{entry['card']['name']}. {entry['card'].get('definition', '')}"


@app.get("/search")
def search(q: str | None = Query(None, min_length=2, max_length=500), limit: int = Query(20, ge=1, le=50),
           level: str | None = Query(None, pattern=LEVEL), year_from: int | None = None, year_to: int | None = None,
           topic: str | None = None, body: str | None = Query(None, pattern=BODY), only_topic: bool = True):
    q = (q or "").strip() or None
    if not q and not topic:
        raise HTTPException(422, "give q, topic or both")
    topic = canonical(topic)
    entry, level, body = resolve_topic(topic, level, body)
    if year_from and year_to and year_from > year_to:
        year_from, year_to = year_to, year_from
    mode = "query_topic" if q and topic else ("query" if q else "topic")
    restrict = bool(topic) and (only_topic or not q)
    stored = DATABASE_URL is not None and topic is not None and topic in stored_topics()
    if topic and not stored and not LIVE:
        raise HTTPException(503, f"{topic} has no stored decisions; {NO_LIVE}")
    filters = (level, body, year_from, year_to)
    checked = 0
    if stored and mode == "topic":
        hits = pg_browse(topic, limit, *filters)
        checked = stored_topics().get(topic, 0)
    else:
        pool = {"query": max(5 * limit, 100), "query_topic": 60, "topic": 80}[mode] if restrict and not stored else max(5 * limit, 100)
        qv = query_vector(q if q else topic_text(entry))
        if DATABASE_URL:
            hits = pg_rank(qv, pool, *filters, topic=topic if stored else None, restrict=restrict and stored)
        else:
            hits = file_rank(qv, pool, *filters)
        if q:
            words = [w.lower() for w in re.findall(r"\w{3,}", q)]
            for h in hits:
                title = str(h.get("title") or "").lower()
                h["keyword_match"] = bool(words) and len(words) <= 4 and all(w in title for w in words)
                h["score"] = h["similarity"] + (0.03 if h["keyword_match"] else 0.0)
            hits = sorted(hits, key=lambda h: -h["score"])
        if stored:
            checked = len(hits)
        elif topic:
            if not restrict:
                hits = hits[:limit]
            texts = local_affairs([h["openparldata_id"] for h in hits])

            def one(h):
                text = texts.get(h["openparldata_id"], {}).get("text")
                if not text:
                    return h
                try:
                    return {**h, "topic_answer": decide_retry(text, entry["card"], entry["calibration"])}
                except httpx.HTTPError:
                    return h

            hits = run_parallel(one, hits, lambda h: h)
            checked = sum(1 for h in hits if "topic_answer" in h)
            if restrict:
                hits = [h for h in hits if h.get("topic_answer", {}).get("decision") == "yes"]
                if mode == "topic":
                    hits.sort(key=lambda h: (-(h.get("year") or 0), -(h["topic_answer"].get("probability") or 0)))
    hits = hits[:limit]
    return {"query": q, "did_you_mean": suggest(q) if q else None, "topic": topic, "mode": mode, "checked": checked, "stored": stored,
            "level": level, "body": body, "year_from": year_from, "year_to": year_to, "results": hits}


def summarise(rows: list[dict]) -> dict:
    by_body: dict[str, dict] = {}
    totals = {k: 0 for k in OUTCOMES}
    for r in rows:
        o = r.get("outcome") or "unknown"
        totals[o] = totals.get(o, 0) + r["n"]
        b = by_body.setdefault(r["body_key"] or "?", {"body_key": r["body_key"], "body_name": r["body_name"], "level": r["level"],
                                                     "total": 0, "outcomes": {k: 0 for k in OUTCOMES}})
        b["total"] += r["n"]
        b["outcomes"][o] = b["outcomes"].get(o, 0) + r["n"]
    bodies = sorted(by_body.values(), key=lambda b: (-b["total"], b["body_name"] or ""))
    return {"total": sum(totals.values()), "parliaments": len(bodies), "outcomes": totals, "by_body": bodies}


def count_rows(ids_outcomes: list[dict]) -> list[dict]:
    agg: dict[tuple, dict] = {}
    for h in ids_outcomes:
        key = (h.get("body_key"), h.get("body_name"), h.get("level"), h.get("outcome") or "unknown")
        agg.setdefault(key, {"body_key": key[0], "body_name": key[1], "level": key[2], "outcome": key[3], "n": 0})["n"] += 1
    return list(agg.values())


def file_outcomes(hits: list[dict]) -> list[dict]:
    if not hits or not OUTCOME_FILE.exists():
        return hits
    with duckdb.connect() as con:
        rows = dict(con.execute(f"SELECT affair_id, outcome FROM read_parquet('{OUTCOME_FILE}') WHERE affair_id IN (SELECT unnest(?))",
                                [[h["openparldata_id"] for h in hits]]).fetchall())
    return [{**h, "outcome": rows.get(h["openparldata_id"], "unknown")} for h in hits]


@app.get("/overview")
def overview(q: str | None = Query(None, min_length=2, max_length=500), level: str | None = Query(None, pattern=LEVEL),
             year_from: int | None = None, year_to: int | None = None, topic: str | None = None,
             body: str | None = Query(None, pattern=BODY)):
    q = (q or "").strip() or None
    if not q and not topic:
        raise HTTPException(422, "give q, topic or both")
    topic = canonical(topic)
    entry, level, body = resolve_topic(topic, level, body)
    if year_from and year_to and year_from > year_to:
        year_from, year_to = year_to, year_from
    filters = (level, body, year_from, year_to)
    stored = topic is not None and topic in stored_topics()
    if stored and not q and DATABASE_URL:
        where, p = pg_filters(*filters)
        p["topic"] = topic
        rows = pg_rows(f"SELECT a.body_key, a.body_name, a.level, a.outcome, count(*) AS n FROM affair_topics_current t "
                       f"JOIN affairs a ON a.openparldata_id = t.openparldata_id WHERE t.topic_code = %(topic)s AND t.decision = 'yes'{where} "
                       f"GROUP BY 1, 2, 3, 4", p)
        basis, pool = "topic", None
    elif stored and not q:
        legacy = {v: k for k, v in LEGACY.items()}.get(topic, topic)
        with duckdb.connect() as con:
            ids = [r[0] for r in con.execute(f"SELECT DISTINCT openparldata_id FROM read_parquet('{TABLE}') WHERE topic_code IN (?, ?) "
                                             f"AND decision = 'yes'", [topic, legacy]).fetchall()]
        index = vector_index()
        hits = [index.describe(a) for a in ids] if index is not None else [{"openparldata_id": a} for a in ids]
        hits = [h for h in hits if (not level or h.get("level") == level) and (not body or h.get("body_key") == body)
                and (not year_from or (h.get("year") or 0) >= year_from) and (not year_to or (h.get("year") or 9999) <= year_to)]
        rows, basis, pool = count_rows(file_outcomes(hits)), "topic", None
    else:
        qv = query_vector(q if q else topic_text(entry))
        if DATABASE_URL:
            hits = pg_rank(qv, OVERVIEW_POOL, *filters, topic=topic if stored else None, restrict=stored)
        else:
            hits = file_outcomes(file_rank(qv, OVERVIEW_POOL, *filters))
        rows = count_rows(hits)
        basis, pool = ("query_topic" if stored else "query") if q else "similar", OVERVIEW_POOL
    return {"basis": basis, "pool": pool, "query": q, "topic": topic, "level": level, "body": body,
            "year_from": year_from, "year_to": year_to, **summarise(rows), "outcome_names": OUTCOMES}


@app.get("/affairs/{affair_id}/detail")
def affair_detail(affair_id: int, lang: str = Query("de", pattern="^(de|fr|it|rm|en)$")):
    local = local_affairs([affair_id]).get(affair_id)
    if DATABASE_URL:
        rows = pg_rows(f"SELECT {AFFAIR_COLS}, a.state, a.url_external FROM affairs a WHERE a.openparldata_id = %s", [affair_id])
        out = {k: v for k, v in rows[0].items() if v is not None} if rows else {"openparldata_id": affair_id}
    else:
        index = vector_index()
        out = index.describe(affair_id) if index is not None else {"openparldata_id": affair_id}
    if local:
        out.update(excerpt=normalise(local["text"])[:1800], text_source=local["text_source"])
    out["url_openparldata"] = f"{OPD}/affairs/{affair_id}"
    try:
        a = httpx.get(f"{OPD}/affairs/{affair_id}", timeout=15).json()
        a = a.get("data", a)
        pick = lambda v: first(v, (lang, "de", "fr", "it", "rm", "en"))[0] if isinstance(v, dict) else v
        out.update(type=pick(a.get("type_harmonized")) or pick(a.get("type_name")), state=pick(a.get("state_name")) or out.get("state"),
                   begin_date=(a.get("begin_date") or "")[:10] or None, number=a.get("number") or out.get("number"),
                   url_external=pick(a.get("url_external")) or out.get("url_external"))
        if not local:
            out["title"] = pick(a.get("title"))
    except (httpx.HTTPError, ValueError):
        pass
    return out


if WEB_OUT.is_dir():
    app.mount("/", StaticFiles(directory=WEB_OUT, html=True), name="web")
