import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from parltopics.db import COLUMNS, EMB_MODEL, ROOT, build_index, connect, copy_frame, init, read_env, upsert_topics

AFFAIR_COLS = ["openparldata_id", "body_key", "body_name", "level", "number", "affair_type", "year", "begin_date", "lang", "title",
               "url_external", "text_hash", "state", "outcome", "title_only", "title_de", "title_fr", "title_it"]
CORRECTION_COLS = ["openparldata_id", "topic_code", "corrected_decision", "reason", "corrected_by", "created_at", "original_probability",
                   "original_decision", "model_revision", "card_hash"]
FLOOR = 3


def frame(con, sql: str, params=None) -> pd.DataFrame:
    with con.cursor() as cur:
        cur.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def counts(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.value_counts().sort_index().items()}


def stratified(pool: pd.DataFrame, k: int, seed: int) -> list[int]:
    if k <= 0 or pool.empty:
        return []
    picked = []
    for i, (_, g) in enumerate(pool.groupby(["body_key", "lang"], dropna=False)):
        quota = max(min(len(g), FLOOR), round(k * len(g) / len(pool)))
        picked += g.sample(min(len(g), quota), random_state=seed + i)["openparldata_id"].tolist()
    rest = pool[~pool["openparldata_id"].isin(picked)]
    if len(picked) < k and not rest.empty:
        picked += rest.sample(min(len(rest), k - len(picked)), random_state=seed)["openparldata_id"].tolist()
    return picked[:k] if len(picked) > k else picked


def select(con, n: int, include: list[int], older: float, seed: int) -> list[int]:
    include = sorted(set(include) | set(frame(con, "SELECT DISTINCT openparldata_id FROM affair_topic_corrections")["openparldata_id"]))
    pool = frame(con, "SELECT a.openparldata_id, a.body_key, a.lang, coalesce(a.year, 0) >= 2024 AS recent FROM affairs a "
                      "WHERE EXISTS (SELECT 1 FROM affair_topics t WHERE t.openparldata_id = a.openparldata_id)")
    pool = pool[~pool["openparldata_id"].isin(include)]
    k = max(n - len(include), 0)
    k_old = round(k * older)
    ids = stratified(pool[~pool["recent"]], k_old, seed) + stratified(pool[pool["recent"]], k - k_old, seed)
    return sorted(set(include) | set(ids))


def export(out: Path, n: int, include: list[int], older: float, seed: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.read_only = True
        ids = select(con, n, include, older, seed)
        affairs = frame(con, f"SELECT {', '.join(AFFAIR_COLS)} FROM affairs WHERE openparldata_id = ANY(%s) ORDER BY openparldata_id", [ids])
        decisions = frame(con, f"SELECT {', '.join(COLUMNS)} FROM affair_topics_current WHERE openparldata_id = ANY(%s) "
                               f"ORDER BY openparldata_id, topic_code", [ids])
        topics = frame(con, "SELECT * FROM topics ORDER BY topic_code")
        corrections = frame(con, f"SELECT {', '.join(CORRECTION_COLS)} FROM affair_topic_corrections WHERE openparldata_id = ANY(%s) "
                                 f"ORDER BY created_at", [ids])
    ids = affairs["openparldata_id"].tolist()
    affairs["year"] = affairs["year"].astype("Int64")
    affairs.to_parquet(out / "affairs.parquet", index=False, compression="zstd")
    texts = duckdb.execute(f"SELECT affair_id AS openparldata_id, text, text_source, md5(text) AS text_hash "
                           f"FROM read_parquet('{ROOT / 'data/affair_text.parquet'}') "
                           f"WHERE affair_id IN (SELECT unnest(?)) AND text IS NOT NULL ORDER BY affair_id", [ids]).df()
    texts.to_parquet(out / "affair_texts.parquet", index=False, compression="zstd")
    tag = EMB_MODEL.split("/")[-1]
    all_ids = pd.read_parquet(ROOT / "runs/emb" / f"embeddings_{tag}_ids.parquet")["affair_id"].to_numpy()
    row = pd.Series(np.arange(len(all_ids)), index=all_ids)
    have = [a for a in ids if a in row.index]
    vectors = np.load(ROOT / "runs/emb" / f"embeddings_{tag}.npy", mmap_mode="r")[row.loc[have].to_numpy()]
    np.savez_compressed(out / "embeddings.npz", ids=np.asarray(have, dtype=np.int64), vectors=np.asarray(vectors, dtype=np.float16))
    decisions.to_parquet(out / "affair_topics.parquet", index=False, compression="zstd")
    topics.to_parquet(out / "topics.parquet", index=False, compression="zstd")
    corrections.to_parquet(out / "corrections.parquet", index=False, compression="zstd")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": seed, "affairs": len(affairs),
                "texts": len(texts), "embeddings": len(have), "embedding_model": EMB_MODEL, "decisions": len(decisions),
                "topics": len(topics), "corrections": len(corrections), "included": sorted(include),
                "by_level": counts(affairs["level"]), "by_lang": counts(affairs["lang"]), "by_year": counts(affairs["year"]),
                "decisions_by_model": counts(decisions["model_revision"]), "decisions_by_run": counts(decisions["run_id"])}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {k: manifest[k] for k in ("affairs", "texts", "embeddings", "decisions", "topics", "corrections")}


