import json
import os
import re
import sys
from pathlib import Path

import psycopg

W = Path(os.environ.get("TITLES_DIR", "runs/titles_en"))
LEAK = re.compile(r"(?i)(^instruction:|translate (this|the) .{0,30}title|into english|keep(ing)? (the )?exact meaning|proper names, place names|answer with the english title)")


def export():
    W.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as con, (W / "titles.jsonl").open("w") as f:
        for i, t, lang in con.execute("SELECT openparldata_id, title, lang FROM affairs WHERE coalesce(trim(title), '') <> '' ORDER BY 1"):
            f.write(json.dumps({"id": i, "t": t[:400], "l": lang}, ensure_ascii=False) + "\n")


def to_d1():
    src = {json.loads(l)["id"]: json.loads(l)["t"] for l in (W / "titles.jsonl").open()}
    rows = {}
    for f in sorted(W.glob("en_*.jsonl")):
        for line in f.open():
            r = json.loads(line)
            t, s = " ".join(r["en"].split()), src[r["id"]]
            if r["fin"] != "stop" or not t or LEAK.search(t) or len(re.findall(r"[A-Za-zÀ-ÿ]", s)) < 4 or len(t) > 2.2 * len(s) + 40:
                continue
            if t != " ".join(s.split()):
                rows[int(r["id"])] = t[:400]
    out = W / "d1"
    out.mkdir(exist_ok=True)
    ids = sorted(rows)
    for n in range(0, len(ids), 20000):
        (out / f"title_en_{n // 20000:03d}.sql").write_text("".join(
            f"UPDATE affairs SET title_en = '{rows[i].replace(chr(39), chr(39) * 2)}' WHERE id = {i};\n" for i in ids[n:n + 20000]))
    print(f"{len(ids)} English titles of {len(src)}")


if __name__ == "__main__":
    {"export": export, "to_d1": to_d1}[sys.argv[1]]()
