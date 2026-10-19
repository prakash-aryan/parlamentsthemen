import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd

OUTCOMES = {
    "accepted": {"de": "angenommen", "fr": "accepté", "it": "accolto", "en": "accepted"},
    "rejected": {"de": "abgelehnt", "fr": "rejeté", "it": "respinto", "en": "rejected"},
    "answered": {"de": "beantwortet", "fr": "répondu", "it": "risposto", "en": "answered"},
    "pending": {"de": "hängig", "fr": "en suspens", "it": "pendente", "en": "pending"},
    "withdrawn": {"de": "abgeschrieben oder zurückgezogen", "fr": "classé ou retiré", "it": "stralciato o ritirato", "en": "written off or withdrawn"},
    "closed": {"de": "erledigt ohne Angabe", "fr": "liquidé sans précision", "it": "evaso senza indicazione", "en": "closed, outcome not stated"},
    "unknown": {"de": "unbekannt", "fr": "inconnu", "it": "sconosciuto", "en": "unknown"},
}
for names in OUTCOMES.values():
    names["rm"] = names["de"]

RULES = [
    ("rejected", r"abgelehnt|ablehnung|nichteintreten|nicht eintreten|non entrée en matière|unzulässig|nicht erheblich|nicht-erheblich|nicht überwiesen|nichtüberweisung|refus|rejet|non pris en consid|respint|non accolt"),
    ("pending", r"non evas|zurückgewiesen|rückweisung|ausstehend"),
    ("accepted", r"angenommen|annahme|adopt|accept|erheblich|überwiesen|überweisung an|pris en consid|folge geleistet|direkte folge|genehmigt|approvat|accolt"
                 r"|beschlossen|transmis|renvoyée au conseil d.etat|in erfüllung|umsetzungsstand|erfüllt|vollzug|inkrafttreten|zur umsetzung"),
    ("withdrawn", r"zurückgezogen|rückzug|abgeschrieben|abschreibung|retir|ritirat|stralciat|class[ée]|abgelaufen"),
    ("answered", r"beantwortet|antwort|répondu|réponse|risposta|kenntnis|prend acte|satisfait|zufrieden"),
    ("pending", r"bearbeitung|eingereicht|d[ée]pos[ée]|hängig|offen|laufend|kommission|zugewiesen|pendent|en cours|en attente|inscrit|beratung|geplant"
                r"|spruchreif|behandlungsreif|traktand|zu beantworten|entwicklung|zuteilung|^kantonsrat$|^regierungsrat$|^regierung$|manque de temps"
                r"|commission|vorparlamentarisch|pronto per|pas démarré|stellungnahme zum vorstoss|en validation|in arbeit|in vorbereitung"),
    ("closed", r"erledigt|abgeschlossen|evas|termin|archiv|traité|liquid|behandelt|behandlung|schlussabstimmung|close|gewählt|vereidigt|beschluss"
               r"|trasformat|transform|umwandlung"),
]


def category(state: str | None) -> str:
    s = (state or "").strip().lower()
    if not s:
        return "unknown"
    for name, pattern in RULES:
        if re.search(pattern, s):
            return name
    return "unknown"


def build(export: Path, out: Path) -> pd.DataFrame:
    fields = ["id", "state_name_de", "state_name_fr", "state_name_it", "state_name_rm",
              "url_external_de", "url_external_fr", "url_external_it", "url_external_rm"]
    cols = ", ".join(f"json_extract_string(json, '$.{c}') AS {c}" for c in fields)
    df = duckdb.sql(f"SELECT {cols} FROM read_ndjson_objects('{export}')").df()
    df["state"] = df[["state_name_de", "state_name_fr", "state_name_it", "state_name_rm"]].bfill(axis=1).iloc[:, 0]
    df["url_external"] = df[["url_external_de", "url_external_fr", "url_external_it", "url_external_rm"]].bfill(axis=1).iloc[:, 0]
    df["outcome"] = df["state"].map(category)
    df = df.assign(affair_id=df["id"].astype("int64"))[["affair_id", "state", "outcome", "url_external"]]
    df.to_parquet(out, index=False)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Map each affair's state in the OpenParlData export to a plain outcome category.")
    ap.add_argument("--export", type=Path, required=True, help="affairs.ndjson.gz from the OpenParlData export")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    df = build(args.export, args.out)
    print(df["outcome"].value_counts().to_string())
    top = df.dropna(subset=["state"]).groupby(["state", "outcome"]).size().sort_values(ascending=False)
    print(top.head(60).to_string())


if __name__ == "__main__":
    main()
