"""RPT5 (2026-11-11, player reports VELA-9F3B4B / PGEA74 / S2BCUW / TGEMQ4): the report's launch options are the reported run's, read
when the run STARTED (Steam's launch as it ran, from its SteamLaunch process), not at Send (the player had turned Vela off or on since),
and the report says whether Vela was in that run (meta vela_in_run, run_start)."""
import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import report  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


tmp = tempfile.mkdtemp(prefix="vela-rptstart-")
proc = os.path.join(tmp, "proc")
APP = "1903340"
ON = ("~/.local/share/vela/bin/vela-launch /usr/libexec/armada/armada-game-launch /x/proton waitforexitandrun "
      "Z:/g/Sandfall-Win64-Shipping.exe -dx12")
OFF = "/usr/libexec/armada/armada-game-launch /x/proton waitforexitandrun Z:/g/Sandfall-Win64-Shipping.exe"


def game_runs(cmd, pid="4242"):
    words = ["reaper", "SteamLaunch", f"AppId={APP}", "--", "/steam/steam-launch-wrapper", "--"] + cmd.split(" ")
    write(os.path.join(proc, pid, "cmdline"), "\0".join(words).encode() + b"\0")


def game_gone(pid="4242"):
    os.replace(os.path.join(proc, pid), os.path.join(tmp, f"gone-{pid}-{len(os.listdir(tmp))}"))


# launch_command / vela_in_cmd
os.makedirs(proc)
write(os.path.join(proc, "1", "cmdline"), b"/sbin/init\0")
ok(report.launch_command(APP, proc) is None, "not running")
game_runs(ON)
ok(report.launch_command(APP, proc) == "/steam/steam-launch-wrapper -- " + ON, report.launch_command(APP, proc))
ok(report.vela_in_cmd(ON) is True and report.vela_in_cmd(OFF) is False and report.vela_in_cmd(None) is None, "vela marks")
ok(report.vela_in_cmd("VELA_NPU=1 LP0_ENABLE=1 %command%") is True, "any-game line")
game_gone()

clock = [1794340000.0]
logged = []
R = report.Reporter(os.path.join(tmp, "settings"), tmp, tmp, log=logged.append, now=lambda: clock[0], proc=proc,
                    runner=lambda *a, **k: (_ for _ in ()).throw(OSError("no tool")))
# the plugin starts while nothing runs; a Vela run starts and ends; then the player turns Vela off and starts again (Vela off)
R.observe([])
game_runs(ON)
clock[0] += 5
R.observe([APP])
clock[0] += 300
game_gone()
R.observe([])
recs = json.load(open(os.path.join(tmp, "settings", "reports", "run_starts.json"), encoding="utf-8"))
ok(len(recs) == 1 and recs[0]["vela"] is True and recs[0]["at"] == 1794340005 and recs[0]["end"] == 1794340305, recs)
ok(ON in recs[0]["cmd"], recs[0]["cmd"])
clock[0] += 100
game_runs(OFF, "5151")
R.observe([APP])
clock[0] += 21
game_gone("5151")
R.observe([])
ok(R.run_start(APP)["vela"] is False and R.run_start(APP)["at"] == 1794340405, R.run_start(APP))
ok(R.run_start(APP, before=1794340310)["vela"] is True, "a kept log's run: the record that started before its end")
# a game that ran before the plugin started gets no record (its start is unknown)
R2 = report.Reporter(os.path.join(tmp, "s2"), tmp, tmp, now=lambda: clock[0], proc=proc)
game_runs(ON, "6000")
R2.observe([APP])
ok(R2.run_start(APP) is None, "no record without a seen start")
game_gone("6000")

# the report: launch_options.txt has the start's launch AND the Send's; meta says Vela was off in the reported (last) run
clock[0] += 600
p = R.build(APP, "crash", "", "/usr/libexec/armada/armada-game-launch ~/.local/share/optiscaler/optiscaler-launch.sh %command%",
            None, "Clair Obscur")
z = zipfile.ZipFile(os.path.join(tmp, "settings", "reports", p["id"] + ".zip"))
lo = z.read("launch_options.txt").decode()
meta = json.loads(z.read("meta.json"))
ok("at the run's start" in lo and "Sandfall-Win64-Shipping.exe" in lo and "vela-launch" not in lo.split("at Send")[0], lo)
ok("at Send" in lo and "optiscaler-launch.sh" in lo, lo)
ok(meta["vela_in_run"] is False and meta["run_start"] == 1794340405, {k: meta.get(k) for k in ("vela_in_run", "run_start")})
print(f"test_report_run_start: {checks} checks, 0 failed")
