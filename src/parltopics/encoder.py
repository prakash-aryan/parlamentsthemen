import argparse
import csv
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

SEED = 20261018


def area_ids(names_csv: Path) -> list[str]:
    with names_csv.open(encoding="utf-8") as f:
        return sorted(r["topic_id"] for r in csv.DictReader(f))


def curia_frames(data: Path, areas: list[str], n_train: int, limit: int | None):
    exclude = set()
    for s in ("dev_sample", "test_sample", "curia_dev_sample", "curia_test_sample"):
        exclude |= set(pd.read_parquet(data / f"{s}.parquet", columns=["affair_id"])["affair_id"])
    text = pd.read_parquet(data / "affair_text.parquet", columns=["affair_id", "text"])
    curia = pd.read_parquet(data / "curia.parquet")
    train = curia[(curia.split == "train") & ~curia.affair_id.isin(exclude)].merge(text, on="affair_id")
    train = train.sample(n=min(n_train, len(train)), random_state=SEED)
    frames = {"train": train}
    for s in ("dev", "test"):
        frames[s] = pd.read_parquet(data / f"curia_{s}_sample.parquet", columns=["affair_id", "text", "topic_ids"])
    for k, f in frames.items():
        f = f.sort_values("text", key=lambda t: -t.str.len()) if limit else f
        f = f.head(limit) if limit else f
        y = np.array([[a in list(t) for a in areas] for t in f.topic_ids], dtype=np.float32)
        frames[k] = (f.reset_index(drop=True), y, None)
    return frames


def digit_frames(data: Path, limit: int | None):
    frames = {}
    tr = pd.read_parquet(data / "probe_train_digit.parquet", columns=["affair_id", "text", "label"])
    frames["train"] = tr
    for s in ("dev", "test"):
        frames[s] = pd.read_parquet(data / f"{s}_sample.parquet", columns=["affair_id", "text", "label", "weight"])
    for k, f in frames.items():
        f = f.sort_values("text", key=lambda t: -t.str.len()).head(limit) if limit else f
        f = f.reset_index(drop=True)
        frames[k] = (f, f["label"].to_numpy(np.float32)[:, None], f["weight"].to_numpy(float) if "weight" in f else None)
    return frames


def macro_ap(y: np.ndarray, s: np.ndarray, w: np.ndarray | None) -> float:
    aps = [average_precision_score(y[:, j], s[:, j], sample_weight=w) for j in range(y.shape[1]) if 0 < y[:, j].sum() < len(y)]
    return float(np.mean(aps)) if aps else float("nan")


def run(task: str, model_dir: str, data: Path, out: Path, epochs: int, n_train: int, batch: int, lr: float, max_len: int,
        limit: int | None, tag: str, remote_code: bool) -> None:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.manual_seed(SEED)
    areas = area_ids(Path(__file__).resolve().parents[2] / "cards" / "curia" / "names.csv") if task == "curia" else ["digitalisation"]
    frames = curia_frames(data, areas, n_train, limit) if task == "curia" else digit_frames(data, limit)
    from transformers import AutoConfig

    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=remote_code)
    config = AutoConfig.from_pretrained(model_dir, trust_remote_code=remote_code, num_labels=len(areas),
                                        problem_type="multi_label_classification")
    rope = getattr(config, "rope_scaling", None) or {}
    if rope.get("rope_type") == "default" and "rope_theta" in rope:
        # transformers 5 dropped the "default" rope type; linear with factor 1 is the same rotation
        config.rope_theta = float(rope["rope_theta"])
        config.rope_scaling = {"rope_type": "linear", "factor": 1.0, "rope_theta": float(rope["rope_theta"])}
    model = AutoModelForSequenceClassification.from_pretrained(model_dir, config=config, trust_remote_code=remote_code).to("cuda")
    train_df, train_y, _ = frames["train"]
    steps = epochs * math.ceil(len(train_df) / batch)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
    warm = max(1, int(0.06 * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda i: min((i + 1) / warm, max(0.0, (steps - i) / max(1, steps - warm))))
    lossf = torch.nn.BCEWithLogitsLoss()

    def score(df):
        model.eval()
        outs = []
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            for i in range(0, len(df), 64):
                enc = tok(df.text.iloc[i:i + 64].tolist(), truncation=True, max_length=max_len, padding=True, return_tensors="pt").to("cuda")
                outs.append(model(**enc).logits.float().cpu().numpy())
        model.train()
        return np.concatenate(outs)

    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    best, log, t0, step = -1.0, [], time.monotonic(), 0
    model.train()
    for ep in range(epochs):
        order = rng.permutation(len(train_df))
        for i in range(0, len(order), batch):
            idx = order[i:i + batch]
            enc = tok(train_df.text.iloc[idx].tolist(), truncation=True, max_length=max_len, padding=True, return_tensors="pt").to("cuda")
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(**enc).logits
            loss = lossf(logits.float(), torch.from_numpy(train_y[idx]).to("cuda"))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            step += 1
            if step % 50 == 0:
                print(f"epoch {ep} step {step}/{steps} loss {loss.item():.4f} {time.monotonic() - t0:.0f}s", flush=True)
        dev_df, dev_y, dev_w = frames["dev"]
        dev_s = score(dev_df)
        m = macro_ap(dev_y, dev_s, dev_w)
        log.append({"epoch": ep, "dev_macro_ap": round(m, 4), "seconds": round(time.monotonic() - t0)})
        print(json.dumps(log[-1]), flush=True)
        if m > best:
            best = m
            test_df, _, _ = frames["test"]
            test_s = score(test_df)
            for split, df, s in (("dev", dev_df, dev_s), ("test", test_df, test_s)):
                for j, a in enumerate(areas):
                    name = f"{tag}_{split}_curia_{a}" if task == "curia" else f"{tag}_{split}_digitalisation"
                    pd.DataFrame({"affair_id": df.affair_id, "score": s[:, j]}).to_parquet(out / f"{name}.parquet", index=False)
    (out / f"{tag}_{task}_log.json").write_text(json.dumps({"model": model_dir, "max_len": max_len, "n_train": len(train_df), "epochs": log}, indent=2))
    print(f"ENCODER_DONE {tag} {task} best dev macro AP {best:.4f}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fine-tune an encoder per scheme (multi-label), as in the 2023 POLITmonitor study.")
    ap.add_argument("--task", choices=["curia", "digit"], required=True)
    ap.add_argument("--model", default="joelito/legal-xlm-roberta-large")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--n-train", type=int, default=8000)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--limit", type=int, help="smoke test on the longest N texts of each split")
    ap.add_argument("--tag", default="xlmr", help="prefix of the score files")
    ap.add_argument("--trust-remote-code", action="store_true", help="only for models whose code has been reviewed")
    args = ap.parse_args()
    run(args.task, args.model, args.data, args.out, args.epochs, args.n_train, args.batch, args.lr, args.max_len, args.limit,
        args.tag, args.trust_remote_code)


if __name__ == "__main__":
    main()
