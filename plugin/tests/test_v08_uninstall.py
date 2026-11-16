"""V08 (audit 2026-11-09): uninstalling the plugin no longer leaves every game on Vela.
Before, there was no _uninstall: each set-up game kept starting with OptiScaler from its kit (the launcher and the kits live outside the plugin
folder), the NPU layer's library was gone with the plugin (FSR 4 on the GPU: slower, hotter), the two layer manifests pointed into the removed
folder, and no panel was left to switch it off.
Now _uninstall switches every overlay kit off for the launcher and takes Vela's two manifests out; the next plugin start (Decky updates a plugin
by uninstalling it first) switches those kits on again and writes the manifests back.
Run: python -I tests/test_v08_uninstall.py     (VELA_TEST_ROOT=<another plugin tree>: the old code fails)"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("VELA_TEST_ROOT") or os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
tmp = tempfile.mkdtemp(prefix="v08_")
decky = types.ModuleType("decky")
logs = []
decky.logger = types.SimpleNamespace(info=logs.append, error=logs.append, exception=logs.append)
decky.DECKY_USER_HOME = os.path.join(tmp, "home")
decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(tmp, "settings")
sys.modules["decky"] = decky
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import launchopts  # noqa: E402
import main  # noqa: E402
import npu  # noqa: E402
import sgsr3  # noqa: E402
import vela_launch  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


home, settings = decky.DECKY_USER_HOME, decky.DECKY_PLUGIN_SETTINGS_DIR
assets = os.path.join(tmp, "plugin", "assets")
for a in ("OptiScaler.dll", "OptiPatcher.asi"):
    write(os.path.join(assets, "sgsr3", a), b"asset " + a.encode())
shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini"), os.path.join(assets, "sgsr3"))
shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "VERSION.json"), os.path.join(assets, "sgsr3"))
lib = os.path.join(home, ".local", "share", "Steam")
write(os.path.join(lib, "steamapps", "libraryfolders.vdf"), '"libraryfolders" { "0" { "path" "%s" } }' % lib.replace("\\", "/"))
for appid, name in (("4242", "OvGame"), ("4243", "OffGame")):
    write(os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf"), '"AppState" { "appid" "%s" "name" "%s" "installdir" "%s" }' % (appid, name, name))
    g = os.path.join(lib, "steamapps", "common", name)
    write(os.path.join(g, name + ".exe"), b"stub" * 100)
    write(os.path.join(g, name, "Binaries", "Win64", name + "-Win64-Shipping.exe"), b"x" * 2000)
    write(os.path.join(g, "Engine/Plugins/Runtime/Nvidia/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll"), b"dlss")
s3 = sgsr3.Sgsr3(os.path.join(assets, "sgsr3"), home, settings, log=lambda *a: None)
s3.probe = lambda exe, w, scratch: (True, "")
s3.new_mode = "launcher"
s3.enable("4242", {}, launchopts.CMD)
r = s3.enable("4243", {}, launchopts.CMD)
s3.disable("4243", r["launch_options"])                 # the player switched this one Off himself
lj = lambda a: json.load(open(os.path.join(settings, "kits", a, "launch.json"), encoding="utf-8"))
assert lj("4242")["on"] is True and lj("4243")["on"] is False

# the NPU layer's manifest in the user's layer dir, as the plugin writes it (NOFG: the lp0 one is gone, tests/test_nofg.py A1)
os.makedirs(os.path.join(assets, "npu"))
write(os.path.join(assets, "npu", npu.LIB), b"so")
shutil.copy(os.path.join(ROOT, "assets", "npu", npu.MANIFEST), os.path.join(assets, "npu"))
N = npu.Npu(os.path.join(assets, "npu"), home, settings, log=lambda *_: None, proc_net_unix=os.path.join(tmp, "none"), systemctl=lambda u: "inactive",
            graph_dir=os.path.join(tmp, "graphs"))
N.enable("4242", "%command%")
mn = N._installed_path()
assert os.path.isfile(mn)

P = main.Plugin()
P.s3, P.npu = s3, N
P.up = types.SimpleNamespace(cfg={"sgsr3": ["4242", "4243"]})
if hasattr(P, "_uninstall"):
    asyncio.run(P._uninstall())
    check("1 the kit that was on is switched off for the launcher (the game starts as without Vela)", lj("4242")["on"] is False and lj("4242").get("uninstalled") is True)
    check("2 the kit the player had switched Off is not marked", lj("4243")["on"] is False and "uninstalled" not in lj("4243"))
    check("3 the NPU layer manifest is out of the user's layer dir", not os.path.exists(mn))
    check("4 the state stays: nothing of the setup is lost", os.path.isfile(os.path.join(settings, "kits", "4242", "state.json")))
    check("5 one log line names what was done", any("Vela uninstalled" in str(m) and "4242" in str(m) for m in logs))
    # the launcher's own rule (vela_launch.py: a kit that is not on is passed through)
    k = lj("4242")
    check("6 vela-launch passes a kit with on false through", not (isinstance(k, dict) and k.get("on")) and 'kit.get("on")' in open(vela_launch.__file__, encoding="utf-8").read())
    # the plugin comes back (reinstall, or the install half of an update)
    back = s3.kits_reinstall()
    N.sync_manifest()
    check("7 after a reinstall the kit is on again, the marker is gone", back == ["4242"] and lj("4242")["on"] is True and "uninstalled" not in lj("4242"))
    check("8 the player's Off kit stays off after a reinstall", lj("4243")["on"] is False and s3.kits_reinstall() == [])
    check("9 the manifest is written again at the next start", os.path.isfile(mn))
else:
    check("1 Plugin._uninstall exists (Decky calls it when the plugin is removed)", False)
print("test_v08_uninstall " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
