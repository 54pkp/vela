"""fgtest7: gpufloor restores the system's own floor, not a boost read (console 2026-11-09: the user floor 220 became 550 for good).
Before: the apply step read min_freq until the first value below the target; a driver boost below it (550 < 680) ended the
reads, "prev" was 550 and the restore wrote 550 as the user floor. Fake devfreq node; the msm boost QoS is simulated by a
wrapped open() (a read returns max(user floor, boost)). Run: python -I tests/test_gpufloor_base.py
(GPUFLOOR_SRC=<file> runs the same checks on another gpufloor.py, e.g. the old one, which must fail case 1.)"""
import builtins
import importlib.util
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("GPUFLOOR_SRC") or os.path.join(HERE, "..", "py_modules", "gpufloor.py")
spec = importlib.util.spec_from_file_location("gpufloor_t", SRC)
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
tmp = tempfile.mkdtemp(prefix="base_floor_")
state = {"boost": []}   # boost values the next min_freq reads see (one per read); [] = no boost
real_open = builtins.open


def fake_open(path, mode="r", *a, **k):
    if str(path).endswith("min_freq") and "r" in mode and state["boost"]:
        b = state["boost"].pop(0)
        with real_open(path, *a, **k) as f:
            v = int(f.read().strip())
        return io.StringIO(f"{max(v, b)}\n")
    return real_open(path, mode, *a, **k)


gpufloor.open = fake_open
node = os.path.join(tmp, "devfreq", "3d00000.gpu")
os.makedirs(node)


def put(name, v):
    with real_open(os.path.join(node, name), "w") as f:
        f.write(f"{v}\n")


def get(name):
    with real_open(os.path.join(node, name)) as f:
        return int(f.read().strip())


put("available_frequencies", FREQS); put("max_freq", 680 * MHZ); put("cur_freq", 680 * MHZ); put("governor", "simple_ondemand")
now = [1000.0]
kw = {"devfreq_glob": os.path.join(tmp, "devfreq", "*.gpu"), "sleep": lambda s: None}
try:
    kw_clock = {"clock": lambda: now[0]}
    gpufloor.GpuFloor(os.path.join(tmp, "probe"), log=lambda *_: None, **kw, **kw_clock)
except TypeError:   # the old module has no clock argument
    kw_clock = {}


def make(name):
    fl = gpufloor.GpuFloor(os.path.join(tmp, name), log=lambda *_: None, **kw, **kw_clock)
    fl.enable("1178830")
    return fl


def cycle(fl, boost_at_apply):
    """idle reconcile (game not running), then the game runs (boost reads at the apply), then the game quits."""
    fl.reconcile(set())
    state["boost"] = list(boost_at_apply)
    fl.reconcile({"1178830"}); state["boost"] = []
    assert get("min_freq") == 680 * MHZ, get("min_freq")
    fl.reconcile(set())
    return get("min_freq")


# 1. the console case: user floor 220, the first read at the apply shows a 550 boost (below the 680 target): back to 220
put("min_freq", 220 * MHZ)
r = cycle(make("c1"), [550 * MHZ])
assert r == 220 * MHZ, f"case 1: restored {r // MHZ} MHz, the user floor was 220 (a boost read became the baseline)"
# 2. every read during the apply is boosted (busy GPU while the game starts): the idle read wins
put("min_freq", 220 * MHZ)
r = cycle(make("c2"), [550 * MHZ] * 12)
assert r == 220 * MHZ, f"case 2: restored {r // MHZ}"
# 3. a profile floor (powerd, 295) is the system's own: restored to it, not lower
put("min_freq", 295 * MHZ)
r = cycle(make("c3"), [550 * MHZ])
assert r == 295 * MHZ, f"case 3: restored {r // MHZ}"
# 4. ten cycles in a row with boosts: no drift upward
put("min_freq", 220 * MHZ)
fl = make("c4")
for i in range(10):
    assert cycle(fl, [550 * MHZ, 615 * MHZ][: 1 + i % 2]) == 220 * MHZ, i
# 5. an idle read older than IDLE_MAX_AGE_S is not used: the full set of reads decides (here unboosted: 220)
if kw_clock:
    put("min_freq", 220 * MHZ)
    fl = make("c5"); fl.reconcile(set())
    put("min_freq", 348 * MHZ)            # the system's floor changed long after the idle read
    now[0] += gpufloor.IDLE_MAX_AGE_S + 1
    fl.reconcile({"1178830"}); assert fl.data["applied"]["prev"] == 348 * MHZ, fl.data["applied"]
    fl.reconcile(set()); assert get("min_freq") == 348 * MHZ
gpufloor.open = builtins.open
print("test_gpufloor_base OK")
