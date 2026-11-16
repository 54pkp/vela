"""V05 (audit 2026-11-09): one lock between the 10 s reconcile loop, the 2 s CPU guard and the panel's calls.
Before: the loop ran each step in a worker thread and every panel call ran in another, with no lock. The loop inside refresh_dll (state read,
ini being built) while the player pressed Off: disable restored the game's files and removed the backup folder, then the loop wrote
OptiScaler.ini and state.json again -> "set up" with no backup; the next pass copied Vela's DLLs over the game's own. Reporter.observe ran on
the event-loop thread and in panel threads on the same dicts.
The test runs the REAL loop with slow fake steps and a panel call at the same time and checks that their work never overlaps.
Run: python -I tests/test_v05_lock.py     (VELA_TEST_ROOT=<another plugin tree>: the old code fails)"""
import asyncio
import os
import sys
import tempfile
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("VELA_TEST_ROOT") or os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
tmp = tempfile.mkdtemp(prefix="v05_")
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
import main  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


gameutil.running_appids = lambda proc="/proc": set()
spans = []          # (who, start, end, thread id) of every piece of work on the shared states
mu = threading.Lock()


def work(who, secs):
    def fn(*a, **k):
        t0 = time.monotonic()
        time.sleep(secs)
        with mu:
            spans.append((who, t0, time.monotonic(), threading.get_ident()))
        return None
    fn.__name__ = who
    return fn


class Quiet:
    """every module the loop touches: nothing pending, nothing to do"""
    rotated = []
    reset_pending = False
    cfg = {"sgsr3": ["4242"]}

    def __getattr__(self, name):
        if name.startswith("has_"):
            return lambda *a, **k: False
        return lambda *a, **k: None


def plugin():
    P = main.Plugin()
    for m in ("floor", "cpu", "rep", "live", "lat", "ag", "cfg", "npu", "s3", "upd"):
        setattr(P, m, Quiet())
    P.up = Quiet()
    return P


def overlaps(a, b):
    return [(x[0], y[0]) for x in spans for y in spans if x[0] == a and y[0] == b and x[1] < y[2] and y[1] < x[2]]


real_sleep = asyncio.sleep


async def fast_sleep(s, *a, **k):      # the loop's 10 s / the guard's 2 s pauses, short
    return await real_sleep(0.02 if s >= 2 else s)


async def scenario_a():
    """the loop is inside refresh_dll of a closed game when the player presses Off (a panel call that changes the same state)"""
    P = plugin()
    P.s3.keep_runs = work("loop.keep_runs", 0.05)
    P.s3.refresh_dll = work("loop.refresh_dll", 0.25)
    main.asyncio.sleep = fast_sleep
    loop = asyncio.ensure_future(P._reconcile_loop())
    try:
        t0 = time.monotonic()
        while not any(s[0] == "loop.keep_runs" for s in spans) and time.monotonic() - t0 < 5:
            await real_sleep(0.01)                       # the pass is under way: refresh_dll is next / running
        await real_sleep(0.05)
        r = await P._run(work("panel.off", 0.1))
        await real_sleep(0.3)
    finally:
        loop.cancel()
        main.asyncio.sleep = real_sleep
    return r


async def scenario_c():
    """Reporter.observe (the loop, on the event-loop thread) and a panel call in a worker thread"""
    P = plugin()
    P.rep.observe = work("loop.observe", 0.0)
    P.up.cfg = {"sgsr3": []}
    main.asyncio.sleep = fast_sleep
    panel = asyncio.ensure_future(P._run(work("panel.state", 0.3)))
    await real_sleep(0.05)
    loop = asyncio.ensure_future(P._reconcile_loop())
    try:
        await panel
        await real_sleep(0.15)
    finally:
        loop.cancel()
        main.asyncio.sleep = real_sleep


async def scenario_poll():
    """a long call holds the lock; the panel's 1.5 s polls for the same game must not pile up behind it"""
    P = plugin()
    n = []
    P._game_state = lambda *a: (n.append(1), time.sleep(0.02), {"ok": 1})[2]
    long_call = asyncio.ensure_future(P._run(work("panel.long", 0.4)))
    await real_sleep(0.05)
    polls = [asyncio.ensure_future(P.game_state("4242", "Default")) for _ in range(6)]
    out = await asyncio.gather(*polls)
    await long_call
    return len(n), out


async def scenario_net():
    """the update check / report upload only talk to the network: they do not wait for the lock and do not hold it"""
    P = plugin()
    P.upd.check = work("net.update_check", 0.05)
    long_call = asyncio.ensure_future(P._run(work("panel.long2", 0.4)))
    await real_sleep(0.05)
    t0 = time.monotonic()
    await P.update_check()
    dt = time.monotonic() - t0
    await long_call
    return dt


spans.clear()
r = asyncio.run(scenario_a())
ov = overlaps("loop.refresh_dll", "panel.off") + overlaps("loop.keep_runs", "panel.off")
check(f"1 scenario A: the panel's Off never runs while the loop is inside refresh_dll / keep_runs (overlaps: {ov[:2]})",
      any(s[0] == "panel.off" for s in spans) and any(s[0] == "loop.refresh_dll" for s in spans) and not ov)
check("2 the panel call still answers", r == {"ok": True, "data": None})
spans.clear()
asyncio.run(scenario_c())
ov = overlaps("loop.observe", "panel.state")
obs = [s for s in spans if s[0] == "loop.observe"]
st = [s for s in spans if s[0] == "panel.state"]
check(f"3 scenario C: Reporter.observe of the loop never runs inside a panel call ({len(obs)} observes, overlaps {len(ov)})",
      bool(st) and bool(obs) and not ov and all(o[1] >= st[0][2] for o in obs))
if "launch" in main.Plugin.game_state.__code__.co_varnames:
    calls, out = asyncio.run(scenario_poll())
    check(f"4 six polls behind a long call: the state is computed once and every poll gets it ({calls} computations)",
          calls == 1 and all(o == {"ok": True, "data": {"ok": 1}} for o in out))
dt = asyncio.run(scenario_net())
check(f"5 an update check does not wait for a long panel call ({dt * 1000:.0f} ms, the long call takes 400)", dt < 0.25)
check("6 the lock is one object per plugin, made on first use", hasattr(main.Plugin, "_lk"))
print("test_v05_lock " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
