import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser(description="Embed every affair for similarity search, duplicate checks and topic shortlists.")
    ap.add_argument("--data", type=Path, required=True, help="directory with affair_text.parquet")
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--chunk", type=int, default=20000)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--limit", type=int, help="embed only the longest N texts of the shard")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--merge", action="store_true", help="join the shard files into one matrix")
    args = ap.parse_args()
    tag, out_dir = args.model.split("/")[-1], args.out or args.data
    if args.merge:
        parts = [(np.load(out_dir / f"embeddings_{tag}_shard{i}of{args.shards}.npy"),
                  pd.read_parquet(out_dir / f"embeddings_{tag}_shard{i}of{args.shards}_ids.parquet")) for i in range(args.shards)]
        np.save(out_dir / f"embeddings_{tag}.npy", np.concatenate([e for e, _ in parts]))
        pd.concat([i for _, i in parts], ignore_index=True).to_parquet(out_dir / f"embeddings_{tag}_ids.parquet", index=False)
        print(f"merged {sum(len(e) for e, _ in parts)} rows")
        return
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(args.model, device="cuda", model_kwargs={"torch_dtype": "bfloat16"})
    model.max_seq_length = args.max_tokens
    df = pd.read_parquet(args.data / "affair_text.parquet", columns=["affair_id", "text"])
    df["n"] = df["text"].str.len()
    df = df.sort_values("n", ascending=False).iloc[args.shard::args.shards]
    df = (df.head(args.limit) if args.limit else df).reset_index(drop=True)
    out = np.zeros((len(df), model.get_sentence_embedding_dimension()), dtype=np.float16)
    t0 = time.monotonic()
    for start in range(0, len(df), args.chunk):
        texts = df["text"].iloc[start:start + args.chunk].tolist()
        out[start:start + len(texts)] = model.encode_document(texts, batch_size=args.batch_size, normalize_embeddings=True,
                                                     convert_to_numpy=True).astype(np.float16)
        print(f"{start + len(texts)}/{len(df)} after {time.monotonic() - t0:.0f}s", flush=True)
    suffix = f"_shard{args.shard}of{args.shards}" if args.shards > 1 else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / f"embeddings_{tag}{suffix}.npy", out)
    df[["affair_id"]].to_parquet(out_dir / f"embeddings_{tag}{suffix}_ids.parquet", index=False)
    print(f"saved {out.shape} in {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
