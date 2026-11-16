"""fgtest8b: gpufloor never restores above armada-powerd's floor, and repairs a floor an older Vela left raised.
Console 2026-11-09 (fgtest8, gpufloor fafc065e): Balanced, gpu_min 0, no game running, min_freq 615; the plugin log has
"680 -> 615 (restored)" at 15:28 and 15:51. The 550 left by fgtest6 was above the real floor (220); every read is
max(floor, boost), so the fgtest7 rule (lowest read) kept 550 and, with the boost holding every read, wrote 615.
Fake devfreq node + fake power-profiles.conf / powerd.state; the msm boost QoS is simulated by a wrapped open().
Run: python -I tests/test_gpufloor_profile.py   (GPUFLOOR_SRC=<file> runs it on another gpufloor.py: the fgtest7 one
fafc065e must fail case 1.)"""
import builtins
import importlib.util
import io
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("GPUFLOOR_SRC") or os.path.join(HERE, "..", "py_modules", "gpufloor.py")
spec = importlib.util.spec_from_file_location("gpufloor_p", SRC)
gpufloor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpufloor)

# GPF1: the floor is off by default (an opt-in setting); these checks are the floor's own rules, so they run with it on
if hasattr(gpufloor.GpuFloor, "set_opt_in"):
    _gf_init = gpufloor.GpuFloor.__init__
    def _gf_init_on(self, *a, **k):
        _gf_init(self, *a, **k)
        self.data["opt_in"] = True
    gpufloor.GpuFloor.__init__ = _gf_init_on

FREQS = "220000000 295000000 348000000 401000000 475000000 550000000 615000000 680000000"
MHZ = 1_000_000
FACTORY = """[general]
default_profile=balanced

[profile.eco]
gpu_max=0.80
gpu_min=0.0

[profile.balanced]
gpu_max=1.0
gpu_min=0.0

[profile.performance]
gpu_max=1.0
gpu_min=1.0
"""
tmp = tempfile.mkdtemp(prefix="prof_floor_")
state = {"boost": []}   # boost the next min_freq reads see (one value per read); [] = none
real_open = builtins.open
fails = []


def fake_open(path, mode="r", *a, **k):
    if str(path).endswith("min_freq") and "r" in mode and state["boost"]:
        b = state["boost"].pop(0) if len(state["boost"]) > 1 or not state.get("hold") else state["boost"][0]
        with real_open(path, *a, **k) as f:
            v = int(f.read().strip())
        return io.StringIO(f"{max(v, b)}\n")
    return real_open(path, mode, *a, **k)


gpufloor.open = fake_open
node = os.path.join(tmp, "devfreq", "3d00000.gpu")
os.makedirs(node)
factory, user, pstate = (os.path.join(tmp, n) for n in ("factory.conf", "user.conf", "powerd.state"))


def put(path, text):
    with real_open(path, "w") as f:
        f.write(text)


def node_put(name, v):
    put(os.path.join(node, name), f"{v}\n")


def get():
    with real_open(os.path.join(node, "min_freq")) as f:
        return int(f.read().strip())


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


put(factory, FACTORY)
node_put("available_frequencies", FREQS); node_put("max_freq", 680 * MHZ); node_put("cur_freq", 680 * MHZ)
node_put("governor", "simple_ondemand")
kw = {"devfreq_glob": os.path.join(tmp, "devfreq", "*.gpu"), "sleep": lambda s: None, "clock": lambda: 1000.0}
kw_prof = {"profiles": (factory, user), "powerd_state": pstate, "device_env": lambda: {"ARMADA_GPU_STOCK_MAX_MHZ": "680"}}
try:
    gpufloor.GpuFloor(os.path.join(tmp, "probe"), log=lambda *_: None, **kw, **kw_prof)
except TypeError:   # an older gpufloor.py: no profile arguments (it must fail case 1)
    kw_prof = {}


