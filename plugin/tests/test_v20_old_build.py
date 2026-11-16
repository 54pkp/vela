"""V20 (audit 2026-11-09): an older build of Vela's own dxgi.dll in a game's kit is not "The game's files changed".
`intact` compared the kit's dxgi.dll with the plugin's CURRENT build; the kit is refreshed only while the game is closed. A plugin update
while a game ran left the card red ("The game's files changed", "choose Off, then the model again") until the game exited: nothing was
wrong. Now the md5 Vela wrote is kept in the game's state (as the static kit does since 0.8.11): a file equal to it is an older build of
ours (intact, dxgi_old); a setup made before this fix has no hash and is judged by the file's time (not written since Vela's last write).
A foreign file, the game's own file back (verify) and a missing file stay "changed".
Run: python -I tests/test_v20_old_build.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
import launchopts  # noqa: E402
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


def world(name, mode):
    tmp = tempfile.mkdtemp(prefix="v20_")
    home, settings = os.path.join(tmp, "home"), os.path.join(tmp, "settings")
    assets = os.path.join(tmp, "plugin", "assets", "sgsr3")
    for a in ("OptiScaler.dll", "OptiPatcher.asi"):
        write(os.path.join(assets, a), b"build 1 " + a.encode())
    shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini"), assets)
    shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "VERSION.json"), assets)
    lib = os.path.join(home, ".local", "share", "Steam")
    write(os.path.join(lib, "steamapps", "libraryfolders.vdf"), '"libraryfolders" { "0" { "path" "%s" } }' % lib.replace("\\", "/"))
    write(os.path.join(lib, "steamapps", "appmanifest_4242.acf"), '"AppState" { "appid" "4242" "name" "G" "installdir" "G" }')
    g = os.path.join(lib, "steamapps", "common", "G")
    gexe = os.path.join(g, "G", "Binaries", "Win64")
    write(os.path.join(g, "G.exe"), b"stub" * 100)
    write(os.path.join(gexe, "G-Win64-Shipping.exe"), b"x" * 2000)
    write(os.path.join(g, "Engine/Plugins/Runtime/Nvidia/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll"), b"dlss")
    if name == "own":
        write(os.path.join(gexe, "dxgi.dll"), b"the game's own dxgi")
    s3 = sgsr3.Sgsr3(assets, home, settings, log=lambda *a: None)
    s3.probe = lambda exe, w, scratch: (True, "")
    s3.enable("4242", {}, launchopts.CMD, mode=mode)
    return s3, assets, s3.where("4242"), gexe


for mode in ("launcher", "copy"):
    s3, assets, d, gexe = world("plain", mode)
    dll = os.path.join(d, "dxgi.dll")
    st0 = s3.status("4242")
    check(f"{mode} 1 a fresh setup is whole", st0["intact"] is True and not st0.get("dxgi_old"))
    # the plugin is updated while the game runs: the plugin's build changes, the kit keeps the old one
    write(os.path.join(assets, "OptiScaler.dll"), b"build 2 OptiScaler.dll")
    st1 = s3.status("4242")
    check(f"{mode} 2 after a plugin update the kit's older build of ours is not 'changed' ({st1['intact']}, old {st1.get('dxgi_old')})",
          st1["intact"] is True and st1.get("dxgi_old") is True)
    # the game closes: the kit follows the plugin, and the new hash is the recorded one
    check(f"{mode} 3 the closed game's kit follows the plugin", s3.refresh_dll("4242") and open(dll, "rb").read() == b"build 2 OptiScaler.dll")
    st2 = s3.status("4242")
    check(f"{mode} 4 ... and is whole and current again", st2["intact"] is True and not st2.get("dxgi_old"))
    write(os.path.join(assets, "OptiScaler.dll"), b"build 3 OptiScaler.dll")
    st3 = s3.status("4242")
    check(f"{mode} 5 a second update: the build the refresh wrote is known as ours too", st3["intact"] is True and st3.get("dxgi_old") is True)
    # a foreign file is still "changed"
    write(dll, b"another mod's dxgi.dll")
    check(f"{mode} 6 a foreign dxgi.dll is 'changed'", s3.status("4242")["intact"] is False)
    os.remove(dll)
    check(f"{mode} 7 a missing dxgi.dll is 'changed'", s3.status("4242")["intact"] is False)

# a setup made by a build before this fix: no hash in the state; the file's time decides
s3, assets, d, gexe = world("plain", "launcher")
stj = s3.read_state(d)
stj.pop("dxgi_md5", None)
s3._write_state(d, stj)
found = "dxgi_md5" not in s3.read_state(d)
write(os.path.join(assets, "OptiScaler.dll"), b"build 2 OptiScaler.dll")
st = s3.status("4242")
check("8 a setup of an earlier Vela (no hash): the file Vela wrote at the setup is an older build of ours", found and st["intact"] is True and st.get("dxgi_old") is True)
dll = os.path.join(d, "dxgi.dll")
write(dll, b"another mod's dxgi.dll")
later = time.time() + 600
os.utime(dll, (later, later))
check("9 ... a file written after Vela's last write is 'changed'", s3.status("4242")["intact"] is False)

# the game's own dxgi.dll back in a copy setup (Steam's verify) is "changed"
s3, assets, d, gexe = world("own", "copy")
write(os.path.join(assets, "OptiScaler.dll"), b"build 2 OptiScaler.dll")
write(os.path.join(d, "dxgi.dll"), b"the game's own dxgi")
check("10 the game's own dxgi.dll back (verify) is 'changed', not an older build", s3.status("4242")["intact"] is False)
print("test_v20_old_build " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
