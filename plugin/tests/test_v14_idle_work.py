"""V14 (audit 2026-11-09): no full check of every set-up game on every 10 s pass, for ever.
Before, for each closed game Vela is set up in, every pass ran keep_runs + refresh_dll: every kit file md5-compared, the 1546-line ini template
rebuilt with ~36 passes and compared, the game folder walked again whenever the 120 s scan cache was old; plus a second /proc scan per pass
(gamecfg.has_pending is true whenever a state file exists) and a worker thread every 2 s for the CPU guard with no cap applied.
Now: the full check once at plugin start, once when the game leaves the running set, every IDLE_FULL_EVERY passes, and at once when a kit file
changed (kit_unchanged: one stat per file); one /proc scan per pass; the CPU guard only while a cap is applied.
The test runs the REAL loop for 60 passes and counts; then measures both checks on a real overlay setup.
Run: python -I tests/test_v14_idle_work.py     (VELA_TEST_ROOT=<another plugin tree>: the old code fails)"""
import asyncio
import os
import shutil
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("VELA_TEST_ROOT") or os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
tmp = tempfile.mkdtemp(prefix="v14_")
decky = types.ModuleType("decky")
decky.logger = types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None, exception=lambda *a: None)
decky.DECKY_USER_HOME = os.path.join(tmp, "home")
decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(tmp, "settings")


async def _emit(*a):
    return None
decky.emit = _emit
sys.modules["decky"] = decky
sys.path.insert(0, ROOT)
import gameutil  # noqa: E402
import launchopts  # noqa: E402
import main  # noqa: E402
import sgsr3  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


count = {}
running = set()


def scan(proc="/proc"):
    count["proc_scan"] = count.get("proc_scan", 0) + 1
    return set(running)


gameutil.running_appids = scan


class Quiet:
    rotated = []
    reset_pending = False
    cfg = {"sgsr3": ["4242", "4243"]}
    data = {"applied": None}

    def __getattr__(self, name):
        if name.startswith("has_"):
            return lambda *a, **k: True          # as on a console with a game-settings state file: always "pending"
        return lambda *a, **k: None


class S3(Quiet):
    changed = set()

    def keep_runs(self, appid, r):
        count[f"keep_runs {appid}"] = count.get(f"keep_runs {appid}", 0) + 1

    def refresh_dll(self, appid):
        count[f"refresh {appid}"] = count.get(f"refresh {appid}", 0) + 1
        self.changed.discard(appid)

    def kit_unchanged(self, appid):
        count[f"stat {appid}"] = count.get(f"stat {appid}", 0) + 1
        return appid not in self.changed


passes = [0]
real_sleep = asyncio.sleep


async def loop_sleep(s, *a, **k):
    if s >= 10:
        passes[0] += 1
    return await real_sleep(0.001 if s >= 2 else s)


async def run_loop(P, n, at=None):
    """the real reconcile loop for n passes; at = {pass number: fn} to change the world before that pass"""
    passes[0] = 0
    main.asyncio.sleep = loop_sleep
    t = asyncio.ensure_future(P._reconcile_loop())
    seen = set()
    try:
        while passes[0] <= n:
            for k, fn in (at or {}).items():
                if passes[0] >= k and k not in seen:
                    seen.add(k); fn()
            await real_sleep(0.0005)
    finally:
        t.cancel()
        main.asyncio.sleep = real_sleep


def plugin():
    P = main.Plugin()
    for m in ("floor", "cpu", "rep", "live", "lat", "ag", "cfg", "npu", "upd"):
        setattr(P, m, Quiet())
    P.up = Quiet()
    P.s3 = S3()
    return P


# ---- 1. two closed set-up games, 60 passes (10 minutes of an idle console)
count.clear()
asyncio.run(run_loop(plugin(), 60))
r, k = count.get("refresh 4242", 0), count.get("keep_runs 4242", 0)
check(f"1 60 idle passes: the full check of a closed game runs {r} times (was once per pass = 60+); want <= 4", 1 <= r <= 4 and 1 <= k <= 4)
check(f"2 one /proc scan per pass ({count.get('proc_scan', 0)} scans in 60+ passes; was 2 per pass)", count.get("proc_scan", 0) <= 66)
# ---- 2. the game runs, then closes: its log is kept and the kit checked at once
count.clear()
running.clear()
P = plugin()
asyncio.run(run_loop(P, 20, {5: lambda: running.add("4242"), 12: lambda: running.discard("4242")}))
check(f"3 a game that ran and closed gets the full check again right after it closes (keep_runs {count.get('keep_runs 4242', 0)}, the other game {count.get('keep_runs 4243', 0)})",
      count.get("keep_runs 4242", 0) == 2 and count.get("keep_runs 4243", 0) == 1)
