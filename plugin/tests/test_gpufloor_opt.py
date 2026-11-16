"""GPF1: the GPU floor is off by default, an opt-in setting (lead 2026-11-09, the owner: «Почему вела не может работать как задумано
в режиме баланс от 220 до 600?»). Fake devfreq node. Run: python -I tests/test_gpufloor_opt.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import gpufloor  # noqa: E402

MHZ = 1_000_000
tmp = tempfile.mkdtemp(prefix="opt_floor_")
node = os.path.join(tmp, "devfreq", "3d00000.gpu")
os.makedirs(node)
fails = []


def put(name, v):
    with open(os.path.join(node, name), "w") as f:
        f.write(f"{v}\n")


def get():
    with open(os.path.join(node, "min_freq")) as f:
        return int(f.read().strip())


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


put("available_frequencies", "220000000 295000000 348000000 401000000 475000000 550000000 615000000 680000000")
put("max_freq", 680 * MHZ); put("cur_freq", 220 * MHZ); put("governor", "simple_ondemand"); put("min_freq", 220 * MHZ)
kw = {"devfreq_glob": os.path.join(tmp, "devfreq", "*.gpu"), "sleep": lambda s: None,
      "profiles": (os.path.join(tmp, "none.conf"),), "powerd_state": os.path.join(tmp, "none.state")}


def make(name, data=None):
    d = os.path.join(tmp, name)
    if data is not None:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "gpufloor.json"), "w") as f:
            json.dump(data, f)
    logs = []
    return gpufloor.GpuFloor(d, log=logs.append, **kw), logs, d


# 1. a fresh install: Vela on for TUNIC, the game runs: no floor
fl, _, _ = make("c1")
fl.enable("553420")
fl.reconcile({"553420"})
check(f"1 fresh install, game running: min_freq {get() // MHZ} (want 220, no floor)", get() == 220 * MHZ)
check("1b status says off, the game's value kept", fl.status("553420")["opt_in"] is False and fl.status("553420")["mhz"] == 680)
# 2. an older gpufloor.json (no opt_in key, games at 680): off too
fl, _, _ = make("c2", data={"games": {"553420": {"on": True, "mhz": 680}}, "applied": None})
fl.reconcile({"553420"})
check(f"2 older settings file: min_freq {get() // MHZ} (want 220)", get() == 220 * MHZ)
# 3. opt in: the floor as before (680 while the game runs, back after)
fl.set_opt_in(True, {"553420"})
check(f"3a opt in, game running: {get() // MHZ} (want 680)", get() == 680 * MHZ)
fl.reconcile(set())
check(f"3b game quit: {get() // MHZ} (want 220)", get() == 220 * MHZ)
# 4. the setting persists across a plugin restart
fl2, _, d2 = make("c2")
check("4 opt_in persisted", fl2.data["opt_in"] is True)
# 5. opt out while the floor is applied: restored at once
fl2.reconcile({"553420"})
a = get()
fl2.set_opt_in(False, {"553420"})
check(f"5 opt out while applied: {a // MHZ} -> {get() // MHZ} (want 680 -> 220)", a == 680 * MHZ and get() == 220 * MHZ)
with open(os.path.join(d2, "gpufloor.json")) as f:
    check("5b saved off", json.load(f)["opt_in"] is False)
# 6. an older Vela left its floor applied ("applied" in the file), now off: the first reconcile restores it
put("min_freq", 680 * MHZ)
fl, logs, _ = make("c6", data={"games": {"553420": {"on": True, "mhz": 680}}, "applied": {"hz": 680 * MHZ, "prev": 220 * MHZ}})
fl.reconcile(set())
check(f"6 an applied floor from an older Vela, setting off: restored to {get() // MHZ}", get() == 220 * MHZ and fl.data["applied"] is None)
# 7. a non-bool opt_in in the file is off
fl, _, _ = make("c7", data={"games": {}, "applied": None, "opt_in": "yes"})
check("7 opt_in 'yes' (not true) reads as off", fl.data["opt_in"] is False)
print("test_gpufloor_opt " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
