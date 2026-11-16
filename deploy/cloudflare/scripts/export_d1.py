import json
import os
from pathlib import Path

import duckdb
import psycopg

from parltopics.db import read_env
from parltopics.explain import normalise

ROOT = Path(os.environ.get("PARLTOPICS_ROOT", Path(__file__).resolve().parents[3]))
OUT = Path(os.environ.get("D1_OUT", ROOT / "runs" / "d1"))
CHUNK = 20000
read_env(ROOT / ".env")

SCHEMA = """
DROP TABLE IF EXISTS affairs;
DROP TABLE IF EXISTS yes;
DROP TABLE IF EXISTS meta;
CREATE TABLE affairs (id INTEGER PRIMARY KEY, body_key TEXT, body_name TEXT, level TEXT, number TEXT, affair_type TEXT, year INTEGER,
  begin_date TEXT, lang TEXT, title TEXT, outcome TEXT, title_only INTEGER, title_de TEXT, title_fr TEXT, title_it TEXT, state TEXT,
  url_external TEXT, excerpt TEXT, text_source TEXT, title_en TEXT);
CREATE TABLE yes (topic TEXT NOT NULL, id INTEGER NOT NULL, probability REAL, confidence TEXT, threshold REAL, corrected INTEGER,
  original_decision TEXT, year INTEGER, level TEXT, body_key TEXT, PRIMARY KEY (topic, id)) WITHOUT ROWID;
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS qcache (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, n INTEGER NOT NULL);
"""
INDEXES = """
CREATE INDEX yes_browse ON yes (topic, year DESC, probability DESC);
CREATE INDEX yes_id ON yes (id);
"""


def lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def write(name, table, cols, rows):
    n, part, buf = 0, 0, []
    for r in rows:
        buf.append(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(lit(x) for x in r)});")
        if len(buf) == CHUNK:
            (OUT / f"{name}_{part:03d}.sql").write_text("\n".join(buf) + "\n")
            part, buf = part + 1, []
        n += 1
    if buf:
        (OUT / f"{name}_{part:03d}.sql").write_text("\n".join(buf) + "\n")
    print(name, n, "rows", flush=True)


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "000_schema.sql").write_text(SCHEMA)
    (OUT / "zzz_indexes.sql").write_text(INDEXES)
    with duckdb.connect() as d:
        texts = {int(a): (t, s) for a, t, s in d.execute(
            f"SELECT affair_id, left(text, 4000), text_source FROM read_parquet('{ROOT}/data/affair_text.parquet')").fetchall()}
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        for i, t, s in con.execute("SELECT openparldata_id, left(text, 4000), text_source FROM affair_texts WHERE text IS NOT NULL"):
            texts[int(i)] = (t, s)
        cols = ["id", "body_key", "body_name", "level", "number", "affair_type", "year", "begin_date", "lang", "title", "outcome",
                "title_only", "title_de", "title_fr", "title_it", "state", "url_external"]
        rows = con.execute("SELECT openparldata_id, body_key, body_name, level, number, affair_type, year, begin_date::text, lang, title, "
                           "outcome, title_only, title_de, title_fr, title_it, state, url_external FROM affairs ORDER BY 1").fetchall()

        def affairs():
            for r in rows:
                t = texts.get(int(r[0]))
                yield list(r) + ([normalise(t[0])[:1800], t[1]] if t and t[0] else [None, None])

        write("affairs", "affairs", cols + ["excerpt", "text_source"], affairs())
        ycols = ["topic", "id", "probability", "confidence", "threshold", "corrected", "original_decision", "year", "level", "body_key"]
        yrows = con.execute("SELECT t.topic_code, t.openparldata_id, t.probability, t.confidence, t.threshold, t.corrected, t.original_decision, "
                            "a.year, a.level, a.body_key FROM affair_topics_current t JOIN affairs a USING (openparldata_id) "
                            "WHERE t.decision = 'yes' ORDER BY 1, 2").fetchall()
        write("yes", "yes", ycols, yrows)
        stored = dict(con.execute("SELECT topic_code, count(*) FROM affair_topics GROUP BY 1").fetchall())
    v = json.dumps(stored).replace("'", "''")
    (OUT / "zzz_meta.sql").write_text(f"INSERT OR REPLACE INTO meta (k, v) VALUES ('stored', '{v}');\n")
    print("EXPORT_DONE", flush=True)


if __name__ == "__main__":
    main()