# ---- 3. a kit file changes while the game is closed (another plugin's uninstall in the same folder): repaired on the next pass
count.clear()
P = plugin()
asyncio.run(run_loop(P, 12, {6: lambda: P.s3.changed.add("4243")}))
check(f"4 a changed kit file is found by the stats and repaired at once (refresh {count.get('refresh 4243', 0)}, log kept {count.get('keep_runs 4243', 0)} time)",
      count.get("refresh 4243", 0) == 2 and count.get("keep_runs 4243", 0) == 1 and count.get("refresh 4242", 0) == 1)


# ---- 4. the 2 s CPU guard: a worker thread only while a cap is applied
async def guard(applied, n=30):
    P = plugin()
    P.cpu = Quiet()
    P.cpu.data = {"applied": applied}
    calls = []
    P.cpu.guard = lambda fn: calls.append(1)
    main.asyncio.sleep = loop_sleep
    t = asyncio.ensure_future(P._cpuboost_loop())
    try:
        await real_sleep(0.3)
    finally:
        t.cancel()
        main.asyncio.sleep = real_sleep
    return len(calls)
check(f"5 CPU guard with no cap applied: no worker thread ({asyncio.run(guard(None))} calls)", asyncio.run(guard(None)) == 0)
check("6 CPU guard with a cap applied: it runs", asyncio.run(guard({"hz": 2476800})) > 3)

# ---- 5. the real checks on a real overlay setup: what the stats replace
def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
home = os.path.join(tmp, "home")
assets = os.path.join(tmp, "assets", "sgsr3")
for a in ("OptiScaler.dll", "OptiPatcher.asi"):
    write(os.path.join(assets, a), b"asset " + a.encode() * 5000)
shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini"), assets)
shutil.copy(os.path.join(ROOT, "assets", "sgsr3", "VERSION.json"), assets)
settings = os.path.join(tmp, "settings")
lib = os.path.join(home, ".local", "share", "Steam")
write(os.path.join(lib, "steamapps", "libraryfolders.vdf"), '"libraryfolders" { "0" { "path" "%s" } }' % lib.replace("\\", "/"))
write(os.path.join(lib, "steamapps", "appmanifest_4242.acf"), '"AppState" { "appid" "4242" "name" "Ov Game" "installdir" "OvGame" }')
g = os.path.join(lib, "steamapps", "common", "OvGame")
write(os.path.join(g, "OvGame.exe"), b"stub" * 100)
write(os.path.join(g, "OvGame", "Binaries", "Win64", "OvGame-Win64-Shipping.exe"), b"x" * 2000)
write(os.path.join(g, "Engine/Plugins/Runtime/Nvidia/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll"), b"dlss")
s3 = sgsr3.Sgsr3(assets, home, settings, log=lambda *a: None)
s3.probe = lambda exe, w, scratch: (True, "")
s3.new_mode = "launcher"
s3.enable("4242", {}, launchopts.CMD)
if hasattr(s3, "kit_unchanged"):
    check("7 never checked in this plugin run: not 'unchanged' (the full check runs first)", s3.kit_unchanged("4242") is False)
    s3.refresh_dll("4242")
    check("8 after the full check: unchanged", s3.kit_unchanged("4242") is True)
    kit = os.path.join(settings, "kits", "4242", "files")
    ini = os.path.join(kit, "OptiScaler.ini")
    good = open(ini, "rb").read()
    open(ini, "wb").write(b"[Log]\nLogLevel=1\n")                       # another plugin's ini
    check("9 the ini replaced by another plugin's: seen by the stats", s3.kit_unchanged("4242") is False)
    check("10 ... and the full check puts Vela's ini back", s3.refresh_dll("4242") is True and open(ini, "rb").read() == good and s3.kit_unchanged("4242"))
    dll = os.path.join(kit, "dxgi.dll")
    os.rename(dll, dll + ".gone")
    check("11 a kit file removed: seen, put back", s3.kit_unchanged("4242") is False and s3.refresh_dll("4242") is True and os.path.exists(dll) and s3.kit_unchanged("4242"))
    t0 = time.perf_counter()
    for _ in range(20):
        s3.cache.clear(); s3.refresh_dll("4242")
    full = (time.perf_counter() - t0) / 20
    t0 = time.perf_counter()
    for _ in range(20):
        s3.kit_unchanged("4242")
    quick = (time.perf_counter() - t0) / 20
    print(f"INFO on this PC (tiny fake game folder): full check {full * 1000:.2f} ms, stats {quick * 1000:.3f} ms per game per pass")
    check(f"12 the stats are at least 5x cheaper than the full check ({full / max(quick, 1e-9):.0f}x)", quick * 5 < full)
else:
    check("7 Sgsr3.kit_unchanged exists", False)
print("test_v14_idle_work " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