def make(name, games=True, data=None):
    d = os.path.join(tmp, name)
    if data is not None:
        os.makedirs(d, exist_ok=True)
        put(os.path.join(d, "gpufloor.json"), json.dumps(data))
    logs = []
    fl = gpufloor.GpuFloor(d, log=logs.append, **kw, **kw_prof)
    if games:
        fl.enable("1178830")
    return fl, logs


def cycle(fl, boost_at_apply=(), boost_idle=(), hold=False):
    """idle reconcile, the game runs (boost reads at the apply), the game quits."""
    state["boost"], state["hold"] = list(boost_idle), hold
    fl.reconcile(set())
    state["boost"], state["hold"] = list(boost_at_apply), hold
    fl.reconcile({"1178830"})
    state["boost"], state["hold"] = list(boost_at_apply), hold
    applied = get()
    fl.reconcile(set())
    state["boost"], state["hold"] = [], False
    return applied, get()


put(pstate, "profile=balanced\ngpu_level=auto\nmanual_gpu_clock=0\n")
# 1. the console's 550 (left by fgtest6), Balanced gpu_min 0: back to 220, not 550 (fgtest7 restored 550)
node_put("min_freq", 550 * MHZ)
fl, _ = make("c1", data={"games": {}, "applied": None, "floor_v": 2})
a, r = cycle(fl)
check(f"1 floor 550 left by an older Vela, Balanced: game {a // MHZ}, restored {r // MHZ} (want 680, 220)",
      a == 680 * MHZ and r == 220 * MHZ)
# 2. the console's 615: the boost holds every read at 615 (idle and apply) over the 550 floor: 220, not 615
node_put("min_freq", 550 * MHZ)
fl, _ = make("c2", data={"games": {}, "applied": None, "floor_v": 2})
a, r = cycle(fl, boost_at_apply=[615 * MHZ], boost_idle=[615 * MHZ], hold=True)
check(f"2 floor 550 + boost 615 on every read: restored {r // MHZ} (want 220)", r == 220 * MHZ)
# 3. a "prev" saved by fgtest7 (applied {hz 680, prev 615}): the restore writes the profile floor
node_put("min_freq", 680 * MHZ)
fl, logs = make("c3", games=False, data={"games": {"1178830": {"on": True, "mhz": 680}},
                                         "applied": {"hz": 680 * MHZ, "prev": 615 * MHZ}, "floor_v": 2})
