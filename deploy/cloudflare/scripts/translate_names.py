import json
import os
from pathlib import Path

from vllm import LLM, SamplingParams

R = Path(os.environ.get("NAMES_DIR", "."))
LANG = {"fr": "French", "it": "Italian", "rm": "Romansh (Rumantsch Grischun)"}


def main():
    rows = [json.loads(l) for l in (R / "items.jsonl").open()]
    llm = LLM(os.environ["APERTUS_MODEL"], dtype="bfloat16", max_model_len=1024, gpu_memory_utilization=0.9, generation_config="vllm")
    sp = SamplingParams(temperature=0, max_tokens=60)
    msgs = [[{"role": "user", "content": (
        f"Translate this label from a Swiss parliamentary topic list into {LANG[r['to']]}. "
        f"German: {r['de']}\nEnglish: {r['en']}\n"
        f"Answer with the {LANG[r['to']].split(' ')[0]} label only, in the official terminology used by Swiss authorities.")}] for r in rows]
    res = llm.chat(msgs, sp, use_tqdm=False)
    with (R / "out.jsonl").open("w") as f:
        for r, o in zip(rows, res):
            f.write(json.dumps({**r, "out": o.outputs[0].text.strip(), "fin": o.outputs[0].finish_reason}, ensure_ascii=False) + "\n")
    print("NAMES_DONE", len(rows), flush=True)


if __name__ == "__main__":
    main()
