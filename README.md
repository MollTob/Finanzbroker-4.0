# Finanzbroker 4.0

Newsbroker: liest Nachrichten-Feeds, lässt ein LLM Markt-Signale vorbewerten und schickt sie per Telegram.
Das System handelt nicht selbst. Es liefert nur Vorschläge (Markt, Richtung, Stärke, Horizont, Begründung).

## Ablauf

1. **Ingest:** RSS/Atom-Feeds abrufen, Dubletten über URL und normalisierten Titel verwerfen.
2. **Vorfilter:** Medienartikel brauchen einen Keyword-Treffer, Primärquellen (Notenbanken, Behörden) gehen immer durch.
3. **Scoring:** Das LLM liefert pro Artikel bis zu drei Signale in einem festen JSON-Schema.
4. **Push:** Signale ab Stärke 4 und Konfidenz 0,7 kommen sofort per Telegram.
5. **Digest:** Alles ab Stärke 2 kommt gesammelt zu den Handelsfenstern.

Jedes Signal landet mit Zeitstempel in SQLite (`data/newsbroker.db`). Darauf baut später die Auswertung
gegen die tatsächliche Kursentwicklung auf (Tabelle `evaluations`, noch nicht implementiert).

## Einrichtung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # Keys eintragen
.venv/bin/python -m newsbroker test-telegram
.venv/bin/python -m newsbroker run
```

- **Telegram:** Bot über `@BotFather` anlegen (`/newbot`), Token in `.env`. Dem Bot einmal schreiben, dann zeigt
  `python -m newsbroker chat-id` die Chat-ID an.
- **LLM:** `ANTHROPIC_API_KEY` in `.env`. Modell und Schwellen stehen in `config/feeds.toml`.

## Befehle

| Befehl | Wirkung |
|---|---|
| `python -m newsbroker run` | Kompletter Lauf: Ingest, Vorfilter, Scoring, Push |
| `python -m newsbroker ingest` | Nur Feeds abrufen und filtern (kostet keine LLM-Tokens) |
| `python -m newsbroker digest --title "US-Schluss"` | Digest senden |
| `python -m newsbroker stats` | Zählerstände |
| `python -m newsbroker retry-failed` | Fehlgeschlagene Artikel für den nächsten Lauf freigeben |
| `python -m newsbroker chat-id` | Chat-ID anzeigen, nachdem du dem Bot geschrieben hast |
| `python -m newsbroker test-telegram` | Testnachricht |

## Raspberry Pi

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now newsbroker.timer newsbroker-digest.timer
```

Die Units erwarten das Repo unter `/home/pi/Finanzbroker-4.0` mit einer `.venv` darin.

## Tests

```bash
pip install pytest && python -m pytest
```
