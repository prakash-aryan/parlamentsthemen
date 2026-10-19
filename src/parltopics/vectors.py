import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

DDL = """CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS affair_embeddings (
    openparldata_id   BIGINT        NOT NULL,
    model             TEXT          NOT NULL,
    text_hash         TEXT          NOT NULL,
    embedding         halfvec({dim}) NOT NULL,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (openparldata_id, model)
);
"""
INDEX = "CREATE INDEX IF NOT EXISTS affair_embeddings_hnsw ON affair_embeddings USING hnsw (embedding halfvec_cosine_ops);\n"

SIMILAR_SQL = """SELECT e.openparldata_id, 1 - (e.embedding <=> q.embedding) AS similarity
FROM affair_embeddings e, (SELECT embedding FROM affair_embeddings WHERE openparldata_id = %(id)s AND model = %(model)s) q
WHERE e.model = %(model)s AND e.openparldata_id <> %(id)s
ORDER BY e.embedding <=> q.embedding
LIMIT %(limit)s"""


class Index:
    def __init__(self, emb_dir: Path, tag: str):
        self.vectors = np.load(emb_dir / f"embeddings_{tag}.npy").astype(np.float32)
        ids = pd.read_parquet(emb_dir / f"embeddings_{tag}_ids.parquet")["affair_id"].to_numpy()
        self.row = {int(a): i for i, a in enumerate(ids)}
        self.ids = ids
        meta = emb_dir / "affair_meta.parquet"
        self.meta = pd.read_parquet(meta).set_index("affair_id") if meta.exists() else None

    def describe(self, affair_id: int, similarity: float | None = None) -> dict:
        row = {"openparldata_id": int(affair_id)}
        if similarity is not None:
            row["similarity"] = round(float(similarity), 4)
        if self.meta is not None and affair_id in self.meta.index:
            m = self.meta.loc[affair_id]
            row.update({k: (None if pd.isna(v) else (int(v) if isinstance(v, (np.integer,)) else v)) for k, v in m.items() if k != "text_hash"})
        return row

    def rank(self, q: np.ndarray, limit: int, allowed: np.ndarray | None = None, exclude: int | None = None) -> list[dict]:
        sims = self.vectors @ q.astype(np.float32)
        if allowed is not None:
            sims = np.where(allowed, sims, -np.inf)
        if exclude is not None:
            sims[exclude] = -np.inf
        top = np.argpartition(-sims, limit)[:limit]
        top = top[np.argsort(-sims[top])]
        return [self.describe(int(self.ids[j]), sims[j]) for j in top if np.isfinite(sims[j])]

    def similar(self, affair_id: int, limit: int = 8) -> list[dict]:
        i = self.row.get(int(affair_id))
        return [] if i is None else self.rank(self.vectors[i], limit, exclude=i)

    def mask(self, level: str | None = None, year_from: int | None = None, year_to: int | None = None) -> np.ndarray | None:
        if self.meta is None or not (level or year_from or year_to):
            return None
        m = self.meta.reindex(self.ids)
        ok = np.ones(len(self.ids), dtype=bool)
        if level:
            ok &= (m["level"] == level).to_numpy()
        if year_from:
            ok &= (m["year"] >= year_from).fillna(False).to_numpy()
        if year_to:
            ok &= (m["year"] <= year_to).fillna(False).to_numpy()
        return ok


def similar_pg(database_url: str, model: str, affair_id: int, limit: int) -> list[dict]:
    import psycopg

    with psycopg.connect(database_url) as con:
        rows = con.execute(SIMILAR_SQL, {"id": affair_id, "model": model, "limit": limit}).fetchall()
    return [{"openparldata_id": int(a), "similarity": round(float(s), 4)} for a, s in rows]


def load_pg(database_url: str, emb_dir: Path, tag: str, model: str, batch: int) -> None:
    import psycopg

    vectors = np.load(emb_dir / f"embeddings_{tag}.npy", mmap_mode="r")
    ids = pd.read_parquet(emb_dir / f"embeddings_{tag}_ids.parquet")["affair_id"].to_numpy()
    hashes = pd.read_parquet(emb_dir / "affair_meta.parquet", columns=["affair_id", "text_hash"]).set_index("affair_id")["text_hash"]
    with psycopg.connect(database_url) as con:
        con.execute(DDL.format(dim=vectors.shape[1]))
        with con.cursor() as cur, cur.copy("COPY affair_embeddings (openparldata_id, model, text_hash, embedding) FROM STDIN") as copy:
            for start in range(0, len(ids), batch):
                block = np.asarray(vectors[start:start + batch], dtype=np.float32)
                for a, v in zip(ids[start:start + batch], block):
                    copy.write_row((int(a), model, hashes.get(int(a), ""), "[" + ",".join(f"{x:.5g}" for x in v) + "]"))
                print(f"{min(start + batch, len(ids))}/{len(ids)}", flush=True)
        con.execute(INDEX)


def main() -> None:
    ap = argparse.ArgumentParser(description="Affair embeddings in PostgreSQL with pgvector, or searched in memory.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("ddl")
    d.add_argument("--dim", type=int, default=1024)
    d.add_argument("--out", type=Path, required=True)
    m = sub.add_parser("meta")
    m.add_argument("--data", type=Path, required=True, help="directory with affair_text.parquet")
    m.add_argument("--out", type=Path, required=True)
    for name in ("load", "similar"):
        p = sub.add_parser(name)
        p.add_argument("--emb-dir", type=Path, required=True)
        p.add_argument("--model", default="microsoft/harrier-oss-v1-0.6b")
        p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    sub.choices["load"].add_argument("--batch", type=int, default=5000)
    sub.choices["similar"].add_argument("--affair-id", type=int, required=True)
    sub.choices["similar"].add_argument("--limit", type=int, default=8)
    args = ap.parse_args()
    if args.cmd == "ddl":
        args.out.write_text(DDL.format(dim=args.dim) + INDEX)
    elif args.cmd == "meta":
        cols = ["affair_id", "body_key", "body_name", "level", "number", "affair_type", "year", "lang", "title", "text_hash"]
        t = pd.read_parquet(args.data / "affair_text.parquet", columns=cols)
        t.assign(title=t["title"].str.slice(0, 300)).to_parquet(args.out / "affair_meta.parquet", index=False)
        print(f"{len(t)} affairs")
    elif args.cmd == "load":
        load_pg(args.database_url, args.emb_dir, args.model.split("/")[-1], args.model, args.batch)
    elif args.database_url:
        print(similar_pg(args.database_url, args.model, args.affair_id, args.limit))
    else:
        print(Index(args.emb_dir, args.model.split("/")[-1]).similar(args.affair_id, args.limit))


if __name__ == "__main__":
    main()
