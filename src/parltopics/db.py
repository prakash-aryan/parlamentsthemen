import argparse
import io
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from parltopics.cards import load
from parltopics.evaluate import best_threshold, platt
from parltopics.export import DDL as TOPICS_DDL
from parltopics.vectors import DDL as EMB_DDL, INDEX as EMB_INDEX

ROOT = Path(os.environ.get("PARLTOPICS_ROOT", Path(__file__).resolve().parents[2]))
EMB_MODEL = "microsoft/harrier-oss-v1-0.6b"
LOW, HIGH = 0.2, 0.6
LEGACY = {"digitalisation": "adhoc_digitalisation"}
SCOPES = {"curia_vista": ("country", "CHE"), "sg": ("canton", "SG")}
SCORE_FILE = re.compile(r"^(chunk_\d+)_full_(.+)\.parquet$")

DDL = """CREATE TABLE IF NOT EXISTS affairs (
    openparldata_id   BIGINT      PRIMARY KEY,
    body_key          TEXT,
    body_name         TEXT,
    level             TEXT,
    number            TEXT,
    affair_type       TEXT,
    year              INTEGER,
    begin_date        DATE,
    lang              TEXT,
    title             TEXT,
    url_external      TEXT,
    text_hash         TEXT
);
ALTER TABLE affairs ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE affairs ADD COLUMN IF NOT EXISTS outcome TEXT;
ALTER TABLE affairs ADD COLUMN IF NOT EXISTS title_only BOOLEAN;
ALTER TABLE affairs ADD COLUMN IF NOT EXISTS title_de TEXT;
ALTER TABLE affairs ADD COLUMN IF NOT EXISTS title_fr TEXT;
ALTER TABLE affairs ADD COLUMN IF NOT EXISTS title_it TEXT;
CREATE INDEX IF NOT EXISTS affairs_filter ON affairs (level, body_key, year);
CREATE TABLE IF NOT EXISTS topics (
    topic_code        TEXT        PRIMARY KEY,
    scheme            TEXT        NOT NULL,
    parent            TEXT,
    scope_level       TEXT,
    scope_body        TEXT,
    name_de           TEXT,
    name_fr           TEXT,
    name_it           TEXT,
    name_rm           TEXT,
    name_en           TEXT,
    card_hash         TEXT
);
ALTER TABLE affair_topics ADD COLUMN IF NOT EXISTS calibrated BOOLEAN NOT NULL DEFAULT true;
CREATE INDEX IF NOT EXISTS affair_topics_current_order ON affair_topics (topic_code, openparldata_id, created_at DESC);
"""

OVERLAY_DDL = """CREATE TABLE IF NOT EXISTS affair_texts (
    openparldata_id   BIGINT      PRIMARY KEY,
    text              TEXT,
    text_source       TEXT
);
ALTER TABLE affair_texts ADD COLUMN IF NOT EXISTS text_hash TEXT;
ALTER TABLE affair_texts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS affair_topic_corrections (
    id                    BIGSERIAL   PRIMARY KEY,
    openparldata_id       BIGINT      NOT NULL,
    topic_code            TEXT        NOT NULL,
    corrected_decision    TEXT        NOT NULL CHECK (corrected_decision IN ('yes', 'no')),
    reason                TEXT        NOT NULL,
    corrected_by          TEXT        NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    original_probability  REAL,
    original_decision     TEXT,
    model_revision        TEXT,
    card_hash             TEXT
);
CREATE INDEX IF NOT EXISTS affair_topic_corrections_key ON affair_topic_corrections (openparldata_id, topic_code, created_at DESC);
CREATE OR REPLACE VIEW affair_topics_current AS
SELECT t.openparldata_id, t.body_key, t.lang, t.scheme, t.topic_code, t.topic_name, t.card_hash, t.probability,
       COALESCE(c.corrected_decision, t.decision) AS decision, t.confidence, t.threshold, t.second_opinion_model,
       t.second_opinion_probability, t.evidence_quote, t.evidence_start, t.evidence_end, t.evidence_source, t.reason,
       t.model_revision, t.run_id, t.created_at, t.calibrated,
       c.corrected_decision IS NOT NULL AS corrected, t.decision AS original_decision, c.reason AS correction_reason,
       c.corrected_by, c.created_at AS corrected_at
FROM (SELECT DISTINCT ON (openparldata_id, topic_code) * FROM affair_topics
      ORDER BY openparldata_id, topic_code, created_at DESC) t
LEFT JOIN (SELECT DISTINCT ON (openparldata_id, topic_code) openparldata_id, topic_code, corrected_decision, reason, corrected_by, created_at
           FROM affair_topic_corrections ORDER BY openparldata_id, topic_code, created_at DESC) c
       ON c.openparldata_id = t.openparldata_id AND c.topic_code = t.topic_code;
"""

