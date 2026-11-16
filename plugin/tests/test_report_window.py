"""RPT1 (2026-11-11, player reports VELA-HRD5X7 / VELA-PGEA74): the run window of a report comes from the kept run's file name
(<appid>[-layer]-YYYYMMDD-HHMMSS.log, local time of the run's end), not from the file's mtime: HRD5X7's window was 2026-10-17 for a run
of 2026-11-10, PGEA74's landed on the Send 20 min after the run, so kernel_gpu.txt / gamescope.txt missed the run."""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import report  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


tmp = tempfile.mkdtemp(prefix="vela-rptwin-")
now = time.mktime(time.strptime("20261111005500", "%Y%m%d%H%M%S"))
rep = report.Reporter(tmp, tmp, tmp, now=lambda: now)

# the name parser
end = time.mktime(time.strptime("20261110155203", "%Y%m%d%H%M%S"))
ok(report.run_end_from_name("1091500-20261110-155203.log") == end, "OptiScaler run name")
ok(report.run_end_from_name("1091500-layer-20261110-155203.log") == end, "layer run name")
for bad in ("OptiScaler.log", "1091500-OptiScaler.log", "live 1091500-20261110-155203.log", "x-20261110-155203.log",
            "1091500-20261310-155203.log", None, ""):
    ok(report.run_end_from_name(bad) is None, bad)

# HRD5X7: the kept file carries an old mtime; the window follows the name
p = os.path.join(tmp, "1091500-20261110-155203.log")
text = "[15:51:55.100] [I] Init\n[15:52:03.900] [I] last line\n"
with open(p, "w", encoding="utf-8") as f:
    f.write(text)
old = time.mktime(time.strptime("20261017020000", "%Y%m%d%H%M%S"))
os.utime(p, (old, old))
start, stop = rep.window(p, text)
ok(stop == int(end + report.WINDOW_AFTER), (stop, end))
ok(start == int(end - 8 - report.WINDOW_BEFORE), (start, end))
ok(start > old + 20 * 86400, "not the mtime's day")

# PGEA74: mtime NEWER than the run (touched at Send) -> still the run's own end
late = end + 20 * 60
os.utime(p, (late, late))
ok(rep.window(p, text)[1] == int(end + report.WINDOW_AFTER), "a later mtime does not move the window")

# a log without a run name (the game folder's OptiScaler.log): the mtime, as before
q = os.path.join(tmp, "OptiScaler.log")
with open(q, "w", encoding="utf-8") as f:
    f.write(text)
os.utime(q, (old, old))
ok(rep.window(q, text)[1] == int(old + report.WINDOW_AFTER), "no run name: mtime")
# a running game: now, as before
ok(rep.window(p, text, running=True)[1] == int(now + report.WINDOW_AFTER), "running: now")
print(f"test_report_window: {checks} checks, 0 failed")
