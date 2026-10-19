import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from parltopics.db import connect, read_env

ROOT = Path(os.environ.get("PARLTOPICS_ROOT", Path(__file__).resolve().parents[2]))
read_env(ROOT / ".env")

router = APIRouter(prefix="/review")


class CorrectionRequest(BaseModel):
    affair_id: int
    topic: str = Field(min_length=1, max_length=80)
    decision: str = Field(pattern="^(yes|no)$")
    reason: str = Field("", max_length=500)
    reviewer: str = Field(min_length=1, max_length=80)


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("PARLTOPICS_DATABASE_URL")


def check(token: str | None) -> None:
    expected = os.environ.get("PARLTOPICS_REVIEW_TOKEN")
    if not expected or not database_url():
        raise HTTPException(503, "review is not configured (set PARLTOPICS_REVIEW_TOKEN and DATABASE_URL)")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "wrong access code")


def store_live(con, affair_id: int, topic: str) -> tuple:
    from parltopics import api

    entry = api.cards().get(topic)
    if entry is None:
        raise HTTPException(404, "unknown topic")
    if not api.LIVE:
        raise HTTPException(503, api.NO_LIVE)
    affair = api.local_affairs([affair_id]).get(affair_id) or api.fetch_affair(affair_id)
    if not affair.get("text"):
        raise HTTPException(409, "no text for this affair")
    try:
        res = api.decide_retry(affair["text"], entry["card"], entry["calibration"])
    except Exception:
        raise HTTPException(503, "the model is not reachable")
    con.execute("INSERT INTO affair_topics (openparldata_id, body_key, lang, scheme, topic_code, topic_name, card_hash, probability, decision, "
                "confidence, threshold, model_revision, run_id, created_at, calibrated) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s) ON CONFLICT DO NOTHING",
                (affair_id, affair.get("body_key"), affair.get("lang"), api.scheme_of(topic), topic, entry["card"]["name"], entry["card"]["hash"],
                 res.get("probability"), res["decision"], res["confidence"], res.get("threshold"), api.DECISION_MODEL, "live_review",
                 entry["calibration"] is not None))
    return res.get("probability"), res["decision"], api.DECISION_MODEL, entry["card"]["hash"]


@router.get("")
def status():
    return {"available": bool(os.environ.get("PARLTOPICS_REVIEW_TOKEN") and database_url())}


@router.get("/queue")
def queue(limit: int = Query(50, ge=1, le=200), x_review_token: str | None = Header(None)):
    check(x_review_token)
    with connect(database_url()) as con:
        rows = con.execute(
            "SELECT DISTINCT ON (f.openparldata_id, f.topic_code) f.openparldata_id, f.topic_code, f.note, f.created_at, "
            "t.decision, t.probability, t.corrected, a.title, a.title_de, a.title_fr, a.title_it, a.body_key, a.body_name, a.level, a.year, a.lang "
            "FROM affair_topic_flags f LEFT JOIN affair_topics_current t ON t.openparldata_id = f.openparldata_id AND t.topic_code = f.topic_code "
            "LEFT JOIN affairs a ON a.openparldata_id = f.openparldata_id "
            "WHERE NOT EXISTS (SELECT 1 FROM affair_topic_corrections c WHERE c.openparldata_id = f.openparldata_id "
            "AND c.topic_code = f.topic_code AND c.created_at >= f.created_at) "
            "ORDER BY f.openparldata_id, f.topic_code, f.created_at DESC LIMIT %s", (limit,)).fetchall()
        cols = ["openparldata_id", "topic", "note", "flagged_at", "decision", "probability", "corrected", "title", "title_de", "title_fr",
                "title_it", "body_key", "body_name", "level", "year", "lang"]
    out = [dict(zip(cols, r)) for r in rows]
    for r in out:
        r["flagged_at"] = r["flagged_at"].isoformat()
        r["stored"] = r["decision"] is not None
    return sorted(out, key=lambda r: r["flagged_at"], reverse=True)


@router.post("/corrections")
def correct(req: CorrectionRequest, x_review_token: str | None = Header(None)):
    check(x_review_token)
    with connect(database_url()) as con:
        row = con.execute("SELECT probability, decision, model_revision, card_hash FROM affair_topics WHERE openparldata_id = %s AND topic_code = %s "
                          "ORDER BY created_at DESC LIMIT 1", (req.affair_id, req.topic)).fetchone()
        if row is None:
            row = store_live(con, req.affair_id, req.topic)
        con.execute("INSERT INTO affair_topic_corrections (openparldata_id, topic_code, corrected_decision, reason, corrected_by, "
                    "original_probability, original_decision, model_revision, card_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (req.affair_id, req.topic, req.decision, req.reason.strip() or "reviewed on the search page", req.reviewer.strip(), *row))
        con.commit()
    return {"affair_id": req.affair_id, "topic": req.topic, "decision": req.decision, "original_decision": row[1], "corrected": True}
