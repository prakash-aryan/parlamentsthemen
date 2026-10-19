import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from parltopics.evaluate import best_threshold, weighted_prf

SEED = 20261018
GROUPS = ["SVP/UDC", "SP/PS", "FDP/PLR", "Mitte/Centre", "Grüne/Verts", "GLP/PVL", "other or committee"]
PARTY_GROUP = {
    "Schweizerische Volkspartei": "SVP/UDC", "Lega dei Ticinesi": "SVP/UDC", "Mouvement Citoyens Genevois": "SVP/UDC",
    "Eidgenössisch-Demokratische Union": "SVP/UDC", "Sozialdemokratische Partei": "SP/PS", "FDP.Die Liberalen": "FDP/PLR",
    "Liberal-Demokratische Partei": "FDP/PLR", "Die Mitte": "Mitte/Centre", "Evangelische Volkspartei": "Mitte/Centre",
    "Die Grünen": "Grüne/Verts", "Alternative Linke": "Grüne/Verts", "Basels Starke Alternative": "Grüne/Verts",
    "Grünliberale Partei": "GLP/PVL",
}
FRAKTION_GROUP = [("Grünliberal", "GLP/PVL"), ("Volkspartei", "SVP/UDC"), ("Sozialdemokrat", "SP/PS"), ("FDP", "FDP/PLR"),
                  ("Mitte", "Mitte/Centre"), ("Grüne Fraktion", "Grüne/Verts")]
SLANT_AREAS = {"2811": "Migration", "52": "Umwelt", "28": "Soziale Fragen", "9": "Sicherheitspolitik", "15": "Wirtschaft"}


def fraktion_group(name: str | None) -> str:
    for key, group in FRAKTION_GROUP:
        if name and key in name:
            return group
    return "other or committee"


def authors(contributors: Path, affair_ids: list[int]) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("ids", pd.DataFrame({"affair_id": affair_ids}))
    c = con.sql(f"SELECT c.affair_id, c.type, c.role_de, c.fullname, c.party_harmonized_de FROM read_json_auto('{contributors}', "
                "format='newline_delimited', sample_size=-1) c JOIN ids USING (affair_id) "
                "WHERE c.body_key = 'CHE' AND c.role_harmonized = 'author' AND c.role_de = 'Urheber(-in)'").df()
    rows = []
    for aid in affair_ids:
        a = c[c.affair_id == aid]
        person = a[a.type == "person"]
        group = a[a.type == "group"]
        if len(person):
            party = person.party_harmonized_de.iloc[0]
            rows.append({"affair_id": aid, "group": PARTY_GROUP.get(party, "other or committee"), "linked_by": "person author",
                         "party": party})
        elif len(group):
            rows.append({"affair_id": aid, "group": fraktion_group(group.fullname.iloc[0]), "linked_by": "group author",
                         "party": group.fullname.iloc[0]})
        else:
            rows.append({"affair_id": aid, "group": "other or committee", "linked_by": "no author", "party": None})
    return pd.DataFrame(rows)