COLUMNS = ["openparldata_id", "body_key", "lang", "scheme", "topic_code", "topic_name", "card_hash", "probability", "decision",
           "confidence", "threshold", "second_opinion_model", "second_opinion_probability", "evidence_quote", "evidence_start",
           "evidence_end", "evidence_source", "reason", "model_revision", "run_id", "created_at", "calibrated"]


def connect(database_url: str | None = None):
    import psycopg

    return psycopg.connect(database_url or os.environ["DATABASE_URL"])


def read_env(path: Path = ROOT / ".env") -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def init(con) -> None:
    con.execute(EMB_DDL.format(dim=1024))
    con.execute(TOPICS_DDL)
    con.execute(DDL)
    con.execute(OVERLAY_DDL)


def copy_frame(con, table: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    with con.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')") as copy:
        while chunk := buf.read(1 << 20):
            copy.write(chunk)


def load_affairs(con) -> int:
    meta = pd.read_parquet(ROOT / "runs/emb/affair_meta.parquet")
    dates = duckdb.sql(f"SELECT affair_id, begin_date, text_source = 'title_only' AS title_only, title_de, title_fr, title_it "
                       f"FROM read_parquet('{ROOT / 'data/affair_text.parquet'}')").df()
    df = meta.merge(dates, on="affair_id", how="left")
    outcome = ROOT / "data/affair_outcome.parquet"
    if outcome.exists():
        df = df.merge(pd.read_parquet(outcome), on="affair_id", how="left")
    else:
        df = df.assign(state=None, outcome="unknown", url_external=None)
    df = df.rename(columns={"affair_id": "openparldata_id"})
    df["outcome"] = df["outcome"].fillna("unknown")
    df["year"] = df["year"].astype("Int64")
    df["begin_date"] = pd.to_datetime(df["begin_date"], errors="coerce").dt.date
    cols = ["openparldata_id", "body_key", "body_name", "level", "number", "affair_type", "year", "begin_date", "lang", "title",
            "url_external", "text_hash", "state", "outcome", "title_only", "title_de", "title_fr", "title_it"]
    con.execute("CREATE TEMP TABLE affairs_in (LIKE affairs INCLUDING DEFAULTS) ON COMMIT DROP")
    copy_frame(con, "affairs_in", df[cols])
    con.execute(f"INSERT INTO affairs ({', '.join(cols)}) SELECT {', '.join(cols)} FROM affairs_in "
                f"ON CONFLICT (openparldata_id) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:]))
    return len(df)


def load_embeddings(con, batch: int = 5000) -> int:
    tag = EMB_MODEL.split("/")[-1]
    vectors = np.load(ROOT / "runs/emb" / f"embeddings_{tag}.npy", mmap_mode="r")
    ids = pd.read_parquet(ROOT / "runs/emb" / f"embeddings_{tag}_ids.parquet")["affair_id"].to_numpy()
    hashes = pd.read_parquet(ROOT / "runs/emb/affair_meta.parquet", columns=["affair_id", "text_hash"]).set_index("affair_id")["text_hash"]
    con.execute("DROP INDEX IF EXISTS affair_embeddings_hnsw")
    con.execute("DELETE FROM affair_embeddings WHERE model = %s", [EMB_MODEL])
    with con.cursor() as cur, cur.copy("COPY affair_embeddings (openparldata_id, model, text_hash, embedding) FROM STDIN") as copy:
        for start in range(0, len(ids), batch):
            block = np.char.mod("%.5g", np.asarray(vectors[start:start + batch], dtype=np.float32))
            lines = [f"{int(a)}\t{EMB_MODEL}\t{hashes.get(int(a), '')}\t[{','.join(v)}]\n" for a, v in zip(ids[start:start + batch], block)]
            copy.write("".join(lines))
            print(f"{min(start + batch, len(ids))}/{len(ids)}", flush=True)
    return len(ids)


def build_index(con) -> None:
    con.execute("SET maintenance_work_mem = '4GB'")
    con.execute("SET max_parallel_maintenance_workers = 4")
    con.execute(EMB_INDEX)


def card_index() -> dict:
    out = {}
    for path in sorted((ROOT / "cards").rglob("*.yaml")):
        card = load(path)
        out[card["id"]] = card
    for old, new in LEGACY.items():
        if new in out:
            out[old] = out[new]
    return out


def load_topics(con) -> int:
    names = json.loads((ROOT / "cards/topic_names.json").read_text(encoding="utf-8"))
    cards = card_index()
    rows = []
    for code, n in names.items():
        level, body = SCOPES.get(n["scheme"], (None, None))
        rows.append({"topic_code": code, "scheme": n["scheme"], "parent": n.get("parent"), "scope_level": level, "scope_body": body,
                     **{f"name_{lang}": n[lang] for lang in ("de", "fr", "it", "rm", "en")},
                     "card_hash": cards[code]["hash"] if code in cards else None})
    df = pd.DataFrame(rows)
    con.execute("CREATE TEMP TABLE topics_in (LIKE topics) ON COMMIT DROP")
    copy_frame(con, "topics_in", df)
    cols = list(df.columns)
    con.execute(f"INSERT INTO topics SELECT * FROM topics_in ON CONFLICT (topic_code) DO UPDATE SET "
                + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:]))
    return len(df)