fl.reconcile(set())
check(f"3 saved prev 615 from fgtest7: restored {get() // MHZ} (want 220); log {logs[-1:]}", get() == 220 * MHZ)
if kw_prof:
    # 4. the one-time repair on the first run of fgtest8b: a fgtest7 gpufloor.json (games, no floor_v), min 615 idle
    node_put("min_freq", 615 * MHZ)
    fl, logs = make("c4", games=False, data={"games": {"1178830": {"on": True, "mhz": 680}}, "applied": None})
    fl.reconcile(set())
    check(f"4 first run, idle 615 left by fgtest7: repaired to {get() // MHZ} (want 220); log {logs[-1:]}",
          get() == 220 * MHZ and any("repair" in m for m in logs))
    # 5. ... once: a later 615 nobody recorded as Vela's (a user's or a tool's) stays
    node_put("min_freq", 615 * MHZ)
    fl.reconcile(set())
    check(f"5 after the one-time repair, an unrecorded 615 stays: {get() // MHZ}", get() == 615 * MHZ)
    # 6. a value Vela wrote (in "wrote") and left above the profile floor is repaired at any later idle reconcile
    fl.data["wrote"] = [615 * MHZ]
    fl.reconcile(set())
    check(f"6 a recorded Vela value 615 at idle: repaired to {get() // MHZ}", get() == 220 * MHZ)
    # 7. never a repair without a floor user: a fresh install (no games) leaves the floor alone
    node_put("min_freq", 401 * MHZ)
    fl, _ = make("c7", games=False)
    fl.reconcile(set())
    check(f"7 no floor user, idle 401: left {get() // MHZ}", get() == 401 * MHZ)
    # 8. manual GPU level (userspace) / another governor: no profile floor, no repair
    put(pstate, "profile=balanced\ngpu_level=manual\nmanual_gpu_clock=401\n")
    node_put("min_freq", 401 * MHZ)
    fl, _ = make("c8", games=False, data={"games": {"1178830": {"on": True, "mhz": 680}}, "applied": None})
    fl.reconcile(set())
    check(f"8 manual GPU level: left {get() // MHZ}", get() == 401 * MHZ and fl.profile_floor() == 0)
    put(pstate, "profile=balanced\ngpu_level=auto\n")
    node_put("governor", "performance")
    fl, _ = make("c8b", games=False, data={"games": {"1178830": {"on": True, "mhz": 680}}, "applied": None})
    fl.reconcile(set())
    check(f"8b governor performance: left {get() // MHZ}", get() == 401 * MHZ)
    node_put("governor", "simple_ondemand")
    # 9. the profile floor follows powerd's rules: gpu_min_mhz in /etc wins, ratio of the stock top, gpu_max cap
    node_put("min_freq", 220 * MHZ)
    fl, _ = make("c9", games=False)
    put(user, "[profile.balanced]\ngpu_min_mhz=300\n")
    check(f"9a /etc gpu_min_mhz=300 -> step {fl.profile_floor() // MHZ} (want 295)", fl.profile_floor() == 295 * MHZ)
    put(user, "[profile.balanced]\ngpu_min=0.5\n")
    check(f"9b gpu_min 0.5 of stock 680 -> {fl.profile_floor() // MHZ} (want 295)", fl.profile_floor() == 295 * MHZ)
    put(user, "")
    put(pstate, "profile=performance\ngpu_level=auto\n")
    check(f"9c Performance gpu_min 1.0 -> {fl.profile_floor() // MHZ} (want 680)", fl.profile_floor() == 680 * MHZ)
    put(pstate, "profile=eco\ngpu_level=auto\n")
    put(user, "[profile.eco]\ngpu_min=1.0\n")
    check(f"9d Eco gpu_min 1.0 capped by gpu_max 0.8 -> {fl.profile_floor() // MHZ} (want 475)",
          fl.profile_floor() == 475 * MHZ)
    put(user, ""); put(pstate, "")
    check(f"9e no powerd.state: default_profile balanced -> {fl.profile_floor() // MHZ}", fl.profile_floor() == 220 * MHZ)
    # 10. a profile floor above the old floor (Eco gpu_min_mhz 295): restored to 295, as powerd would
    put(user, "[profile.balanced]\ngpu_min_mhz=295\n")
    node_put("min_freq", 295 * MHZ)
    fl, _ = make("c10")
    a, r = cycle(fl, boost_at_apply=[550 * MHZ])
    check(f"10 profile floor 295: restored {r // MHZ}", r == 295 * MHZ)
    put(user, "")
    # 11. no profile files (not Armada): the fgtest7 rule alone, unchanged
    fl2 = gpufloor.GpuFloor(os.path.join(tmp, "c11"), log=lambda *_: None, **kw,
                            profiles=(os.path.join(tmp, "none.conf"),), powerd_state=pstate)
    fl2.enable("1178830")
    node_put("min_freq", 348 * MHZ)
    a, r = cycle(fl2, boost_at_apply=[550 * MHZ])
    check(f"11 no profile files: restored {r // MHZ} (the fgtest7 rule: 348)", r == 348 * MHZ and fl2.profile_floor() == 0)
    # 12. ten cycles with boosts from a raised start: settles at 220 after the first and stays (no ratchet)
    node_put("min_freq", 550 * MHZ)
    fl, _ = make("c12", data={"games": {}, "applied": None, "floor_v": 2})
    rs = [cycle(fl, boost_at_apply=[615 * MHZ], boost_idle=[615 * MHZ], hold=True)[1] // MHZ for _ in range(10)]
    check(f"12 ten boosted cycles: {rs}", rs == [220] * 10)
gpufloor.open = builtins.open
print("test_gpufloor_profile " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
