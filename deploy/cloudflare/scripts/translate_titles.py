import json
import os
import sys
from pathlib import Path

from vllm import LLM, SamplingParams

R = Path(os.environ.get("TITLES_DIR", "runs/titles_en"))
LANG = {"de": "German", "fr": "French", "it": "Italian", "rm": "Romansh"}
SYSTEM = ("You translate titles of Swiss parliamentary affairs into plain English. Keep the exact meaning and the style of a title. "
          "Keep proper names, place names, party names and official abbreviations. Answer with the English title only.")


def main():
    shard, nshards, limit = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else None
    out = R / f"en_{shard:02d}.jsonl"
    done = {json.loads(l)["id"] for l in out.open()} if out.exists() else set()
    rows = [json.loads(l) for n, l in enumerate((R / "titles.jsonl").open()) if n % nshards == shard]
    rows = [r for r in rows if r["id"] not in done][:limit]
    llm = LLM(os.environ["APERTUS_MODEL"], dtype="bfloat16", max_model_len=2048, gpu_memory_utilization=0.9, generation_config="vllm")
    sp = SamplingParams(temperature=0, max_tokens=160)
    for i in range(0, len(rows), 5000):
        part = rows[i:i + 5000]
        msgs = [[{"role": "user", "content": f"{SYSTEM}\n\nTranslate this {LANG.get(r['l'], 'Swiss')} title into English:\n{r['t']}"}] for r in part]
        res = llm.chat(msgs, sp, use_tqdm=False)
        with out.open("a") as f:
            for r, o in zip(part, res):
                f.write(json.dumps({"id": r["id"], "en": o.outputs[0].text.strip(), "fin": o.outputs[0].finish_reason}, ensure_ascii=False) + "\n")
        print(f"{i + len(part)}/{len(rows)}", flush=True)
    print("SHARD_DONE", shard, flush=True)


if __name__ == "__main__":
    main()
