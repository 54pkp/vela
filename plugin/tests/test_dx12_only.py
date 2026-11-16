"""DX12O (2026-11-11): a dx12_only kit (Deep Rock Galactic) runs only on DX12. vela-launch reads the game's own command at launch time:
no API flag -> '-dx12' added for this launch; Steam's DirectX 12 entry (-dx12 / -d3d12) -> nothing added; the DX11 entry (-dx11 / -d3d11) ->
the kit is left out (plan raises, main() runs the command untouched); never -dx12 on top of -dx11. The profile carries the flag and the
plugin's launch.json gets it; other games are unchanged."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import profiles  # noqa: E402
import vela_launch  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


class Ran:
    def __init__(self, rc=0, err=b""):
        self.returncode, self.stderr, self.stdout = rc, err, b""


tmp = tempfile.mkdtemp(prefix="vela-dx12o-")
game, layer, work, kits = (os.path.join(tmp, x) for x in ("game", "layer", "work", "kits"))
for d in (game, layer, work):
    os.makedirs(d)
open(os.path.join(layer, "dxgi.dll"), "wb").close()
base = {"SteamAppId": "548430"}
run = lambda a, **k: Ran()  # noqa: E731


def kit(**extra):
    k = {"on": True, "game_dir": game, "layer": layer, "work_dir": work, "files": ["dxgi.dll"],
         "options": 'WINEDLLOVERRIDES="dxgi=n,b" VELA_NPU=1 %command%', **extra}
    os.makedirs(os.path.join(kits, "548430"), exist_ok=True)
    with open(os.path.join(kits, "548430", "launch.json"), "w", encoding="utf-8") as f:
        json.dump(k, f)


# the profile and its accessor
ok(profiles.dx12_only("548430") is True, "DRG profile is dx12_only")
ok(profiles.dx12_only("1091500") is False and profiles.dx12_only("999999") is False, "other games are not")
ok(profiles.game_cfg("548430")["keys"] == {"UpscalingType": 3}, "the game_cfg of DRG is unchanged")

# dx12_only kit, default entry (no API flag): -dx12 added for this launch only
kit(dx12_only=True)
cmd, env = vela_launch.plan(["/g", "FSD.exe"], dict(base), kits, run=run)
ok(cmd[-3:] == ["/g", "FSD.exe", "-dx12"], cmd[-3:])
ok(cmd.count("-dx12") == 1, "one -dx12")
# Steam's DirectX 12 entry: its own flag, nothing added (any case)
for flag in ("-dx12", "-D3D12", "-DX12"):
    cmd, env = vela_launch.plan(["/g", "FSD.exe", flag], dict(base), kits, run=run)
    ok(cmd[-3:] == ["/g", "FSD.exe", flag] and "-dx12" not in cmd[-2:] or flag == "-dx12" and cmd.count("-dx12") == 1, (flag, cmd[-3:]))
# the DX11 entry: the kit is left out, never -dx12 on top of -dx11
for flag in ("-dx11", "-d3d11", "-DX11"):
    try:
        vela_launch.plan(["/g", "FSD.exe", flag], dict(base), kits, run=run)
        ok(False, f"kit used with {flag}")
    except RuntimeError as e:
        ok("runs only on DX12" in str(e) and flag.lower() in str(e), str(e))
# main(): with -dx11 the command runs untouched (no kit, no -dx12)
seen = {}
vela_launch.KITS = kits
real_exec, real_execpe = os.execvp, os.execvpe
os.execvp = lambda f, a: seen.setdefault("plain", list(a))
os.execvpe = lambda f, a, e: seen.setdefault("kit", list(a))
real_environ = os.environ
os.environ = {"SteamAppId": "548430"}  # a plain dict: Windows' os.environ upper-cases the names (the console's Linux does not)
try:
    vela_launch.main(["/g", "FSD.exe", "-dx11"])
finally:
    os.execvp, os.execvpe = real_exec, real_execpe
    os.environ = real_environ
ok(seen.get("plain") == ["/g", "FSD.exe", "-dx11"] and "kit" not in seen, seen)
log = open(os.path.join(kits, "548430", "launch.log"), encoding="utf-8").read() if os.path.exists(os.path.join(kits, "548430", "launch.log")) else ""
ok("runs only on DX12" in log, "launch.log says why the kit was left out")
# the panel's per-game status (V03c sgsr3.left_out) reads the last launch.log line after "Vela left out of this launch:": it shows this reason
last = [x for x in log.splitlines() if x.strip()][-1]
ok("Vela left out of this launch: the game starts with -dx11" in last, last)

# a kit without the flag: unchanged behaviour (no -dx12 added, -dx11 keeps the kit)
kit()
cmd, env = vela_launch.plan(["/g", "FSD.exe"], dict(base), kits, run=run)
ok(cmd[-2:] == ["/g", "FSD.exe"], cmd[-2:])
cmd, env = vela_launch.plan(["/g", "FSD.exe", "-dx11"], dict(base), kits, run=run)
ok(cmd[-3:] == ["/g", "FSD.exe", "-dx11"], cmd[-3:])
# a dx12_only kit whose own options already pass -dx12: not doubled
kit(dx12_only=True, options='WINEDLLOVERRIDES="dxgi=n,b" %command% -dx12')
cmd, env = vela_launch.plan(["/g", "FSD.exe"], dict(base), kits, run=run)
ok(cmd.count("-dx12") == 1, cmd)
print(f"test_dx12_only: {checks} checks, 0 failed")
