"""RPT3 (2026-11-11, player report VELA-9F3B4B): one NPU timeout the layer recovered from (errors 0, the run went on: 6 600 jobs, NPU
"on, exact" again 0.2 s later) is no bad run: the panel does not ask "Send a report?" for it (the player sent "crash" with no text). Two
timeouts, or any NPU error, still ask. The flag itself stays in the report."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import report  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


LOG = "[22:28:35.000] [I] init\n[22:32:41.000] [I] last\n"
# 9F3B4B: one timeout, no error, a long run
fl = report.assess(LOG, {}, [], {"timeouts": 1, "errors": 0, "jobs": 6600}, False, 439)
ok(not fl["bad"] and fl["why"] == [], fl["why"])
ok(fl["npu_errors"] == 1 and fl["npu_timeouts"] == 1, "the flag stays in the report")
# two timeouts: asks
fl = report.assess(LOG, {}, [], {"timeouts": 2, "errors": 0, "jobs": 6600}, False, 439)
ok(fl["bad"] and "npu_errors" in fl["why"], fl["why"])
# one timeout and one NPU error: asks
fl = report.assess(LOG, {}, [], {"timeouts": 1, "errors": 1, "jobs": 6600}, False, 439)
ok(fl["bad"] and "npu_errors" in fl["why"], fl["why"])
# an error without a timeout: asks
fl = report.assess(LOG, {}, [], {"timeouts": 0, "errors": 1, "jobs": 600}, False, 439)
ok(fl["bad"] and "npu_errors" in fl["why"], fl["why"])
# one timeout plus another sign (an NPU fallback state): asks for that sign, not for the timeout
fl = report.assess(LOG, {"npu": {"state": "fallback", "reason": "error"}}, [], {"timeouts": 1, "errors": 0}, False, 439)
ok(fl["bad"] and fl["why"] == ["npu_fallback"], fl["why"])
# no NPU layer at all: unchanged
fl = report.assess(LOG, {}, [], None, False, 439)
ok(not fl["bad"] and fl["npu_errors"] == 0 and fl["npu_timeouts"] == 0, fl)
print(f"test_report_one_timeout: {checks} checks, 0 failed")
