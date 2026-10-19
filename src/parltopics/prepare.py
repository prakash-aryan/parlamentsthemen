import argparse
from pathlib import Path

import duckdb

SENTINEL = "[extraction_failed]"
BODY_CHARS = 3000
MAX_JSON_OBJECT = 400_000_000

FEDERAL_TEXT_ORDER = {
    "Eingereichter Text": 1,
    "Begründung": 2,
    "Antwort BR / Büro": 3,
}


def clean(expr: str) -> str:
    return (
        "trim(regexp_replace(regexp_replace(regexp_replace("
        f"{expr}, '<[^>]+>', ' ', 'g'), '&[a-zA-Z#0-9]+;', ' ', 'g'), '\\s+', ' ', 'g'))"
    )


def title_ok(col: str) -> str:
    return f"CASE WHEN {col} IS NULL OR trim({col}) = '' OR regexp_matches(trim({col}), '^\\[.*\\]$') THEN NULL ELSE {clean(col)} END"


def load_affairs(con, raw: Path) -> None:
    cols = ["id", "body_key", "number", "type_harmonized_en", "begin_date", "updated_at"]
    cols += [f"title_{l}" for l in ("de", "fr", "it", "rm")]
    spec = ", ".join(f"'{c}': 'VARCHAR'" for c in cols)
    con.execute(f"""
        CREATE TABLE affairs AS
        SELECT CAST(id AS BIGINT) AS affair_id, body_key, number,
               coalesce(type_harmonized_en, 'unknown') AS affair_type,
               TRY_CAST(begin_date AS TIMESTAMP)::DATE AS begin_date, updated_at,
               {title_ok('title_de')} AS title_de, {title_ok('title_fr')} AS title_fr,
               {title_ok('title_it')} AS title_it, {title_ok('title_rm')} AS title_rm
        FROM read_json('{raw}/export/affairs.ndjson.gz', format='newline_delimited', columns={{{spec}}})
    """)
    con.execute(f"""
        CREATE TABLE bodies AS
        SELECT body_key, type AS level, lower(lang) AS body_lang, name_de AS body_name, canton_key
        FROM read_json('{raw}/export/bodies.ndjson.gz', format='newline_delimited',
             columns={{'body_key': 'VARCHAR', 'type': 'VARCHAR', 'lang': 'VARCHAR', 'name_de': 'VARCHAR', 'canton_key': 'VARCHAR'}})
    """)


def load_federal_texts(con, raw: Path) -> None:
    order = " ".join(f"WHEN '{k}' THEN {v}" for k, v in FEDERAL_TEXT_ORDER.items())
    con.execute(f"""
        CREATE TABLE fed_parts AS
        SELECT CAST(openparldata_id AS BIGINT) AS affair_id,
               CASE type_de {order} END AS part,
               {clean('text_de')} AS text_de, {clean('text_fr')} AS text_fr, {clean('text_it')} AS text_it
        FROM read_json('{raw}/labels/che_affair_texts.ndjson.gz', format='newline_delimited',
             maximum_object_size={MAX_JSON_OBJECT},
             columns={{'openparldata_id': 'VARCHAR', 'type_de': 'VARCHAR', 'text_de': 'VARCHAR', 'text_fr': 'VARCHAR', 'text_it': 'VARCHAR'}})
        WHERE type_de IN ({", ".join(f"'{k}'" for k in FEDERAL_TEXT_ORDER)})
    """)
    con.execute("""
        CREATE TABLE fed AS
        SELECT affair_id,
               nullif(string_agg(text_de, '\n\n' ORDER BY part), '') AS body_de,
               nullif(string_agg(text_fr, '\n\n' ORDER BY part), '') AS body_fr,
               nullif(string_agg(text_it, '\n\n' ORDER BY part), '') AS body_it
        FROM fed_parts GROUP BY affair_id
    """)


def load_docs(con, raw: Path) -> None:
    con.execute("CREATE TABLE doc_best (affair_id BIGINT, body VARCHAR, body_len BIGINT)")
    con.execute("CREATE TABLE doc_stats (affair_id BIGINT, n_docs BIGINT, n_empty BIGINT)")
    spec = "{'affair_id': 'VARCHAR', 'text': 'VARCHAR'}"
    for path in sorted((raw / "export" / "docs").glob("docs_*.ndjson.gz")):
        src = f"read_json('{path}', format='newline_delimited', maximum_object_size={MAX_JSON_OBJECT}, columns={spec})"
        con.execute(f"""
            INSERT INTO doc_stats
            SELECT CAST(affair_id AS BIGINT), count(*),
                   count(*) FILTER (WHERE text IS NULL OR trim(text) = '' OR trim(text) = '{SENTINEL}')
            FROM {src} WHERE affair_id IS NOT NULL GROUP BY 1
        """)
        con.execute(f"""
            INSERT INTO doc_best
            SELECT affair_id, body, body_len FROM (
                SELECT CAST(affair_id AS BIGINT) AS affair_id,
                       left({clean('left(text, 20000)')}, {BODY_CHARS}) AS body,
                       length(text) AS body_len,
                       row_number() OVER (PARTITION BY affair_id ORDER BY length(text) DESC) AS rk
                FROM {src}
                WHERE affair_id IS NOT NULL AND text IS NOT NULL
                  AND trim(text) <> '' AND trim(text) <> '{SENTINEL}'
            ) WHERE rk = 1
        """)
        print(path.name, flush=True)


