"""V12 (audit 2026-11-09): the one-time "Steam's own Gamescope filter back" neither sets a wrong filter nor retries for ever.
A  xprop could not read the root window (exit code not 0, nothing printed): the defaults "linear, 2" were pushed to Gamescope and the
   migration was marked done: Gamescope on Linear while Steam's menu shows FSR. Now nothing is pushed and the try counts as failed.
   (xprop that ran and found no atom: Steam never set a filter; Gamescope's own default, linear, is pushed as before.)
B  a tool is missing, or the device is in desktop mode: two process starts and a log line on every 10 s pass, for ever. Now the first
   6 passes try, then one pass in 30 (5 min); the same reason is logged once.
C  a NEW install (no settings file) has no older Vela's filter to undo: it never starts the migration (it did as soon as one game was
   set up and the plugin started again). A settings file of an older Vela (no "gamescope_reset" in it) still gets it.
Run: python -I tests/test_v12_filter_restore.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
import upscale  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


world = {"xprop": (0, "GAMESCOPE_NEW_SCALING_FILTER(CARDINAL) = 2\nGAMESCOPE_FSR_SHARPNESS(CARDINAL) = 3\n"), "ctl": 0, "missing": False}
starts, pushed, logs = [], [], []


def fake_run(cmd, **kw):
    starts.append(cmd[0])
    if world["missing"]:
        raise FileNotFoundError(2, "No such file or directory", cmd[0])
    if cmd[0] == upscale.XPROP:
        rc, out = world["xprop"]
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="unable to open display" if rc else "")
    if world["ctl"]:
        return types.SimpleNamespace(returncode=world["ctl"], stdout="", stderr="no gamescope socket")
    pushed.append((cmd[1], cmd[2]))
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


upscale.subprocess = types.SimpleNamespace(run=fake_run, SubprocessError=upscale.subprocess.SubprocessError)
if not hasattr(os, "getuid"):
    os.getuid = lambda: 1000   # Windows (tests): _env() asks for it


def old_install():
    d = tempfile.mkdtemp(prefix="v12_")
    with open(os.path.join(d, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"games": {"1566200": {"filter": "sgsr"}}, "sgsr3": ["2050650"]}, f)
    return upscale.Upscaler(d, "/nonexistent", log=logs.append), d


# ---- A. xprop cannot read the root window
up, d = old_install()
world["xprop"] = (1, "")
r = up.restore_steam_filter()
check(f"A1 xprop failed: nothing is pushed to Gamescope ({pushed})", pushed == [] and r is False)
check("A2 ... and the migration is still to do", up.reset_pending and not json.load(open(os.path.join(d, "settings.json")))
      .get("gamescope_reset"))
world["xprop"] = (0, "GAMESCOPE_NEW_SCALING_FILTER(CARDINAL) = 2\nGAMESCOPE_FSR_SHARPNESS(CARDINAL) = 3\n")
check("A3 xprop works again: Steam's own choice goes to Gamescope, once", up.restore_steam_filter() is True
      and pushed == [("scaling_filter", "fsr"), ("scaling_sharpness", "3")] and not up.reset_pending)
pushed.clear()
up, d = old_install()
world["xprop"] = (0, "GAMESCOPE_NEW_SCALING_FILTER:  not found.\nGAMESCOPE_FSR_SHARPNESS:  not found.\n")
check("A4 xprop ran and Steam never set a filter: Gamescope's default (linear, 2), as before", up.restore_steam_filter() is True
      and pushed == [("scaling_filter", "linear"), ("scaling_sharpness", "2")])
pushed.clear()

# ---- B. a tool is missing: 100 passes of the 10 s loop (almost 17 min)
world["xprop"] = (0, "GAMESCOPE_NEW_SCALING_FILTER(CARDINAL) = 2\n")
world["missing"] = True
up, d = old_install()
starts.clear()
logs.clear()
for _ in range(100):
    up.restore_steam_filter()
check(f"B1 100 passes with the tool missing: at most 10 process starts ({len(starts)})", 0 < len(starts) <= 10)
check(f"B2 ... and the reason is logged once, not on every pass ({len(logs)} lines)", 1 <= len(logs) <= 2)
check("B3 ... the migration is still to do", up.reset_pending)
world["missing"] = False
for _ in range(31):
    if up.restore_steam_filter():
        break
check("B4 the tools are there again (game mode): the migration happens within 5 min", not up.reset_pending and pushed[:1] == [("scaling_filter", "fsr")])
pushed.clear()

# ---- B'. desktop mode: gamescopectl fails
world["ctl"] = 1
up, d = old_install()
starts.clear()
for _ in range(100):
    up.restore_steam_filter()
check(f"B5 100 passes with Gamescope not up: at most 20 process starts ({len(starts)})", 0 < len(starts) <= 20 and up.reset_pending)
world["ctl"] = 0

# ---- C. a new install
d = tempfile.mkdtemp(prefix="v12n_")
new = upscale.Upscaler(d, "/nonexistent", log=logs.append)
new.set_sgsr3("870780", True)
again = upscale.Upscaler(d, "/nonexistent", log=logs.append)
starts.clear()
check("C1 a new install with a game set up: the migration never starts", not again.reset_pending and again.restore_steam_filter() is False and not starts)
d = tempfile.mkdtemp(prefix="v12o_")
with open(os.path.join(d, "settings.json"), "w", encoding="utf-8") as f:
    json.dump({"sgsr3": ["2050650"]}, f)    # 0.8.14: games Vela upscaled (Gamescope on Linear for them), no other old key
check("C2 a settings file of an older Vela with only the list of games still gets it", upscale.Upscaler(d, "/nonexistent", log=logs.append).reset_pending)
print("test_v12_filter_restore " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
