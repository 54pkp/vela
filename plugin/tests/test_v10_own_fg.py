"""V10 (audit 2026-11-09): an overlay setup no longer hides the game's own amd_fidelityfx_dx12.dll.
Vela's FidelityFX SDK DLL goes in "whenever the game has none of its own; a game's own copy stays (its FSR 3.1 runs)". "The game has its
own" was read from the backup record; in an overlay setup the backup looks into the kit's (empty) folder, so the answer was always "none"
and Vela's SDK 1.1.4 copy was mounted over a game's own, possibly newer, library. Now an overlay setup looks into the game's exe folder.
A kit set up by an older Vela loses Vela's copy at the next refresh of the closed game (only Vela's own file, only out of Vela's own kit).
Run: python -I tests/test_v10_own_fg.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
import launchopts  # noqa: E402
import sgsr3  # noqa: E402

fails = []
FG = sgsr3.FFX_DLL
OWN = b"the game's own FSR 3.1 library"


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def world(own, mode):
    tmp = tempfile.mkdtemp(prefix="v10_")
    home, settings = os.path.join(tmp, "home"), os.path.join(tmp, "settings")
    assets = os.path.join(tmp, "plugin", "assets", "sgsr3")
    for a in ("OptiScaler.dll", "OptiPatcher.asi", FG):
        write(os.path.join(assets, a), b"vela " + a.encode())
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
    if own:
        write(os.path.join(gexe, FG), OWN)
    s3 = sgsr3.Sgsr3(assets, home, settings, log=lambda *a: None)
    s3.probe = lambda exe, w, scratch: (True, "")
    assert s3.fsr3_available(), "the test world has FSR 3.1 live"
    s3.enable("4242", {}, launchopts.CMD, mode=mode)
    return s3, s3.where("4242"), gexe


def data(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


# 1. overlay, the game has its own library: nothing of Vela's is mounted over it
s3, kit, gexe = world(True, "launcher")
assert os.path.normpath(kit) != os.path.normpath(gexe)
check("1 overlay + the game's own library: Vela's copy is not in the kit (nothing is mounted over the game's)", data(os.path.join(kit, FG)) is None)
check("1b ... the game's own file is untouched", data(os.path.join(gexe, FG)) == OWN)
# a kit an older Vela set up has Vela's copy in it: the closed game's refresh takes it out
write(os.path.join(kit, FG), b"vela " + FG.encode())
check("2 a kit of an older Vela: the refresh of the closed game takes Vela's copy out", s3.refresh_dll("4242") is True and data(os.path.join(kit, FG)) is None)
check("2b ... once: the next refresh has nothing to do", not s3.refresh_dll("4242") and s3.status("4242")["intact"] is True)
# a file in the kit that is not Vela's build is never removed
write(os.path.join(kit, FG), b"somebody else's file")
s3.refresh_dll("4242")
check("2c a file there that is not Vela's copy is left alone", data(os.path.join(kit, FG)) == b"somebody else's file")

# 3. overlay, the game has none: Vela's copy is in the kit (FSR 3.1 as a live model needs it)
s3, kit, gexe = world(False, "launcher")
check("3 overlay + no library of the game's own: Vela's copy is in the kit", data(os.path.join(kit, FG)) == b"vela " + FG.encode())
check("3b ... and stays there over a refresh", not s3.refresh_dll("4242") and data(os.path.join(kit, FG)) == b"vela " + FG.encode())

# 4. copy setups, as before
s3, d, gexe = world(True, "copy")
check("4 copy + the game's own library: it stays", data(os.path.join(gexe, FG)) == OWN)
s3, d, gexe = world(False, "copy")
check("5 copy + none: Vela's copy goes in", data(os.path.join(gexe, FG)) == b"vela " + FG.encode())
print("test_v10_own_fg " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
