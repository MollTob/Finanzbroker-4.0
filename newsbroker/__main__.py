"""CLI: python -m newsbroker <run|ingest|digest|stats|test-telegram|chat-id|retry-failed>"""
from __future__ import annotations

import argparse
import logging

from . import db, pipeline, telegram
from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="newsbroker")
    parser.add_argument("command", choices=["run", "ingest", "digest", "stats", "test-telegram", "chat-id", "retry-failed"])
    parser.add_argument("--title", default="Digest", help="Überschrift für den Digest")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    conn = db.connect(cfg.db_path)

    if args.command == "run":
        pipeline.run(conn, cfg)
    elif args.command == "ingest":
        pipeline.ingest(conn, cfg)
        pipeline.prefilter(conn, cfg)
    elif args.command == "digest":
        pipeline.digest(conn, cfg, args.title)
    elif args.command == "stats":
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM articles GROUP BY status"):
            print(f"Artikel {row['status']}: {row['n']}")
        print("Signale:", conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
    elif args.command == "test-telegram":
        telegram.send(cfg.telegram_token, cfg.telegram_chat_id, "Finanzbroker 4.0: Verbindung steht.")
        print("Testnachricht gesendet.")
    elif args.command == "retry-failed":
        print(f"{db.retry_failed(conn)} Artikel werden beim nächsten Lauf erneut bewertet.")
    elif args.command == "chat-id":
        chats = telegram.find_chat_ids(cfg.telegram_token)
        if not chats:
            print("Keine Nachricht gefunden. Schreib dem Bot erst etwas und versuch es erneut.")
        for chat_id, name in chats:
            print(f"TELEGRAM_CHAT_ID={chat_id}   ({name})")


if __name__ == "__main__":
    try:
        main()
    except telegram.TelegramError as exc:
        raise SystemExit(f"Fehler: {exc}")