def assemble(con) -> None:
    con.execute(f"""
        CREATE TABLE affair_text AS
        WITH base AS (
            SELECT a.*, b.level, b.body_lang, b.body_name, b.canton_key,
                   f.body_de AS fed_de, f.body_fr AS fed_fr, f.body_it AS fed_it,
                   d.body AS doc_body, d.body_len AS doc_len,
                   coalesce(s.n_docs, 0) AS n_docs, coalesce(s.n_empty, 0) AS n_empty_docs
            FROM affairs a
            JOIN bodies b USING (body_key)
            LEFT JOIN fed f USING (affair_id)
            LEFT JOIN (SELECT affair_id, arg_max(body, body_len) AS body, max(body_len) AS body_len
                       FROM doc_best GROUP BY affair_id) d USING (affair_id)
            LEFT JOIN (SELECT affair_id, sum(n_docs) AS n_docs, sum(n_empty) AS n_empty
                       FROM doc_stats GROUP BY affair_id) s USING (affair_id)
            WHERE a.body_key <> 'LIE'
        ),
        lang AS (
            SELECT *,
                   CASE
                     WHEN body_key = 'CHE' AND title_de IS NOT NULL THEN 'de'
                     WHEN body_lang = 'de' AND title_de IS NOT NULL THEN 'de'
                     WHEN body_lang = 'fr' AND title_fr IS NOT NULL THEN 'fr'
                     WHEN body_lang = 'it' AND title_it IS NOT NULL THEN 'it'
                     WHEN title_de IS NOT NULL THEN 'de'
                     WHEN title_fr IS NOT NULL THEN 'fr'
                     WHEN title_it IS NOT NULL THEN 'it'
                     WHEN title_rm IS NOT NULL THEN 'rm'
                   END AS lang,
                   concat_ws(',', CASE WHEN title_de IS NOT NULL THEN 'de' END, CASE WHEN title_fr IS NOT NULL THEN 'fr' END,
                             CASE WHEN title_it IS NOT NULL THEN 'it' END, CASE WHEN title_rm IS NOT NULL THEN 'rm' END) AS title_langs
            FROM base
        ),
        txt AS (
            SELECT *,
                   CASE lang WHEN 'de' THEN title_de WHEN 'fr' THEN title_fr WHEN 'it' THEN title_it ELSE title_rm END AS title,
                   CASE
                     WHEN body_key = 'CHE' AND fed_de IS NOT NULL THEN left(fed_de, {BODY_CHARS})
                     WHEN doc_body IS NOT NULL THEN doc_body
                   END AS body,
                   CASE
                     WHEN body_key = 'CHE' AND fed_de IS NOT NULL THEN 'texts'
                     WHEN doc_body IS NOT NULL THEN 'docs'
                     ELSE 'title_only'
                   END AS text_source
            FROM lang
        )
        SELECT affair_id, body_key, body_name, canton_key, level, number, affair_type, begin_date,
               year(begin_date) AS year, updated_at, lang, title_langs, title, body, text_source,
               n_docs, n_empty_docs,
               (text_source = 'title_only' AND n_docs > 0 AND n_empty_docs = n_docs) AS scan_suspect,
               concat_ws('\n\n', title, body) AS text,
               md5(concat_ws('\n\n', title, body)) AS text_hash,
               title_de, title_fr, title_it, fed_de, fed_fr, fed_it
        FROM txt
        WHERE title IS NOT NULL
        QUALIFY number IS NULL
             OR row_number() OVER (PARTITION BY body_key, number
                                   ORDER BY length(coalesce(body, '')) DESC, updated_at DESC) = 1
    """)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build one cleaned text per affair from the OpenParlData export.")
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.out / "work.duckdb"))
    con.execute(f"SET threads={args.threads}")
    con.execute("SET preserve_insertion_order=false")
    for t in ("affairs", "bodies", "fed_parts", "fed", "doc_best", "doc_stats", "affair_text"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    load_affairs(con, args.raw)
    load_federal_texts(con, args.raw)
    load_docs(con, args.raw)
    assemble(con)
    con.execute(f"COPY affair_text TO '{args.out / 'affair_text.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    print(con.execute("""
        SELECT level, text_source, count(*) AS affairs, sum(scan_suspect::INT) AS scan_suspect
        FROM affair_text GROUP BY ALL ORDER BY ALL
    """).fetchdf().to_string(index=False))


if __name__ == "__main__":
    main()
