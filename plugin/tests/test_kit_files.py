"""KIT1 (2026-11-11, the owner's Control 870780): an overlay kit's launch.json listed amd_fidelityfx_dx12.dll that the kit did not hold (V10 took
Vela's copy out because the game has its own, the list stayed), so vela-launch left the kit out of every launch ("kit incomplete") while the
panel said On. Now: kit_missing() names such files, status() carries them, main's not_in_launch reports them while idle too, the 10 s repair
(refresh_dll) rewrites the list from what the kit holds, and enable() fails loudly instead of writing a kit vela-launch refuses."""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import launchopts  # noqa: E402
import sgsr3  # noqa: E402
import vela_launch  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


class Ran:
    def __init__(self, rc=0, err=b""):
        self.returncode, self.stderr, self.stdout = rc, err, b""


tmp = tempfile.mkdtemp(prefix="vela-kit1-")
home = os.path.join(tmp, "home")
assets = os.path.join(tmp, "assets", "sgsr3")
for a in ("OptiScaler.dll", "OptiPatcher.asi", sgsr3.FFX_DLL):
    write(os.path.join(assets, a), b"asset " + a.encode())
shutil.copy(os.path.join(HERE, "..", "assets", "sgsr3", "OptiScaler.ini"), assets)
shutil.copy(os.path.join(HERE, "..", "assets", "sgsr3", "VERSION.json"), assets)
settings = os.path.join(tmp, "settings")
lib = os.path.join(home, ".local", "share", "Steam")
write(os.path.join(lib, "steamapps", "libraryfolders.vdf"), '"libraryfolders" { "0" { "path" "%s" } }' % lib.replace("\\", "/"))
write(os.path.join(lib, "steamapps", "appmanifest_870780.acf"), '"AppState" { "appid" "870780" "name" "Control" "installdir" "Control" }')
groot = os.path.join(lib, "steamapps", "common", "Control")
write(os.path.join(groot, "Control_DX12.exe"), b"x" * (3 << 20))
write(os.path.join(groot, "nvngx_dlss.dll"), b"dlss")
write(os.path.join(groot, sgsr3.FFX_DLL), b"the game's own FidelityFX DLL")  # Control's folder holds its own copy
logs = []
s3 = sgsr3.Sgsr3(assets, home, settings, log=logs.append)
s3.probe = lambda exe, w, scratch: (True, "")
s3.new_mode = "launcher"
ok(s3.setup_mode("870780", "%command%") == "launcher", "overlay setup")
s3.enable("870780", {}, launchopts.CMD)
kitroot = os.path.join(settings, "kits", "870780")
lj_path = os.path.join(kitroot, "launch.json")
lj = json.load(open(lj_path, encoding="utf-8"))
ok(s3.kit_missing("870780") == [], ("a fresh kit is whole", lj["files"]))
ok(s3.status("870780")["kit_missing"] == [], "status: nothing missing")
ok(sgsr3.FFX_DLL not in lj["files"], "the game has its own FidelityFX DLL: Vela's is not in the kit")

# the owner's state: an older Vela listed (and copied) its FidelityFX DLL; V10 took the file out, the list stayed
lj["files"] = sorted(lj["files"] + [sgsr3.FFX_DLL])
write(lj_path, json.dumps(lj, indent=2))
ok(s3.kit_missing("870780") == [sgsr3.FFX_DLL], s3.kit_missing("870780"))
ok(s3.status("870780")["kit_missing"] == [sgsr3.FFX_DLL], "status names the missing file")
# vela-launch refuses such a kit (what the console logged: "Vela left out of this launch: kit incomplete")
try:
    vela_launch.plan(["/g"], {"SteamAppId": "870780"}, os.path.join(settings, "kits"), run=lambda a, **k: Ran())
    ok(False, "incomplete kit used")
except RuntimeError as e:
    ok("kit incomplete" in str(e) and sgsr3.FFX_DLL in str(e), str(e))
# main's not_in_launch: "left_out" while the game is NOT running (main.py cannot be imported without Decky: the rule's text is checked)
src = open(os.path.join(HERE, "..", "main.py"), encoding="utf-8").read()
ok('if s3.get("kit_missing"):\n            return "left_out"' in src, "main.py reports an incomplete kit while idle")

# the 10 s repair mends the list from what the kit holds
logs.clear()
ok(s3.refresh_dll("870780") is True, "repair wrote something")
lj2 = json.load(open(lj_path, encoding="utf-8"))
ok(sgsr3.FFX_DLL not in lj2["files"] and s3.kit_missing("870780") == [], lj2["files"])
ok(any("kit list mended" in x for x in logs), logs)
cmd, env = vela_launch.plan(["/g"], {"SteamAppId": "870780"}, os.path.join(settings, "kits"), run=lambda a, **k: Ran())
ok(cmd[-1] == "/g", "vela-launch takes the mended kit")
ok(s3.refresh_dll("870780") is False, "a whole kit: nothing to write")

# enable() is loud: a kit that would list a file it does not hold raises (here: _write_launch made to list one more)
real = s3._write_launch
s3._write_launch = lambda appid, sc, d, st, options, files: real(appid, sc, d, st, options, list(files) + ["ghost.dll"])
try:
    s3.enable("870780", {}, launchopts.CMD)
    ok(False, "enable wrote an incomplete kit silently")
except RuntimeError as e:
    ok(str(e).startswith("kit incomplete: ghost.dll"), str(e))
finally:
    s3._write_launch = real
print(f"test_kit_files: {checks} checks, 0 failed")
