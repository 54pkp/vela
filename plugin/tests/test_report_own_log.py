"""RPT4 (2026-11-11, player reports VELA-S2BCUW / VELA-TGEMQ4): only the reported run's own OptiScaler log is attached. S2BCUW's log was
13 h older than the run (a Vela-off run: OptiScaler never loaded), TGEMQ4's was an earlier attempt's. A log that ended before the run
started (RPT5's run record) is not attached and the report says so; a log of the run itself is attached as before."""
import json
import os
import sys
import tempfile
import time
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
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)


class S3:
    def __init__(self, logs):
        self.logs_dir = logs

    def scan(self, appid):
        return {}

    def kit(self, appid):
        return {"log": "OptiScaler.log", "static": None}


tmp = tempfile.mkdtemp(prefix="vela-rptown-")
APP = "1174180"
logs = os.path.join(tmp, "logs")
t = lambda s: time.mktime(time.strptime(s, "%Y%m%d%H%M%S"))  # noqa: E731
old_log = os.path.join(logs, f"{APP}-20261109-000043.log")
write(old_log, "[23:59:50.000] [I] OptiScaler init\n[00:00:43.000] [I] last line\n")
clock = [t("20261109134200")]
settings = os.path.join(tmp, "settings")
R = report.Reporter(settings, tmp, tmp, s3=S3(logs), now=lambda: clock[0], proc=os.path.join(tmp, "noproc"),
                    runner=lambda *a, **k: (_ for _ in ()).throw(OSError("no tool")))
# the run record of the reported run (RPT5): started 13:38:54 with Vela off, ended 13:39:20
write(os.path.join(settings, "reports", "run_starts.json"),
      json.dumps([{"appid": APP, "at": int(t("20261109133854")), "end": int(t("20261109133920")),
                   "cmd": "/usr/libexec/armada/armada-game-launch /x/RDR2.exe", "vela": False}]))


def build():
    p = R.build(APP, "crash", "", "/usr/libexec/armada/armada-game-launch %command%", None, "RDR2")
    z = zipfile.ZipFile(os.path.join(settings, "reports", p["id"] + ".zip"))
    clock[0] += 1
    return z, json.loads(z.read("meta.json"))


# S2BCUW: the newest log is 13 h older than the run: not attached
z, meta = build()
txt = z.read("optiscaler.log").decode()
ok(txt.startswith("no OptiScaler log of this run") and "last line" not in txt, txt)
ok(any(e.startswith("no OptiScaler log of this run") for e in meta["errors"]), meta["errors"])
ok(meta["log"].startswith("none"), meta["log"])
ok(meta["window"][0] == int(t("20261109133854") - report.WINDOW_BEFORE)
   and meta["window"][1] == int(t("20261109133920") + report.WINDOW_AFTER), meta["window"])
ok(meta["vela_in_run"] is False, meta["vela_in_run"])

# the run's own log (it ended after the run started): attached as before
own = os.path.join(logs, f"{APP}-20261109-133918.log")
write(own, "[13:38:58.000] [I] OptiScaler init\n[13:39:18.000] [I] last line of this run\n")
z, meta = build()
ok("last line of this run" in z.read("optiscaler.log").decode(), "own log attached")
ok(not any(e.startswith("no OptiScaler log") for e in meta["errors"]) and meta["log"] == os.path.basename(own), meta["log"])
print(f"test_report_own_log: {checks} checks, 0 failed")
