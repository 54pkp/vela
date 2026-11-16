"""V01 (audit 2026-11-09): Off must not wipe launch options the player added while Vela was on.
Before: `launch_set` was renewed on every re-enable, `launch_prev` was not; Off took the shortcut "Steam's options == launch_set -> give back
launch_prev" and returned the options of the FIRST On. Scenario: on with empty options, the player adds -windowed in Steam, moves the sharpness
slider (a re-enable), presses Off: -windowed was gone. Same through npu.enable (called on every model pick in a copy-mode game).
Run: python -I tests/test_v01_launch_prev.py     (VELA_PYMOD=<another py_modules> runs it on that code: the old code fails)"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
import launchopts  # noqa: E402
import npu  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="v01_")
home, settings = os.path.join(tmp, "home"), os.path.join(tmp, "settings")
# 1-4 (the lp0 layer's Off) left with frame generation (NOFG 2026-11-15): tests/test_nofg.py

# 5. the NPU layer (copy-mode games; enable runs on every model pick)
assets = os.path.join(tmp, "plugin", "assets", "npu")
os.makedirs(assets)
open(os.path.join(assets, npu.LIB), "wb").write(b"so")
with open(os.path.join(ROOT, "assets", "npu", npu.MANIFEST), "rb") as f:
    open(os.path.join(assets, npu.MANIFEST), "wb").write(f.read())
n = npu.Npu(assets, home, settings, log=lambda *_: None, proc_net_unix=os.path.join(tmp, "none"), systemctl=lambda u: "inactive",
            graph_dir=os.path.join(tmp, "graphs"))
lo1 = n.enable("20", "%command%")
edited = lo1 + " -windowed"
lo2 = n.enable("20", edited)
check("5a npu: the re-enable keeps the player's token", "-windowed" in launchopts.words(lo2))
off = n.disable("20", lo2)
check(f"5b npu: edit, model pick, Off: -windowed stays ({off!r})", off == "%command% -windowed")
lo1 = n.enable("21", "FOO=1 %command%")
check("6 npu: no edit, Off: exactly the old options", n.disable("21", n.enable("21", lo1)) == "FOO=1 %command%")
print("test_v01_launch_prev " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
