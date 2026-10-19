import argparse
import getpass
import sys

from parltopics.db import OVERLAY_DDL, connect, read_env


def ensure(con) -> None:
    con.execute(OVERLAY_DDL)


def add(con, affair_id: int, topic: str, decision: str, reason: str, by: str) -> dict:
    row = con.execute("SELECT probability, decision, model_revision, card_hash FROM affair_topics WHERE openparldata_id = %s AND topic_code = %s "
                      "ORDER BY created_at DESC LIMIT 1", (affair_id, topic)).fetchone()
    if row is None:
        raise SystemExit(f"no stored decision for affair {affair_id} and topic {topic}")
    con.execute("INSERT INTO affair_topic_corrections (openparldata_id, topic_code, corrected_decision, reason, corrected_by, "
                "original_probability, original_decision, model_revision, card_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (affair_id, topic, decision, reason, by, *row))
    con.commit()
    return {"openparldata_id": affair_id, "topic_code": topic, "original_decision": row[1], "original_probability": row[0],
            "corrected_decision": decision, "model_revision": row[2], "card_hash": row[3], "reason": reason, "corrected_by": by}


def listing(con, limit: int) -> list[tuple]:
    return con.execute("SELECT c.created_at, c.openparldata_id, c.topic_code, c.original_decision, c.original_probability, c.corrected_decision, "
                       "c.corrected_by, c.reason FROM affair_topic_corrections c ORDER BY c.created_at DESC LIMIT %s", (limit,)).fetchall()


def open_flags(con, limit: int) -> list[tuple]:
    return con.execute("SELECT f.created_at, f.openparldata_id, f.topic_code, t.decision, t.probability, f.note "
                       "FROM affair_topic_flags f LEFT JOIN affair_topics_current t "
                       "ON t.openparldata_id = f.openparldata_id AND t.topic_code = f.topic_code "
                       "WHERE NOT EXISTS (SELECT 1 FROM affair_topic_corrections c WHERE c.openparldata_id = f.openparldata_id "
                       "AND c.topic_code = f.topic_code AND c.created_at >= f.created_at) "
                       "ORDER BY f.created_at DESC LIMIT %s", (limit,)).fetchall()


def main() -> None:
    read_env()
    ap = argparse.ArgumentParser(description="Human corrections of stored topic decisions; the original decision is kept.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--affair", type=int, required=True)
    a.add_argument("--topic", required=True)
    a.add_argument("--decision", choices=["yes", "no"], required=True)
    a.add_argument("--reason", required=True)
    a.add_argument("--by", default=getpass.getuser())
    for name in ("list", "from-flags"):
        sub.add_parser(name).add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    with connect() as con:
        ensure(con)
        if args.cmd == "add":
            print(add(con, args.affair, args.topic, args.decision, args.reason, args.by))
        else:
            rows = listing(con, args.limit) if args.cmd == "list" else open_flags(con, args.limit)
            for r in rows:
                print(" | ".join("" if v is None else (v.isoformat(timespec="seconds") if hasattr(v, "isoformat") else str(v)) for v in r))
            if not rows:
                print("none", file=sys.stderr)


if __name__ == "__main__":
    main()
