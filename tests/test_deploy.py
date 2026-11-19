"""Simuliert die SD-Karten-Vorbereitung und die Ersteinrichtung auf dem Pi mit Stubs für
apt, systemctl, sudo usw. Läuft ohne Netz und ohne root."""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parent.parent

USER_DATA = """#cloud-config
hostname: finanzbroker
manage_etc_hosts: true
users:
- name: pi
  groups: users,adm,sudo
  shell: /bin/bash
  lock_passwd: false
  passwd: $6$hash
timezone: Europe/Berlin
runcmd:
- [systemctl, enable, --now, ssh]
"""


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def card(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(REPO, project, ignore=shutil.ignore_patterns(".venv", "data", ".pytest_cache", "__pycache__"))
    (project / ".env").write_text("TELEGRAM_BOT_TOKEN=x\n")
    (project / ".venv").mkdir()  # darf nicht im Bundle landen
    (project / ".venv" / "marker").write_text("mac")
    bootfs = tmp_path / "bootfs"
    bootfs.mkdir()
    (bootfs / "cmdline.txt").write_text("console=tty1 root=PARTUUID=x")
    (bootfs / "user-data").write_text(USER_DATA)
    return project, bootfs


def test_prepare_sdcard(card):
    project, bootfs = card
    for _ in range(2):  # zweiter Lauf darf runcmd nicht doppeln
        out = subprocess.run([sys.executable, str(project / "deploy" / "prepare_sdcard.py"), str(bootfs)],
                             capture_output=True, text=True, check=True).stdout
    assert "war schon ergänzt" in out
    text = (bootfs / "user-data").read_text()
    assert text.startswith("#cloud-config\n")
    data = yaml.safe_load(text)
    assert data["users"][0]["passwd"] == "$6$hash" and data["hostname"] == "finanzbroker"
    assert len(data["runcmd"]) == 5 and data["runcmd"][0] == ["systemctl", "enable", "--now", "ssh"]
    assert (bootfs / "finanzbroker.env").read_text() == "TELEGRAM_BOT_TOKEN=x\n"
    import tarfile
    names = tarfile.open(bootfs / "finanzbroker.tar.gz").getnames()
    assert "newsbroker/__main__.py" in names and "deploy/pi-setup.sh" in names
    assert not any(n.startswith(".venv") or n == ".env" for n in names)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash fehlt")
def test_pi_setup_script(card, tmp_path):
    project, bootfs = card
    subprocess.run([sys.executable, str(project / "deploy" / "prepare_sdcard.py"), str(bootfs)], check=True,
                   capture_output=True)
    home = tmp_path / "home" / "tester"
    app = home / "Finanzbroker-4.0"
    (app / ".venv" / "bin").mkdir(parents=True)
    log = tmp_path / "calls.log"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub(stubs, "getent", f'echo "tester:x:1000:1000::{home}:/bin/bash"')
    _stub(stubs, "dpkg", "exit 0")
    _stub(stubs, "apt-get", f'echo "apt-get $*" >> {log}; exit 1')
    _stub(stubs, "chown", "exit 0")
    _stub(stubs, "systemctl", f'echo "systemctl $*" >> {log}')
    _stub(stubs, "sudo", 'shift 2; exec "$@"')
    for tool in ("python", "pip"):
        _stub(app / ".venv" / "bin", tool, f'echo "{tool} $*" >> {log}')
    units = tmp_path / "units"
    units.mkdir()
    env = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}", FB_BOOT=str(bootfs),
               FB_DONE=str(tmp_path / "done"), FB_UNIT_DIR=str(units))

    result = subprocess.run(["bash", str(bootfs / "finanzbroker-setup.sh")], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    assert (app / "newsbroker" / "__main__.py").exists()
    assert stat.S_IMODE((app / ".env").stat().st_mode) == 0o600
    assert not (bootfs / "finanzbroker.env").exists() and not (bootfs / "finanzbroker.tar.gz").exists()
    service = (units / "newsbroker.service").read_text()
    assert "User=tester" in service and f"{app}/.venv/bin/python" in service and "/home/pi" not in service
    calls = log.read_text()
    assert "apt-get" not in calls
    assert "pip install --quiet -r" in calls
    assert "systemctl enable --now newsbroker.timer newsbroker-digest.timer" in calls
    assert "python -m newsbroker test-telegram --text" in calls
    assert (tmp_path / "done").exists()


def test_pi_setup_fails_cleanly_without_bundle(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub(stubs, "getent", f'echo "tester:x:1000:1000::{tmp_path}/home:/bin/bash"')
    env = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}", FB_BOOT=str(tmp_path),
               FB_DONE=str(tmp_path / "done"), FB_UNIT_DIR=str(tmp_path))
    result = subprocess.run(["bash", str(REPO / "deploy" / "pi-setup.sh")], env=env, capture_output=True, text=True)
    assert result.returncode == 1 and "fehlt" in result.stderr
    assert not (tmp_path / "done").exists()
