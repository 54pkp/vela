"""V06 / V07 / V16 (audit 2026-11-09): the panel's own races.
V06  (a) two one-time fixes scheduled in one render both saw `busy` false, read the same Steam launch options and both wrote them: the last
     write dropped the other's edit. (b) Until a newly opened game's state arrived, the previous game's state (its window_fix / layer_on
     flags) acted on the new appid; the backend's _window_fix answered "Default" for any game.
V07  each step of the sharpness slider read the options and called the backend on its own: overlapping calls with stale options.
V16  setInterval started a state poll every 1.5 s whether or not the last one had come back.
Three parts: (1) src/serial.ts compiled with the TypeScript of the bench's node_modules and run under Node (tests/panel_serial_test.cjs);
(2) src/index.tsx really uses it (source checks); (3) the backend guard of _window_fix.
Run: python -I tests/test_v06_v07_v16_panel.py     (VELA_TEST_ROOT=<another plugin tree>: the old code fails)
Needs node and VELA_BENCH_NODE_MODULES (default C:/src/ext/vela7/appsFT3/decky-upscale/node_modules); without them part 1 is reported as SKIPPED."""
import os
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("VELA_TEST_ROOT") or os.path.join(HERE, "..")
NM = os.environ.get("VELA_BENCH_NODE_MODULES") or "C:/src/ext/vela7/appsFT3/decky-upscale/node_modules"
fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="v06_")
# ---- 1. the helper under Node
ts = os.path.join(ROOT, "src", "serial.ts")
node = shutil.which("node")
if not os.path.isfile(ts):
    check("1 src/serial.ts exists (the panel's queue, latest-wins sender and poll chain)", False)
elif not node or not os.path.isdir(os.path.join(NM, "typescript")):
    print("SKIPPED part 1: node or typescript not found (VELA_BENCH_NODE_MODULES)")
else:
    out = os.path.join(tmp, "serial.cjs")
    comp = ("const ts=require(process.argv[1]);const fs=require('fs');const r=ts.transpileModule(fs.readFileSync(process.argv[2],'utf8'),"
            "{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,strict:true},reportDiagnostics:true});"
            "if(r.diagnostics&&r.diagnostics.length){console.error(JSON.stringify(r.diagnostics.map(d=>d.messageText)));process.exit(2)}"
            "fs.writeFileSync(process.argv[3],r.outputText)")
    c = subprocess.run([node, "-e", comp, os.path.join(NM, "typescript"), ts, out], capture_output=True, text=True)
    check(f"1 src/serial.ts compiles ({(c.stderr or '').strip()[:120] or 'no diagnostics'})", c.returncode == 0)
    if c.returncode == 0:
        r = subprocess.run([node, os.path.join(HERE, "panel_serial_test.cjs"), out], capture_output=True, text=True, timeout=120)
        for ln in r.stdout.strip().split("\n"):
            print("  node:", ln)
        check("2 the Node run of the three race scenarios passes (15 checks above)", r.returncode == 0 and "panel_serial_test OK" in r.stdout)

# ---- 2. the panel uses it
src = open(os.path.join(ROOT, "src", "index.tsx"), encoding="utf-8").read()
check("3 V06a: `run` goes through the module's queue, the one-time fixes are queued", "serial.run(async () => {" in src and src.count("}, true), 0);") >= 2
      and "if (busy) return;" not in src)
check("4 V06b: nothing is rendered or fixed until the state belongs to the game shown", "gsApp !== game.appid" in src and "setGsApp(g.appid)" in src)
# NOFSR (2026-11-11): the any-game sharpness slider left with FSR 4 for any game; no slider makes calls of its own (makeLatest stays in
# serial.ts, tested above, for the next slider)
check("5 V07: no slider of its own calls (the any-game slider is gone, nothing ad hoc)", "SliderField" not in src and "sharpPush" not in src
      and "launchOptions(game.appid).then(async (launch) => {" not in src)
check("6 V16: the poll is a chain, no setInterval(load", "makePoll(load, 1500)" in src and "setInterval(load" not in src)

# ---- 3. the backend: _window_fix only for a game that is set up
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
decky = types.ModuleType("decky")
decky.logger = types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None, exception=lambda *a: None)
decky.DECKY_USER_HOME = os.path.join(tmp, "home")
decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(tmp, "settings")
sys.modules["decky"] = decky
sys.path.insert(0, ROOT)
import gameutil  # noqa: E402
import main  # noqa: E402

gameutil.running_appids = lambda proc="/proc": set()
P = main.Plugin()
P._win_restart = set()
P.s3 = types.SimpleNamespace(status=lambda appid, *a, **k: {"installed": appid == "100"})
check("7 a set-up game: Steam's window back to Default, as before", P._window_fix("100") == {"resolution": "Default"})
check(f"8 a game Vela is not set up in: nothing to set ({P._window_fix('200')})", P._window_fix("200") == {"resolution": None})
print("test_v06_v07_v16_panel " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
