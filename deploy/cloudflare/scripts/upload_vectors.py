import os
import sys
import time

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from pymilvus import DataType, MilvusClient

COLL = "affairs"
MODEL = "microsoft/harrier-oss-v1-0.6b"
BATCH = 1000




def ensure(mc):
    if mc.has_collection(COLL):
        return
    s = MilvusClient.create_schema(auto_id=False)
    s.add_field("id", DataType.INT64, is_primary=True)
    s.add_field("vector", DataType.FLOAT_VECTOR, dim=1024)
    s.add_field("body_key", DataType.VARCHAR, max_length=16)
    s.add_field("level", DataType.VARCHAR, max_length=16)
    s.add_field("year", DataType.INT16)
    s.add_field("topics", DataType.ARRAY, element_type=DataType.VARCHAR, max_capacity=32, max_length=48)
    ix = mc.prepare_index_params()
    ix.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
    mc.create_collection(COLL, schema=s, index_params=ix)


SQL = """
WITH yes AS (
  SELECT openparldata_id, array_agg(topic_code ORDER BY topic_code) AS topics
  FROM affair_topics_current WHERE decision = 'yes' GROUP BY 1
)
SELECT e.openparldata_id, e.embedding, coalesce(a.body_key, ''), coalesce(a.level, ''), coalesce(a.year, 0),
       coalesce(y.topics, '{{}}')
FROM affair_embeddings e
JOIN affairs a ON a.openparldata_id = e.openparldata_id
LEFT JOIN yes y ON y.openparldata_id = e.openparldata_id
WHERE e.model = %s
ORDER BY e.openparldata_id {extra}
"""


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    mc = MilvusClient(uri=os.environ["ZILLIZ_URL"], token=os.environ["ZILLIZ_TOKEN"])
    ensure(mc)
    t0, n = time.monotonic(), 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        register_vector(con)
        with con.cursor(name="emb") as cur:
            cur.itersize = BATCH
            cur.execute(SQL.format(extra=f"LIMIT {limit}" if limit else ""), [MODEL])
            rows = []
            for r in cur:
                v = np.asarray(r[1].to_numpy() if hasattr(r[1], "to_numpy") else r[1], dtype=np.float32)
                rows.append({"id": int(r[0]), "vector": v.tolist(), "body_key": r[2], "level": r[3],
                             "year": int(r[4]), "topics": list(r[5])})
                if len(rows) == BATCH:
                    mc.upsert(COLL, rows)
                    n += len(rows)
                    rows = []
                    if n % 20000 == 0:
                        print(f"{n} uploaded, {n / (time.monotonic() - t0):.0f}/s", flush=True)
            if rows:
                mc.upsert(COLL, rows)
                n += len(rows)
    print(f"UPLOAD_DONE {n} vectors in {time.monotonic() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