def upsert_topics(con, df: pd.DataFrame) -> int:
    df = df[COLUMNS].astype({"evidence_start": "Int64", "evidence_end": "Int64", "openparldata_id": "int64"})
    con.execute("CREATE TEMP TABLE IF NOT EXISTS affair_topics_in (LIKE affair_topics)")
    con.execute("TRUNCATE affair_topics_in")
    copy_frame(con, "affair_topics_in", df)
    keys = ("openparldata_id", "scheme", "topic_code", "card_hash", "run_id")
    con.execute(f"INSERT INTO affair_topics ({', '.join(COLUMNS)}) SELECT {', '.join(COLUMNS)} FROM affair_topics_in "
                f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in keys))
    return len(df)


def load_export(con) -> int:
    total = 0
    for path in sorted((ROOT / "runs/export").glob("affair_topics_*.parquet")):
        df = pd.read_parquet(path)
        df["topic_code"] = df["topic_code"].replace(LEGACY)
        df["calibrated"] = True
        total += upsert_topics(con, df)
    return total


def calibration_for(code: str, tag: str) -> dict | None:
    for name in (code, "default"):
        path = ROOT / "models" / f"calibration_{name}_{tag}.json"
        if path.exists():
            return json.loads(path.read_text())
    return None


def decide_rows(scores: pd.DataFrame, calibration: dict | None) -> pd.DataFrame:
    s = scores["score"].to_numpy(float)
    if calibration:
        p = 1 / (1 + np.exp(-(calibration["a"] * s + calibration["b"])))
        threshold, calibrated = calibration["threshold"], calibration.get("calibrated", True)
    else:
        p = 1 / (1 + np.exp(-s))
        threshold, calibrated = 0.0, False
    return scores.assign(probability=np.round(p, 4), decision=np.where(s >= threshold, "yes", "no"),
                         confidence=np.where((p >= LOW) & (p < HIGH), "low", "high"), threshold=threshold, calibrated=calibrated)


