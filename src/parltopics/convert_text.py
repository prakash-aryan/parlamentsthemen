import argparse
import json
import shutil
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file

TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "chat_template.jinja")


def convert(src: Path, out: Path, shard_bytes: int) -> None:
    cfg = json.loads((src / "config.json").read_text())
    tc = cfg["text_config"]
    if tc.get("post_norm") or not tc.get("qk_norm", True):
        raise ValueError("the text decoder differs from ApertusForCausalLM (post_norm or missing qk_norm)")
    vocab = tc["output_vocab_size"]
    text_cfg = {
        "architectures": ["ApertusForCausalLM"],
        "model_type": "apertus",
        "vocab_size": vocab,
        "hidden_size": tc["hidden_size"],
        "intermediate_size": tc["intermediate_size"],
        "num_hidden_layers": tc["num_hidden_layers"],
        "num_attention_heads": tc["num_attention_heads"],
        "num_key_value_heads": tc["num_key_value_heads"],
        "hidden_act": tc["hidden_act"],
        "max_position_embeddings": tc["max_position_embeddings"],
        "initializer_range": tc["initializer_range"],
        "rms_norm_eps": tc["rms_norm_eps"],
        "rope_parameters": tc["rope_parameters"],
        "attention_bias": tc["attention_bias"],
        "attention_dropout": tc["attention_dropout"],
        "pad_token_id": tc["pad_token_id"],
        "bos_token_id": tc["bos_token_id"],
        "eos_token_id": tc["eos_token_id"],
        "tie_word_embeddings": False,
        "dtype": "bfloat16",
    }
    index = json.loads((src / "model.safetensors.index.json").read_text())["weight_map"]
    keep = {k: v for k, v in index.items() if k.startswith("model.language_model.") or k == "lm_head.weight"}
    out.mkdir(parents=True, exist_ok=True)
    shards, current, size, weight_map = [], {}, 0, {}
    for name, file in sorted(keep.items(), key=lambda kv: kv[1]):
        with safe_open(src / file, framework="pt") as f:
            t = f.get_tensor(name)
        new = name.replace("model.language_model.", "model.", 1)
        if new == "model.embed_tokens.weight":
            t = t[:vocab].clone()
        if new == "lm_head.weight" and t.shape[0] != vocab:
            raise ValueError(f"lm_head has {t.shape[0]} rows, expected {vocab}")
        current[new] = t.contiguous()
        size += t.numel() * t.element_size()
        if size >= shard_bytes:
            shards.append(current)
            current, size = {}, 0
    if current:
        shards.append(current)
    total = 0
    for i, shard in enumerate(shards, 1):
        fname = f"model-{i:05d}-of-{len(shards):05d}.safetensors"
        save_file(shard, out / fname, metadata={"format": "pt"})
        for k, t in shard.items():
            weight_map[k] = fname
            total += t.numel() * t.element_size()
    (out / "model.safetensors.index.json").write_text(json.dumps({"metadata": {"total_size": total}, "weight_map": weight_map}, indent=2))
    (out / "config.json").write_text(json.dumps(text_cfg, indent=2))
    for f in TOKENIZER_FILES:
        if (src / f).exists():
            shutil.copy(src / f, out / f)
    print(f"{len(weight_map)} tensors in {len(shards)} shards, {total / 1e9:.1f} GB, vocab {vocab}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract the text decoder of Apertus 1.5 as an ApertusForCausalLM checkpoint.")
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--shard-gb", type=float, default=5.0)
    args = ap.parse_args()
    convert(args.src, args.out, int(args.shard_gb * 1e9))


if __name__ == "__main__":
    main()
