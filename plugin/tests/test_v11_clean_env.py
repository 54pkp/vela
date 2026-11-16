"""V11 (audit 2026-11-09): every helper program the plugin starts gets an environment without Decky's own library path.
Decky's frozen Python exports LD_LIBRARY_PATH (its bundled libraries), LD_PRELOAD, PYTHONHOME and PYTHONPATH to the plugin process.
systemctl, journalctl, xprop and gamescopectl were already started without them (npu.py, report.py, upscale.py); the bwrap probe of the
overlay (velakit.probe_game), `bash` for powerd's device-env (gpufloor) and `sg` (gpufloor, cpuboost) were not. With a Decky that runs
natively on arm64 the system programs can load those bundled libraries: bwrap fails to start, the probe says "no overlay" for every game
and each new setup silently copies files into the game folder. (Today the console's Decky is an x86-64 program under FEX: its libraries
cannot be loaded by the system's arm64 programs, so nothing breaks yet.)
Run: python -I tests/test_v11_clean_env.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
BAD = {"LD_LIBRARY_PATH": "/tmp/_MEIabc", "LD_PRELOAD": "/tmp/_MEIabc/libx.so", "PYTHONHOME": "/tmp/_MEIabc", "PYTHONPATH": "/tmp/_MEIabc/lib"}
os.environ.update(BAD)
os.environ["VELA_KEEP_ME"] = "1"
import cpuboost  # noqa: E402
import gpufloor  # noqa: E402
import velakit  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def clean(kw):
    env = kw.get("env")
    return isinstance(env, dict) and not any(k in env for k in BAD) and env.get("VELA_KEEP_ME") == "1" and "PATH" in env


tmp = tempfile.mkdtemp(prefix="v11_")
seen = {}


def runner(name, out=b""):
    def run(cmd, **kw):
        seen[name] = (cmd, kw)
        return types.SimpleNamespace(returncode=0, stdout=out, stderr=b"")
    return run


real_open = open


def refusing_open(path, mode="r", *a, **kw):
    if "w" in mode and str(path).endswith(("min_freq", "scaling_max_freq")):
        raise PermissionError(13, "Permission denied")
    return real_open(path, mode, *a, **kw)


# 1. the overlay probe (bwrap)
game, work, scratch = (os.path.join(tmp, n) for n in ("game", "work", "scratch"))
os.makedirs(game)
ok, why = velakit.probe_game(game, work, scratch, run=runner("bwrap"), bwrap="/usr/bin/bwrap")
check(f"1 the overlay probe ran ({why!r}) and bwrap got a clean environment", ok and "bwrap" in seen and clean(seen["bwrap"][1]))

# 2. gpufloor: powerd's device-env through bash
dev_env = os.path.join(tmp, "device-env")
with open(dev_env, "w") as f:
    f.write("#!/bin/sh\n")
gpufloor.DEVICE_ENV = dev_env
fl = gpufloor.GpuFloor(os.path.join(tmp, "s"), log=lambda *a: None, runner=runner("bash", b"ARMADA_GPU_STOCK_MAX_MHZ=680\n"),
                       sg="/usr/bin/sg", devfreq_glob=os.path.join(tmp, "none", "*.gpu"), sleep=lambda s: None)
fl._stock_max([220000000, 680000000])
check("2 gpufloor: bash for device-env got a clean environment", "bash" in seen and seen["bash"][0][0] == "bash" and clean(seen["bash"][1]))

# 3. gpufloor: the write through sg
fl._run = runner("sg_gpu")
fl._sg_group = lambda p: "wheel"
gpufloor.open = refusing_open
mf = os.path.join(tmp, "min_freq")
with real_open(mf, "w") as f:
    f.write("220000000\n")
fl._write(mf, 680000000)
check("3 gpufloor: sg got a clean environment", "sg_gpu" in seen and seen["sg_gpu"][0][0] == "/usr/bin/sg" and clean(seen["sg_gpu"][1]))

# 4. cpuboost: the write through sg
pol = os.path.join(tmp, "policy7")
os.makedirs(pol)
with real_open(os.path.join(pol, "scaling_max_freq"), "w") as f:
    f.write("2092800\n")
cb = cpuboost.CpuBoost(os.path.join(tmp, "s4"), log=lambda *a: None, policy=pol, runner=runner("sg_cpu"), sg="/usr/bin/sg",
                       sg_group=lambda p: "wheel")
cpuboost.open = refusing_open
cb._write(2400000)
check("4 cpuboost: sg got a clean environment", "sg_cpu" in seen and seen["sg_cpu"][0][0] == "/usr/bin/sg" and clean(seen["sg_cpu"][1]))
print("test_v11_clean_env " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