def upsert(con, table: str, df: pd.DataFrame, key: str) -> int:
    cols = list(df.columns)
    con.execute(f"CREATE TEMP TABLE {table}_in (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    copy_frame(con, f"{table}_in", df)
    con.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM {table}_in ON CONFLICT ({key}) DO UPDATE SET "
                + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key))
    return len(df)


def load_embeddings(con, path: Path, hashes: pd.Series, batch: int = 2000) -> int:
    data = np.load(path)
    ids, vectors = data["ids"], data["vectors"]
    con.execute("DROP INDEX IF EXISTS affair_embeddings_hnsw")
    con.execute("DELETE FROM affair_embeddings WHERE model = %s AND openparldata_id = ANY(%s)", [EMB_MODEL, ids.tolist()])
    with con.cursor() as cur, cur.copy("COPY affair_embeddings (openparldata_id, model, text_hash, embedding) FROM STDIN") as copy:
        for start in range(0, len(ids), batch):
            block = np.char.mod("%.5g", vectors[start:start + batch].astype(np.float32))
            copy.write("".join(f"{int(a)}\t{EMB_MODEL}\t{hashes.get(int(a)) or ''}\t[{','.join(v)}]\n"
                               for a, v in zip(ids[start:start + batch], block)))
    build_index(con)
    return len(ids)


def load_corrections(con, df: pd.DataFrame) -> int:
    cols = ", ".join(CORRECTION_COLS)
    con.execute(f"CREATE TEMP TABLE corrections_in ON COMMIT DROP AS SELECT {cols} FROM affair_topic_corrections WITH NO DATA")
    copy_frame(con, "corrections_in", df[CORRECTION_COLS])
    cur = con.execute(f"INSERT INTO affair_topic_corrections ({cols}) SELECT {cols} FROM corrections_in i WHERE NOT EXISTS "
                      f"(SELECT 1 FROM affair_topic_corrections c WHERE c.openparldata_id = i.openparldata_id "
                      f"AND c.topic_code = i.topic_code AND c.created_at = i.created_at)")
    return cur.rowcount


def load(src: Path) -> dict:
    affairs = pd.read_parquet(src / "affairs.parquet")
    affairs["year"] = affairs["year"].astype("Int64")
    with connect() as con:
        init(con)
        out = {"affairs": upsert(con, "affairs", affairs[AFFAIR_COLS], "openparldata_id"),
               "texts": upsert(con, "affair_texts", pd.read_parquet(src / "affair_texts.parquet"), "openparldata_id"),
               "embeddings": load_embeddings(con, src / "embeddings.npz", affairs.set_index("openparldata_id")["text_hash"]),
               "topics": upsert(con, "topics", pd.read_parquet(src / "topics.parquet"), "topic_code"),
               "decisions": upsert_topics(con, pd.read_parquet(src / "affair_topics.parquet")),
               "corrections": load_corrections(con, pd.read_parquet(src / "corrections.parquet"))}
    return out


def main() -> None:
    read_env()
    ap = argparse.ArgumentParser(description="Demo bundle: a subset of affairs with texts, embeddings and stored topic decisions.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("export")
    x.add_argument("--out", type=Path, default=ROOT / "data/demo")
    x.add_argument("--n", type=int, default=5000)
    x.add_argument("--include", type=Path, help="JSON list of affair ids that must be in the bundle")
    x.add_argument("--older", type=float, default=0.1)
    x.add_argument("--seed", type=int, default=20261018)
    ld = sub.add_parser("load")
    ld.add_argument("--dir", type=Path, default=ROOT / "data/demo")
    args = ap.parse_args()
    t0 = time.time()
    if args.cmd == "export":
        include = [int(i) for i in json.loads(args.include.read_text())] if args.include else []
        result = export(args.out, args.n, include, args.older, args.seed)
    else:
        result = load(args.dir)
    print(f"{json.dumps(result)} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
