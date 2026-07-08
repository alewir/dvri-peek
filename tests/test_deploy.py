import subprocess
from tests.conftest import ROOT

SETUP = (ROOT / "deploy" / "setup-pi.sh").read_text()

def test_setup_script_syntax_ok():
    r = subprocess.run(["bash", "-n", str(ROOT / "deploy" / "setup-pi.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_setup_disables_uas_for_usb_root():
    assert "usb-storage.quirks=" in SETUP        # UAS-disable quirk
    assert "ID_VENDOR_ID" in SETUP and "ID_MODEL_ID" in SETUP   # auto-detected, not hardcoded

def test_setup_arms_watchdog_and_panic_reboot():
    assert "RuntimeWatchdogSec=15s" in SETUP
    assert "kernel.panic" in SETUP

def test_setup_installs_heartbeat_and_journald_sync():
    assert "dvri-heartbeat" in SETUP
    assert "logger -t dvri-heartbeat" in SETUP
    assert "SyncIntervalSec=10s" in SETUP

def test_netwatch_script_syntax_ok():
    r = subprocess.run(["bash", "-n", str(ROOT / "deploy" / "dvri-netwatch.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_setup_installs_network_watchdog():
    assert "dvri-netwatch.sh" in SETUP and "dvri-netwatch.timer" in SETUP
    nw = (ROOT / "deploy" / "dvri-netwatch.sh").read_text()
    assert "ip route show default" in nw          # pings the LAN gateway, not the internet
    assert "systemctl reboot" in nw               # reboot is the reliable recovery on Pi 5 WiFi
    assert 'up" -lt 300' in nw                     # boot grace period (no false trigger during boot)

def test_kiosk_disables_gpu():
    k = (ROOT / "kiosk.sh").read_text()
    assert "--disable-gpu" in k        # vc4 GPU wedge freezes the whole display; software render avoids it
