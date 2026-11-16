"""V15 (audit 2026-11-09): the plugin start no longer scans every set-up game for a migration that is long done.
_llfg_migrate (LL / FG left the panel in 0.8.9) asked s3.status of every set-up game at EVERY plugin start, inline on the event loop: a cold
folder walk, an md5 of the kit DLL and up to 2 MB of log per game. With 15 games on an SD card the panel sat on "Loading" until all ended.
Now one clean pass is remembered in the settings (llfg_migrated) and later starts skip it.
Run: python -I tests/test_v15_start_scan.py     (VELA_TEST_ROOT=<another plugin tree>: the old code fails)"""
import os
import sys
import tempfile
import threading
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("VELA_TEST_ROOT") or os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
tmp = tempfile.mkdtemp(prefix="v15_")
decky = types.ModuleType("decky")
decky.logger = types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None, exception=lambda *a: None)
decky.DECKY_USER_HOME = os.path.join(tmp, "home")
decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(tmp, "settings")
sys.modules["decky"] = decky
sys.path.insert(0, ROOT)
import main  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


GAMES = [str(1000 + i) for i in range(15)]
calls = {"status": 0, "off": [], "save": 0}


class S3:
    def status(self, appid):
        calls["status"] += 1
        return {"installed": True, "opts": {"fg": appid == "1003"}}      # one game still has FG from an old Vela


class Up:
    def __init__(self):
        self.cfg = {"sgsr3": list(GAMES)}
        self.lock = threading.Lock()

    def _save(self):
        calls["save"] += 1


class Lat:
    def _state_path(self, appid):
        return os.path.join(tmp, "lat", f"{appid}.json")

    def wanted(self, appid):
        return {"on": False}


def plugin(up):
    P = main.Plugin()
    P.s3, P.up, P.lat = S3(), up, Lat()
    P._llfg_off = lambda appid, launch: calls["off"].append(appid)
    return P


up = Up()
P = plugin(up)
P._llfg_migrate()
check(f"1 the first start looks at every set-up game once ({calls['status']} status calls for 15 games) and switches the old FG off", calls["status"] == 15 and calls["off"] == ["1003"])
check("2 the game with FG is queued for the panel's launch-option cleanup, as before", up.cfg.get("llfg_pending") == ["1003"])
n = calls["status"]
P2 = plugin(up)                       # the next plugin start (the same settings)
P2._llfg_migrate()
check(f"3 the next start does not scan again ({calls['status'] - n} status calls, was 15 at every start)", calls["status"] == n)
check("4 the pass is remembered in the settings", up.cfg.get("llfg_migrated") is True)
up2 = Up()
P3 = plugin(up2)
P3.s3.status = lambda appid: (_ for _ in ()).throw(OSError("SD card gone"))
try:
    P3._llfg_migrate()
except OSError:
    pass
check("5 a pass that failed half-way is not remembered (it runs again at the next start)", not up2.cfg.get("llfg_migrated"))
print("test_v15_start_scan " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
