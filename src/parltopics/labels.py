import argparse
import json
from pathlib import Path

import duckdb

SEED = 20261018
TEST_FROM_YEAR = 2024
DEV_SAMPLE = {"pos": 500, "neg": 1500}
TEST_SAMPLE = {"pos": 600, "neg": 2400}
MEDIA_TOPIC_ID = "34"


def build_digitalisation(con, raw: Path) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE pm AS
        SELECT DISTINCT CAST(openparldata_id AS BIGINT) AS affair_id
        FROM read_csv('{raw}/labels/politmonitor_digitalisierung.csv', all_varchar=true)
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE digit AS
        WITH pos AS (SELECT t.* FROM affair_text t JOIN pm USING (affair_id)),
        starts AS (SELECT body_key, greatest(DATE '2018-01-01', min(begin_date)) AS start FROM pos GROUP BY body_key),
        types AS (SELECT DISTINCT body_key, affair_type FROM pos),
        universe AS (
            SELECT t.affair_id, t.body_key, t.level, t.lang, t.affair_type, t.begin_date, t.year, t.text_source,
                   t.text_hash, t.title, t.text, t.affair_id IN (SELECT affair_id FROM pm) AS label
            FROM affair_text t
            JOIN starts s USING (body_key)
            WHERE t.begin_date >= s.start
              AND (t.affair_id IN (SELECT affair_id FROM pm)
                   OR (t.body_key, t.affair_type) IN (SELECT (body_key, affair_type) FROM types))
        )
        SELECT *, CASE WHEN year >= {TEST_FROM_YEAR} THEN 'test' ELSE 'dev' END AS split
        FROM universe
    """)
    con.execute(f"""
        DELETE FROM digit
        WHERE split = 'test'
          AND text_hash IN (SELECT text_hash FROM affair_text WHERE year < {TEST_FROM_YEAR})
    """)


def sample(con, split: str, sizes: dict, name: str) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE {name} AS
        WITH counts AS (
            SELECT label, count(*) AS n FROM digit WHERE split = '{split}' GROUP BY label
        ),
        ranked AS (
            SELECT d.*, row_number() OVER (PARTITION BY label ORDER BY hash(affair_id + {SEED})) AS rk
            FROM digit d WHERE split = '{split}'
        )
        SELECT r.* EXCLUDE (rk),
               c.n / least(c.n, CASE WHEN r.label THEN {sizes['pos']} ELSE {sizes['neg']} END) AS weight
        FROM ranked r JOIN counts c USING (label)
        WHERE rk <= CASE WHEN r.label THEN {sizes['pos']} ELSE {sizes['neg']} END
    """)


def build_curia(con, raw: Path) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE curia AS
        SELECT CAST(openparldata_id AS BIGINT) AS affair_id,
               list_transform(string_split(topic_ids, '|'), x -> trim(x)) AS topic_ids,
               TRY_CAST(begin_date AS DATE) AS begin_date,
               CASE WHEN year(TRY_CAST(begin_date AS DATE)) >= {TEST_FROM_YEAR} THEN 'test' ELSE 'train' END AS split
        FROM read_csv('{raw}/labels/che_affairs_keywords.csv', all_varchar=true)
        WHERE topic_ids IS NOT NULL AND trim(topic_ids) <> ''
    """)


def media_stand_in(con, since: str) -> dict:
    row = con.execute(f"""
        WITH fed AS (
            SELECT c.affair_id, list_contains(c.topic_ids, '{MEDIA_TOPIC_ID}') AS media,
                   c.affair_id IN (SELECT affair_id FROM pm) AS digital
            FROM curia c WHERE c.begin_date >= DATE '{since}'
        )
        SELECT count(*) FILTER (WHERE media AND digital) AS hit,
               count(*) FILTER (WHERE digital) AS digital,
               count(*) FILTER (WHERE media) AS media
        FROM fed
    """).fetchone()
    hit, digital, media = row
    return {"since": since, "hit": hit, "digital": digital, "media": media,
            "recall": hit / digital if digital else None, "precision": hit / media if media else None}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the frozen split, evaluation samples and the Curia Vista baseline.")
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()
    con = duckdb.connect()
    con.execute(f"CREATE TABLE affair_text AS SELECT * FROM '{args.data / 'affair_text.parquet'}'")
    build_digitalisation(con, args.raw)
    sample(con, "dev", DEV_SAMPLE, "dev_sample")
    sample(con, "test", TEST_SAMPLE, "test_sample")
    build_curia(con, args.raw)
    for table in ("digit", "dev_sample", "test_sample", "curia"):
        con.execute(f"COPY {table} TO '{args.data / (table + '.parquet')}' (FORMAT parquet)")
    report = {
        "digitalisation": con.execute("""
            SELECT split, label, count(*) AS n FROM digit GROUP BY ALL ORDER BY ALL
        """).fetchdf().to_dict("records"),
        "positives_outside_universe": con.execute("""
            SELECT count(*) FROM pm WHERE affair_id NOT IN (SELECT affair_id FROM digit)
        """).fetchone()[0],
        "media_stand_in_since_2018": media_stand_in(con, "2018-01-01"),
        "media_stand_in_test_years": media_stand_in(con, f"{TEST_FROM_YEAR}-01-01"),
        "curia": con.execute("SELECT split, count(*) AS n FROM curia GROUP BY ALL ORDER BY ALL").fetchdf().to_dict("records"),
    }
    (args.data / "labels_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