def load_scores(con, dirs: list[Path], run_id: str, model_revision: str, tag: str) -> dict:
    cards = card_index()
    names = json.loads((ROOT / "cards/topic_names.json").read_text(encoding="utf-8"))
    affairs = pd.DataFrame(con.execute("SELECT openparldata_id, body_key, lang FROM affairs").fetchall(),
                           columns=["openparldata_id", "body_key", "lang"])
    counts: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()
    for d in dirs:
        for path in sorted(d.glob("chunk_*_full_*.parquet")):
            m = SCORE_FILE.match(path.name)
            code = LEGACY.get(m.group(2), m.group(2))
            if code not in cards or code not in names:
                print(f"skip {path.name}: unknown topic {code}")
                continue
            df = pd.read_parquet(path).dropna(subset=["score"]).rename(columns={"affair_id": "openparldata_id"})
            df = decide_rows(df, calibration_for(code, tag)).merge(affairs, on="openparldata_id", how="inner")
            card = cards[code]
            df = df.assign(scheme=names[code]["scheme"], topic_code=code, topic_name=names[code]["de"], card_hash=card["hash"],
                           second_opinion_model=None, second_opinion_probability=None, evidence_quote=None, evidence_start=None,
                           evidence_end=None, evidence_source=None, reason=None, model_revision=model_revision, run_id=run_id, created_at=now)
            counts[code] = counts.get(code, 0) + upsert_topics(con, df)
            con.commit()
    return counts


def calibrate(dev: Path, scores: Path, code: str, tag: str) -> dict:
    d = pd.read_parquet(dev)[["affair_id", "label", "weight"]].merge(pd.read_parquet(scores)[["affair_id", "score"]], on="affair_id").dropna()
    a, b = platt(d)
    thr = best_threshold(d["label"].to_numpy(bool), d["score"].to_numpy(float), d["weight"].to_numpy(float))
    out = {"model": tag, "card": code, "a": a, "b": b, "threshold": thr,
           "fitted_on": f"{dev.name}, {len(d)} affairs before 2024, {int(d['label'].sum())} positives"}
    (ROOT / "models" / f"calibration_{code}_{tag}.json").write_text(json.dumps(out, indent=2))
    return out


def main() -> None:
    read_env()
    ap = argparse.ArgumentParser(description="PostgreSQL with pgvector: schema, affairs, embeddings, topics and topic decisions.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("affairs")
    e = sub.add_parser("embeddings")
    e.add_argument("--batch", type=int, default=5000)
    sub.add_parser("index")
    sub.add_parser("topics")
    sub.add_parser("export")
    s = sub.add_parser("scores")
    s.add_argument("--dir", type=Path, nargs="+", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--model-revision", default="apertus-parltopics-8b")
    s.add_argument("--tag", default="parltopics8b")
    c = sub.add_parser("calibrate")
    c.add_argument("--dev", type=Path, required=True)
    c.add_argument("--scores", type=Path, required=True)
    c.add_argument("--topic", required=True)
    c.add_argument("--tag", default="parltopics8b")
    args = ap.parse_args()
    if args.cmd == "calibrate":
        print(json.dumps(calibrate(args.dev, args.scores, args.topic, args.tag), indent=2))
        return
    t0 = time.time()
    with connect() as con:
        if args.cmd == "init":
            init(con)
            result = "schema ready"
        elif args.cmd == "affairs":
            result = f"{load_affairs(con)} affairs"
        elif args.cmd == "embeddings":
            result = f"{load_embeddings(con, args.batch)} embeddings"
        elif args.cmd == "index":
            build_index(con)
            result = "hnsw index built"
        elif args.cmd == "topics":
            result = f"{load_topics(con)} topics"
        elif args.cmd == "export":
            result = f"{load_export(con)} stored decisions"
        else:
            result = json.dumps(load_scores(con, args.dir, args.run_id, args.model_revision, args.tag))
    print(f"{result} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
