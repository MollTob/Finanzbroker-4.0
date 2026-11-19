"""Legt Projekt und Setup auf die Boot-Partition einer frisch mit dem Raspberry Pi Imager
beschriebenen SD-Karte (Raspberry Pi OS ab Trixie, cloud-init).

    python3 deploy/prepare_sdcard.py /Volumes/bootfs
    python3 deploy/prepare_sdcard.py /Volumes/bootfs --ssh-key ~/.ssh/id_ed25519.pub

Ohne --ssh-key muss die Karte im Imager angepasst worden sein (Benutzer, SSH). Mit --ssh-key wird
user-data neu geschrieben: Benutzer pi ohne Passwort, Anmeldung nur per Schlüssel, Hostname
finanzbroker, Zeitzone Europe/Berlin. Dann darf die Imager-Anpassung übersprungen werden.

Kopiert:
  finanzbroker.tar.gz         Projekt ohne .venv und Caches (inkl. data/ und .git)
  finanzbroker.env            die lokale .env
  finanzbroker-setup.sh       Einrichtungsskript
  finanzbroker-setup.service  systemd-Unit, die das Skript bis zum Erfolg wiederholt
und ergänzt in user-data drei runcmd-Schritte, die beim ersten Start die Unit installieren.
Der Inhalt von user-data (Passwort-Hash, WLAN) wird dabei nicht ausgegeben.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Optional

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


def base_user_data(public_key: str, user: str = "pi", hostname: str = "finanzbroker") -> dict:
    """Entspricht dem, was der Imager bei angepasster Karte schreibt, nur ohne Passwort."""
    return {
        "hostname": hostname,
        "manage_etc_hosts": True,
        "packages": ["avahi-daemon"],
        # Der Pi hat keine Echtzeituhr: apt soll beim ersten Start nicht am Datum scheitern.
        "apt": {"conf": 'Acquire {\n  Check-Date "false";\n};\n'},
        "timezone": "Europe/Berlin",
        "keyboard": {"model": "pc105", "layout": "de"},
        "enable_ssh": True,
        "ssh_pwauth": False,
        "users": [{
            "name": user,
            "groups": "users,adm,dialout,audio,netdev,video,plugdev,cdrom,games,input,gpio,spi,i2c,render,sudo",
            "shell": "/bin/bash",
            "lock_passwd": True,
            "ssh_authorized_keys": [public_key],
            "sudo": "ALL=(ALL) NOPASSWD:ALL",
        }],
        "runcmd": [["systemctl", "enable", "--now", "ssh"]],
    }


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


def main(bootfs: Path, ssh_key: Optional[Path] = None) -> None:
    user_data = bootfs / "user-data"
    if not (bootfs / "cmdline.txt").exists():
        sys.exit(f"{bootfs} sieht nicht wie eine Raspberry-Pi-Boot-Partition aus (cmdline.txt fehlt).")
    if ssh_key is not None:
        key = ssh_key.expanduser().read_text(encoding="utf-8").strip()
        if not key.startswith("ssh-") or "PRIVATE KEY" in key:
            sys.exit(f"{ssh_key} ist kein öffentlicher SSH-Schlüssel")
        body = yaml.safe_dump(base_user_data(key), sort_keys=False, allow_unicode=True)
        user_data.write_text("#cloud-config\n" + body, encoding="utf-8")
    elif not user_data.exists():
        sys.exit("user-data fehlt: Karte im Imager anpassen oder --ssh-key angeben.")
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bootfs", type=Path)
    parser.add_argument("--ssh-key", type=Path, help="öffentlicher Schlüssel (.pub) für Benutzer pi")
    args = parser.parse_args()
    main(args.bootfs, args.ssh_key)
