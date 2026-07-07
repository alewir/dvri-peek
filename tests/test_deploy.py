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