def curia_decisions(samples: Path, scores: Path) -> pd.DataFrame:
    dev = pd.read_parquet(samples / "curia_dev_sample.parquet")
    test = pd.read_parquet(samples / "curia_test_sample.parquet")
    out = []
    for path in sorted(scores.glob("G_desc_test_curia_*.parquet")):
        area = path.stem.rsplit("_", 1)[1]
        d = dev.merge(pd.read_parquet(scores / f"G_desc_dev_curia_{area}.parquet")[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        t = test.merge(pd.read_parquet(path)[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
        yd = d.topic_ids.apply(lambda x: area in [str(v) for v in x]).to_numpy(bool)
        if yd.sum() == 0:
            continue
        thr = best_threshold(yd, d.score.to_numpy(float), np.ones(len(d)))
        out.append(pd.DataFrame({"affair_id": t.affair_id.to_numpy(), "area": area,
                                 "label": t.topic_ids.apply(lambda x: area in [str(v) for v in x]).to_numpy(bool),
                                 "pred": t.score.to_numpy(float) >= thr}))
    return pd.concat(out, ignore_index=True)


def digit_decisions(samples: Path, scores: Path) -> pd.DataFrame:
    dev = pd.read_parquet(samples / "dev_sample.parquet").merge(
        pd.read_parquet(scores / "G_desc_dev_digitalisation.parquet")[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
    thr = best_threshold(dev.label.to_numpy(bool), dev.score.to_numpy(float), dev.weight.to_numpy(float))
    test = pd.read_parquet(samples / "test_sample.parquet").merge(
        pd.read_parquet(scores / "G_desc_test_digitalisation.parquet")[["affair_id", "score"]], on="affair_id").dropna(subset=["score"])
    test = test[test.level == "country"]
    return pd.DataFrame({"affair_id": test.affair_id.to_numpy(), "label": test.label.to_numpy(bool),
                         "pred": test.score.to_numpy(float) >= thr, "weight": test.weight.to_numpy(float)})


def per_affair(df: pd.DataFrame) -> pd.DataFrame:
    w = df.weight.to_numpy(float) if "weight" in df else np.ones(len(df))
    y, p = df.label.to_numpy(bool), df.pred.to_numpy(bool)
    a = pd.DataFrame({"affair_id": df.affair_id.to_numpy(), "tp": w * (y & p), "fp": w * (~y & p), "fn": w * (y & ~p),
                      "yes": p.astype(float), "lab": y.astype(float), "n": 1.0})
    return a.groupby("affair_id").sum()


def stats(m: np.ndarray) -> np.ndarray:
    tp, fp, fn, yes, lab, n = m.T if m.ndim == 2 else m
    prec = np.where(tp + fp > 0, tp / np.maximum(tp + fp, 1e-12), np.nan)
    rec = np.where(tp + fn > 0, tp / np.maximum(tp + fn, 1e-12), np.nan)
    f1 = np.where(prec + rec > 0, 2 * prec * rec / np.maximum(prec + rec, 1e-12), np.nan)
    return np.stack([prec, rec, f1, (yes - lab) / n], axis=-1)


def table(dec: pd.DataFrame, who: pd.DataFrame, n_boot: int, cols: list[str]) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    agg = per_affair(dec).join(who.set_index("affair_id")["group"], how="inner")
    rows = []
    for g in GROUPS + ["all"]:
        part = agg if g == "all" else agg[agg.group == g]
        if part.empty:
            continue
        m = part[["tp", "fp", "fn", "yes", "lab", "n"]].to_numpy(float)
        est = stats(m.sum(axis=0))
        idx = rng.integers(0, len(m), size=(n_boot, len(m)))
        boot = stats(m[idx].sum(axis=1))
        lo, hi = np.nanpercentile(boot, 2.5, axis=0), np.nanpercentile(boot, 97.5, axis=0)
        row = {"group": g, "affairs": len(part)}
        for i, name in enumerate(["precision", "recall", "F1", "yes_minus_label"]):
            if name in cols:
                row[name] = f"{est[i]:.2f} [{lo[i]:.2f}, {hi[i]:.2f}]" if name != "yes_minus_label" else f"{est[i]:+.3f} [{lo[i]:+.3f}, {hi[i]:+.3f}]"
                row[f"_{name}"] = (est[i], lo[i], hi[i])
        rows.append(row)
    return pd.DataFrame(rows)


def within_noise(t: pd.DataFrame, metric: str) -> list[str]:
    overall = t[t.group == "all"][f"_{metric}"].iloc[0][0]
    return [r["group"] for r in t.to_dict("records") if r["group"] != "all" and not (r[f"_{metric}"][1] <= overall <= r[f"_{metric}"][2])]


def md(t: pd.DataFrame) -> str:
    cols = [c for c in t.columns if not c.startswith("_")]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in t[cols].itertuples(index=False)]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Results of the decision model by parliamentary group of the affair's author.")
    ap.add_argument("--contributors", type=Path, required=True)
    ap.add_argument("--samples", type=Path, required=True)
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    curia = curia_decisions(args.samples, args.scores)
    digit = digit_decisions(args.samples, args.scores)
    who = authors(args.contributors, sorted(set(curia.affair_id) | set(digit.affair_id)))
    who.to_csv(args.out / "authors.csv", index=False)
    t_all = table(curia, who, args.n_boot, ["precision", "recall", "F1", "yes_minus_label"])
    slant = {name: table(curia[curia.area == a], who, args.n_boot, ["yes_minus_label"]) for a, name in SLANT_AREAS.items()}
    t_dig = table(digit, who, args.n_boot, ["precision", "recall", "F1"])
    for name, t in [("curia_all", t_all), ("digitalisation", t_dig)] + [(f"area_{k}", v) for k, v in slant.items()]:
        t[[c for c in t.columns if not c.startswith("_")]].to_csv(args.out / f"{name.replace(' ', '_')}.csv", index=False)
    cov = who[who.affair_id.isin(curia.affair_id)]
    report = {
        "coverage": cov.linked_by.value_counts().to_dict(), "groups": cov.group.value_counts().to_dict(),
        "curia": md(t_all), "digit": md(t_dig),
        "slant": "\n\n".join(f"**{name}**\n\n{md(t)}" for name, t in slant.items()),
        "noise_f1": within_noise(t_all, "F1"), "noise_yes": within_noise(t_all, "yes_minus_label"),
        "noise_digit_r": within_noise(t_dig, "recall"),
        "noise_slant": {name: within_noise(t, "yes_minus_label") for name, t in slant.items()},
    }
    (args.out / "summary.json").write_text(pd.Series(report).to_json(force_ascii=False, indent=1))
    print(md(t_all)); print(); print(md(t_dig)); print(report["coverage"], report["groups"])
    print("outside the interval of the overall value:", {k: report[k] for k in ("noise_f1", "noise_yes", "noise_digit_r", "noise_slant")})


if __name__ == "__main__":
    main()
