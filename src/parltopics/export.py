import argparse
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from parltopics.cards import load

DDL = """CREATE TABLE IF NOT EXISTS affair_topics (
    openparldata_id   BIGINT      NOT NULL,
    body_key          TEXT        NOT NULL,
    lang              TEXT,
    scheme            TEXT        NOT NULL,
    topic_code        TEXT        NOT NULL,
    topic_name        TEXT,
    card_hash         TEXT        NOT NULL,
    probability       REAL        NOT NULL,
    decision          TEXT        NOT NULL CHECK (decision IN ('yes', 'no')),
    confidence        TEXT        NOT NULL CHECK (confidence IN ('high', 'low')),
    threshold         REAL        NOT NULL,
    second_opinion_model       TEXT,
    second_opinion_probability REAL,
    evidence_quote    TEXT,
    evidence_start    INTEGER,
    evidence_end      INTEGER,
    evidence_source   TEXT,
    reason            TEXT,
    model_revision    TEXT        NOT NULL,
    run_id            TEXT        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (openparldata_id, scheme, topic_code, card_hash, run_id)
);
CREATE INDEX IF NOT EXISTS affair_topics_topic ON affair_topics (scheme, topic_code, decision, probability DESC);
CREATE INDEX IF NOT EXISTS affair_topics_affair ON affair_topics (openparldata_id);
CREATE TABLE IF NOT EXISTS affair_topic_flags (
    id                BIGSERIAL   PRIMARY KEY,
    openparldata_id   BIGINT      NOT NULL,
    topic_code        TEXT        NOT NULL,
    note              TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS affair_topic_flags_topic ON affair_topic_flags (topic_code, openparldata_id);
"""

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "affair_topics row",
    "type": "object",
    "required": ["openparldata_id", "body_key", "scheme", "topic_code", "card_hash", "probability", "decision",
                 "confidence", "threshold", "model_revision", "run_id", "created_at"],
    "properties": {
        "openparldata_id": {"type": "integer"},
        "body_key": {"type": "string"},
        "lang": {"type": ["string", "null"]},
        "scheme": {"type": "string", "description": "adhoc, curia_vista or aps"},
        "topic_code": {"type": "string"},
        "topic_name": {"type": ["string", "null"]},
        "card_hash": {"type": "string", "description": "hash of the topic card used"},
        "probability": {"type": "number", "minimum": 0, "maximum": 1},
        "decision": {"enum": ["yes", "no"]},
        "confidence": {"enum": ["high", "low"], "description": "low when the first model was uncertain and the second opinion did not settle the case"},
        "threshold": {"type": "number"},
        "second_opinion_model": {"type": ["string", "null"]},
        "second_opinion_probability": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "evidence_quote": {"type": ["string", "null"]},
        "evidence_start": {"type": ["integer", "null"]},
        "evidence_end": {"type": ["integer", "null"]},
        "evidence_source": {"type": ["string", "null"], "description": "model (exact quote) or nearest_sentence"},
        "reason": {"type": ["string", "null"]},
        "model_revision": {"type": "string"},
        "run_id": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
    },
}


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def build_rows(scores, affairs, card, scheme, platt, threshold, band, explanations, model_revision, run_id, second=None):
    df = scores[["affair_id", "score"]].dropna().merge(affairs[["affair_id", "body_key", "lang"]], on="affair_id", how="left")
    a, b = platt
    df["probability"] = [sigmoid(a * s + b) for s in df["score"]]
    low, high = band
    uncertain = df["probability"].between(low, high, inclusive="left")
    df["decision"] = ["yes" if s >= threshold else "no" for s in df["score"]]
    df["second_opinion_model"], df["second_opinion_probability"] = None, None
    if second is not None:
        s2, (a2, b2), name = second
        p2 = df[["affair_id"]].merge(s2[["affair_id", "score"]], on="affair_id", how="left")["score"].map(
            lambda x: None if pd.isna(x) else sigmoid(a2 * x + b2))
        df.loc[uncertain, "second_opinion_probability"] = p2[uncertain].round(4)
        df.loc[uncertain & p2.notna(), "second_opinion_model"] = name
    p2 = pd.to_numeric(df["second_opinion_probability"])
    settled = uncertain & ((p2 >= high) | (p2 < low))
    df.loc[settled, "decision"] = ["yes" if v >= high else "no" for v in p2[settled]]
    df["confidence"] = ["low" if u and not st else "high" for u, st in zip(uncertain, settled)]
    if explanations is not None:
        df = df.merge(explanations[["affair_id", "quote", "quote_start", "quote_end", "quote_source", "reason"]], on="affair_id", how="left")
    else:
        df = df.assign(quote=None, quote_start=None, quote_end=None, quote_source=None, reason=None)
    now = datetime.now(timezone.utc).isoformat()
    return pd.DataFrame({
        "openparldata_id": df["affair_id"].astype("int64"), "body_key": df["body_key"], "lang": df["lang"],
        "scheme": scheme, "topic_code": card["id"], "topic_name": card["name"], "card_hash": card["hash"],
        "probability": df["probability"].round(4), "decision": df["decision"], "confidence": df["confidence"], "threshold": threshold,
        "second_opinion_model": df["second_opinion_model"], "second_opinion_probability": pd.to_numeric(df["second_opinion_probability"]),
        "evidence_quote": df["quote"], "evidence_start": df["quote_start"], "evidence_end": df["quote_end"],
        "evidence_source": df["quote_source"], "reason": df["reason"],
        "model_revision": model_revision, "run_id": run_id, "created_at": now,
    })


def main() -> None:
    ap = argparse.ArgumentParser(description="Write affair_topics rows (Parquet, gzipped NDJSON) plus the PostgreSQL DDL and JSON Schema.")
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--affairs", type=Path, required=True, help="parquet with affair_id, body_key, lang")
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--scheme", default="adhoc")
    ap.add_argument("--calibration", type=Path, required=True, help="json with platt a, b and threshold")
    ap.add_argument("--explanations", type=Path)
    ap.add_argument("--model-revision", required=True)
    ap.add_argument("--uncertain-low", type=float, default=0.2)
    ap.add_argument("--uncertain-high", type=float, default=0.6)
    ap.add_argument("--second-scores", type=Path)
    ap.add_argument("--second-calibration", type=Path)
    ap.add_argument("--second-model")
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    cal = json.loads(args.calibration.read_text())
    card = load(args.card)
    second = None
    if args.second_scores:
        cal2 = json.loads(args.second_calibration.read_text())
        second = (pd.read_parquet(args.second_scores), (cal2["a"], cal2["b"]), args.second_model)
    rows = build_rows(pd.read_parquet(args.scores), pd.read_parquet(args.affairs), card, args.scheme,
                      (cal["a"], cal["b"]), cal["threshold"], (args.uncertain_low, args.uncertain_high),
                      pd.read_parquet(args.explanations) if args.explanations else None,
                      args.model_revision, uuid.uuid4().hex[:12], second)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"affair_topics_{card['id']}"
    rows.to_parquet(args.out_dir / f"{stem}.parquet", index=False)
    rows.to_json(args.out_dir / f"{stem}.ndjson.gz", orient="records", lines=True, force_ascii=False, compression="gzip")
    (args.out_dir / "affair_topics.sql").write_text(DDL)
    (args.out_dir / "affair_topics.schema.json").write_text(json.dumps(SCHEMA, indent=2))
    print(rows.groupby(["decision", "confidence"]).size().to_string())
    print("settled by second opinion:", int((rows["second_opinion_model"].notna() & (rows["confidence"] == "high")).sum()))


if __name__ == "__main__":
    main()
