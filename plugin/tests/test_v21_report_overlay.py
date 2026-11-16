"""V21 (audit 2026-11-09): the problem report reads the kit's folder in an overlay setup.
In an overlay setup OptiScaler's log and ini and Vela's DLLs are in the kit's folder (<settings>/kits/<appid>/files), not in the game's exe
folder. run_log, versions and build looked in the exe folder: a report from a running game held no live log (the previous run's kept copy at
best), no OptiScaler.ini and the md5 of the game's own files. Also: a kernel journal query that returns no line at all (the plugin process has
no supplementary groups) was silent, so "no GPU hang found" read as "the kernel log was checked".
Run: python -I tests/test_v21_report_overlay.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
import launchopts  # noqa: E402
import report  # noqa: E402
import sgsr3  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


tmp = tempfile.mkdtemp(prefix="v21_")
home, settings = os.path.join(tmp, "home"), os.path.join(tmp, "settings")
plugin = os.path.join(tmp, "plugin")
assets = os.path.join(plugin, "assets", "sgsr3")
for a in ("OptiScaler.dll", "OptiPatcher.asi"):
    write(os.path.join(assets, a), b"asset " + a.encode())
shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini"), assets)
shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "VERSION.json"), assets)
write(os.path.join(plugin, "package.json"), json.dumps({"version": "0.8.22"}))
lib = os.path.join(home, ".local", "share", "Steam")
write(os.path.join(lib, "steamapps", "libraryfolders.vdf"), '"libraryfolders" { "0" { "path" "%s" } }' % lib.replace("\\", "/"))
write(os.path.join(lib, "steamapps", "appmanifest_4242.acf"), '"AppState" { "appid" "4242" "name" "Ov Game" "installdir" "OvGame" }')
g = os.path.join(lib, "steamapps", "common", "OvGame")
gexe = os.path.join(g, "OvGame", "Binaries", "Win64")
write(os.path.join(g, "OvGame.exe"), b"stub" * 100)
write(os.path.join(gexe, "OvGame-Win64-Shipping.exe"), b"x" * 2000)
write(os.path.join(gexe, "dxgi.dll"), b"the game's own dxgi")
write(os.path.join(g, "Engine/Plugins/Runtime/Nvidia/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll"), b"dlss")
s3 = sgsr3.Sgsr3(assets, home, settings, log=lambda *a: None)
s3.probe = lambda exe, w, scratch: (True, "")
s3.new_mode = "launcher"
s3.enable("4242", {}, launchopts.CMD)
kit = s3.where("4242")
assert s3.install_mode("4242") == "launcher" and os.path.normpath(kit) != os.path.normpath(gexe)
live_log = s3._log_path(kit, s3.kit("4242"))
write(live_log, "[12:00:00.000] [I] OptiScaler v0.9 init\n[12:00:01.000] [I] this run's line\n")
T0 = 1_800_000_000.0
os.utime(live_log, (T0 - 5, T0 - 5))


class Done:
    def __init__(self, out):
        self.returncode, self.stdout = 0, out


journal = {"kernel": ""}


def runner(args, **kw):
    if args[0] == "journalctl":
        return Done(journal["kernel"] if "_TRANSPORT=kernel" in args else "")
    raise OSError("no such tool")


clock = [T0]
R = report.Reporter(settings, home, plugin, s3=s3, npu=None, live=None, log=lambda *a: None, runner=runner, now=lambda: clock[0])
report.DEFAULT_RELAY = ""
p, label = R.run_log("4242", running=True)
check(f"1 the live log of a running overlay game is the kit's ({label})", p is not None and os.path.normpath(p) == os.path.normpath(live_log))
v = R.versions("4242")
ours = sgsr3.Sgsr3._md5(s3, os.path.join(kit, "dxgi.dll")) if hasattr(s3, "_md5") else None
check("2 versions: the md5 are of Vela's files in the kit, not of the game's own dxgi.dll",
      v.get("game_md5", {}).get("dxgi.dll") == ours and v["game_md5"].get("OptiScaler.ini"))
b = R.build("4242", "fsr", "", None, None, "Ov Game", None, True)
with zipfile.ZipFile(R._path(b["id"] + ".zip")) as z:
    names = z.namelist()
    body = {n: z.read(n) for n in names}
check(f"3 the report zip holds the kit's OptiScaler.ini ({sorted(names)})", "OptiScaler.ini" in names)
check("4 ... and this run's log line", any(b"this run's line" in body[n] for n in names if n.lower().endswith(".log")))
meta = json.loads(body["meta.json"].decode("utf-8"))
check(f"5 an empty kernel journal is named in the report ({meta.get('errors')})", any("kernel journal empty" in e for e in meta.get("errors", [])))
journal["kernel"] = "2026-11-10T02:00:00+01:00 armada kernel: usb 1-1: new device\n"
clock[0] += 120
b2 = R.build("4242", "slow", "", None, None, "Ov Game", None, True)
with zipfile.ZipFile(R._path(b2["id"] + ".zip")) as z2:
    meta2 = json.loads(z2.read("meta.json").decode("utf-8"))
check("6 a kernel journal with lines (none about the GPU) is not called empty", not any("kernel journal" in e for e in meta2.get("errors", [])))
# a copy setup still reads the game's exe folder
s3b = sgsr3.Sgsr3(assets, home, os.path.join(tmp, "settings2"), log=lambda *a: None)
s3b.enable("4242", {}, launchopts.CMD, mode="copy")
Rb = report.Reporter(os.path.join(tmp, "settings2"), home, plugin, s3=s3b, npu=None, live=None, log=lambda *a: None, runner=runner, now=lambda: T0)
vb = Rb.versions("4242")
check("7 a copy setup: the md5 are of the game's exe folder, as before", vb.get("game_md5", {}).get("dxgi.dll") is not None and vb["game_md5"].get("OptiScaler.ini"))
print("test_v21_report_overlay " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
