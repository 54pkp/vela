"""RPT2 (2026-11-11, player report VELA-H63SA7): npu_errors counts only the reported run's own NPU session (the last process in the
NPU layer's log). H63SA7's flag 'npu_errors 2' came from the previous, healthy run (pid 22202, 33 000 jobs, 2 timeouts); the reported
run (pid 29888) used no NPU job at all."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import npu  # noqa: E402
import report  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


PREV = ("Vela NPU layer: loaded v11\nVela NPU layer: loaded v11\n"
        "[vela-npu 22202 3317802.232] device 0xfffd8413fcb0 created (layer build 11): dma-buf import on\n"
        "Vela NPU layer: 600 jobs, HTP 3.60 ms, timeouts 0, errors 0\n"
        "[vela-npu 22202 3318000.100] job seq 2221 slot 3: pack-done event not seen in 200 ms\n"
        "Vela NPU layer: 33000 jobs, HTP 3.90 ms, timeouts 2, errors 0\n"
        "[vela-npu 22202 3350000.000] [vela-npu exit] signal 15\n")
CUR = ("Vela NPU layer: loaded v11\nVela NPU layer: loaded v11\n"
       "[vela-npu 29888 4694522.936] device 0xffff98392750 created (layer build 11): dma-buf import on\n"
       "[vela-npu 29888 4724206.943] device 0xfffe98042590 created (layer build 11): dma-buf import on\n")

# the session cut
ok(report.npu_session(PREV + CUR) == CUR, "the last process with its 'loaded' lines")
ok(report.npu_session(PREV) == PREV, "one session: all of it")
ok(report.npu_session("Vela NPU layer: loaded v11\n") == "Vela NPU layer: loaded v11\n", "no process ids: as it is")
ok(report.npu_session("") == "" and report.npu_session(None) is None, "empty / none")

# the flag: the old whole-log count said 2, this run's count says 0
whole = npu.parse_layer(PREV + CUR)
ok((whole["timeouts"] or 0) == 2, "whole log: the previous run's 2 timeouts")
mine = npu.parse_layer(report.npu_session(PREV + CUR))
fl = report.assess("[21:41:02.000] [I] x\n[21:41:32.870] [I] y\n", {}, [], mine, False, 116)
ok(fl["npu_errors"] == 0 and "npu_errors" not in fl["why"], fl)
# a timeout inside the reported run still counts
ERR = CUR + "Vela NPU layer: 600 jobs, HTP 3.6 ms, timeouts 0, errors 3\n"
fl = report.assess("", {}, [], npu.parse_layer(report.npu_session(PREV + ERR)), False, 900)
ok(fl["npu_errors"] == 3 and "npu_errors" in fl["why"], fl)
print(f"test_report_npu_session: {checks} checks, 0 failed")
