#!/bin/bash
# Ersteinrichtung des Newsbrokers auf dem Raspberry Pi.
#
# Läuft als root über finanzbroker-setup.service und wird bei einem Fehler (z. B. noch kein Netz)
# jede Minute wiederholt, bis alles steht. Mehrfaches Ausführen ist unschädlich.
#
# Erwartet auf der Boot-Partition:
#   finanzbroker.tar.gz   Projektordner ohne .venv
#   finanzbroker.env      die .env mit API-Key und Telegram-Daten
set -euo pipefail

BOOT="${FB_BOOT:-/boot/firmware}"
BUNDLE="$BOOT/finanzbroker.tar.gz"
ENVFILE="$BOOT/finanzbroker.env"
DONE="${FB_DONE:-/var/lib/finanzbroker-setup.done}"
UNIT_DIR="${FB_UNIT_DIR:-/etc/systemd/system}"

USER_NAME="$(getent passwd 1000 | cut -d: -f1)"
if [ -z "$USER_NAME" ]; then
    echo "Kein Benutzer mit UID 1000 gefunden" >&2
    exit 1
fi
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
APP="$HOME_DIR/Finanzbroker-4.0"

# 1. Projekt und Zugangsdaten von der Boot-Partition ins Home kopieren
if [ -f "$BUNDLE" ]; then
    mkdir -p "$APP"
    tar -xzf "$BUNDLE" -C "$APP"
fi
if [ -f "$ENVFILE" ]; then
    install -m 600 "$ENVFILE" "$APP/.env"
fi
if [ ! -f "$APP/newsbroker/__main__.py" ] || [ ! -f "$APP/.env" ]; then
    echo "Projekt oder .env fehlt unter $APP" >&2
    exit 1
fi
chown -R "$USER_NAME:$USER_NAME" "$APP"
chmod 600 "$APP/.env"
# Die Boot-Partition ist FAT und für jeden lesbar, der die Karte in der Hand hat: Secrets dort löschen.
rm -f "$BUNDLE" "$ENVFILE"

# 2. Systempakete (braucht Netz; ohne Netz bricht das Skript hier ab und läuft später erneut)
if ! dpkg -s python3-venv >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3-venv git
fi

# 3. Virtuelle Umgebung und Abhängigkeiten
if [ ! -x "$APP/.venv/bin/python" ]; then
    sudo -u "$USER_NAME" python3 -m venv "$APP/.venv"
fi
sudo -u "$USER_NAME" "$APP/.venv/bin/pip" install --quiet -r "$APP/requirements.txt"

# 4. systemd-Units mit dem tatsächlichen Benutzer und Pfad installieren
for unit in newsbroker.service newsbroker.timer newsbroker-digest.service newsbroker-digest.timer; do
    sed -e "s|^User=pi$|User=$USER_NAME|" -e "s|/home/pi/Finanzbroker-4.0|$APP|g" \
        "$APP/deploy/$unit" > "$UNIT_DIR/$unit"
done
systemctl daemon-reload
systemctl enable --now newsbroker.timer newsbroker-digest.timer

# 5. Rückmeldung aufs Handy
sudo -u "$USER_NAME" sh -c "cd '$APP' && .venv/bin/python -m newsbroker test-telegram \
    --text 'Finanzbroker 4.0: Raspberry Pi ($(hostname)) ist eingerichtet und läuft.'" || true

touch "$DONE"
systemctl disable finanzbroker-setup.service || true
echo "Einrichtung abgeschlossen"
