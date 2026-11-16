"""V04 (audit 2026-11-09): the live files in /tmp come back when something removes them while the plugin runs.
/tmp/vela-live/<appid>.ini carries the model and the NPU keys (launch options carry none since 0.8.15). Before, it was written only at plugin
start (restore_all) and on a change (Live.set). systemd-tmpfiles removes /tmp files not used for 10 days (a console suspended and resumed
without a reboot): the next start of that game ran the default model on the GPU while the panel showed the stored one. The same gap for the
any-game layer's lp_<appid>.ini (sync_live only at plugin start).
Now the 10 s loop calls Live.ensure and AnyFsr4.ensure_live: one stat per game, a missing file is written again, an existing one is never touched.
Run: python -I tests/test_v04_live_tmp.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="v04_")
live.TMP_DIR = os.path.join(tmp, "vela-live")
settings = os.path.join(tmp, "settings")
logs = []
lv = live.Live(settings, log=logs.append)
lv.set("100", {"model": "fsr4", "npu": 1})
lv.set("200", {"model": "sgsr2"})
ini = lambda a: os.path.join(live.TMP_DIR, f"{a}.ini")
want100 = open(ini("100")).read()
assert "model=fsr4" in want100 and "npu=1" in want100

if hasattr(lv, "ensure"):
    check("1 both files there: nothing written, nothing logged", lv.ensure() == [] and not [m for m in logs if "gone" in m])
    os.rename(ini("100"), ini("100") + ".cleaned")           # /tmp cleanup took one game's file
    back = lv.ensure()
    check("2 the missing file is written again with the stored model and NPU key", back == ["100"] and open(ini("100")).read() == want100)
    check("3 one log line says so", len([m for m in logs if "100" in m and "gone" in m]) == 1)
    open(ini("200"), "w").write("model=fsr4\n")              # a file that exists is the game's / a run's: never rewritten
    check("4 an existing file is left as it is", lv.ensure() == [] and open(ini("200")).read() == "model=fsr4\n")
    lv.set("200", {"model": None})                           # the player went back to the launch settings: no stored values
    check("5 a game with no stored values gets no file", lv.ensure() == [] and not os.path.exists(ini("200")))
    os.rename(live.TMP_DIR, live.TMP_DIR + ".gone")          # the whole folder gone
    check("6 the folder itself gone: made again", lv.ensure() == ["100"] and open(ini("100")).read() == want100)
else:
    check("1 Live.ensure exists", False)
# the stored JSON is written through a temporary file + rename
lv.set("300", {"model": "fsr4"})
check("7 no half-written JSON left behind, the stored values read back", not [n for n in os.listdir(lv.dir) if n.endswith(".new")] and lv.get("300") == {"model": "fsr4"})
if hasattr(lv, "_write_json"):
    real = json.dump
    try:
        json.dump = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            lv.set("300", {"model": "sgsr2"})
        except OSError:
            pass
    finally:
        json.dump = real
    check("8 a write that fails half-way keeps the old stored values (was: an empty file = no settings)", lv.get("300") == {"model": "fsr4"})
else:
    check("8 Live._write_json exists (atomic write)", False)

# 9-11 (the lp0 layer's live file, ensure_live) left with frame generation (NOFG 2026-11-15): tests/test_nofg.py C
print("test_v04_live_tmp " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
