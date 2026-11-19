"""Legt Projekt und Setup auf die Boot-Partition einer frisch mit dem Raspberry Pi Imager
beschriebenen SD-Karte (Raspberry Pi OS ab Trixie, cloud-init).

    python3 deploy/prepare_sdcard.py /Volumes/bootfs

Kopiert:
  finanzbroker.tar.gz         Projekt ohne .venv und Caches (inkl. data/ und .git)
  finanzbroker.env            die lokale .env
  finanzbroker-setup.sh       Einrichtungsskript
  finanzbroker-setup.service  systemd-Unit, die das Skript bis zum Erfolg wiederholt
und ergänzt in user-data drei runcmd-Schritte, die beim ersten Start die Unit installieren.
Der Inhalt von user-data (Passwort-Hash, WLAN) wird dabei nicht ausgegeben.
"""
from __future__ import annotations

import shutil
import sys
import tarfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = {".venv", "__pycache__", ".pytest_cache", ".env", ".DS_Store"}
MARKER = "/usr/local/sbin/finanzbroker-setup.sh"
RUNCMD = [
    ["install", "-m", "755", "/boot/firmware/finanzbroker-setup.sh", MARKER],
    ["install", "-m", "644", "/boot/firmware/finanzbroker-setup.service", "/etc/systemd/system/"],
    ["systemctl", "daemon-reload"],
    ["systemctl", "enable", "--now", "--no-block", "finanzbroker-setup.service"],
]


def _filter(info: tarfile.TarInfo):
    parts = Path(info.name).parts
    return None if any(p in EXCLUDE for p in parts) else info


def patch_user_data(path: Path) -> bool:
    """Hängt die runcmd-Schritte an. Gibt False zurück, wenn sie schon drin sind."""
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    runcmd = data.setdefault("runcmd", [])
    if any(MARKER in str(cmd) for cmd in runcmd):
        return False
    runcmd.extend(RUNCMD)
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path.write_text("#cloud-config\n" + body, encoding="utf-8")
    return True


def main(bootfs: Path) -> None:
    user_data = bootfs / "user-data"
    if not (bootfs / "cmdline.txt").exists() or not user_data.exists():
        sys.exit(f"{bootfs} sieht nicht wie eine mit dem Imager angepasste Boot-Partition aus "
                 "(cmdline.txt oder user-data fehlt).")
    if not (ROOT / ".env").exists():
        sys.exit(".env fehlt im Projektordner")

    with tarfile.open(bootfs / "finanzbroker.tar.gz", "w:gz") as tar:
        for item in sorted(ROOT.iterdir()):
            tar.add(item, arcname=item.name, filter=_filter)
    shutil.copyfile(ROOT / ".env", bootfs / "finanzbroker.env")
    shutil.copyfile(ROOT / "deploy" / "pi-setup.sh", bootfs / "finanzbroker-setup.sh")
    shutil.copyfile(ROOT / "deploy" / "finanzbroker-setup.service", bootfs / "finanzbroker-setup.service")
    changed = patch_user_data(user_data)

    size = (bootfs / "finanzbroker.tar.gz").stat().st_size / 1e6
    print(f"Projekt kopiert ({size:.1f} MB), .env kopiert, user-data {'ergänzt' if changed else 'war schon ergänzt'}.")
    print("Runcmd-Einträge:", len(yaml.safe_load(user_data.read_text(encoding='utf-8')).get("runcmd", [])))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
