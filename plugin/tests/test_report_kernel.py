"""RPT6 (2026-11-11): kernel_gpu.txt was 1 byte in all 7 player reports. On the console the plugin (root) reads the kernel journal fine
(2026-11-11: 968 kernel lines in 2 h, GPU faults / hangcheck visible), and two reports had a wrong window (RPT1), so an empty file could
mean "no access", "wrong window" or "the kernel said nothing about the GPU". Its first line now says which: the window, how many kernel
lines it held and how many are about the GPU; meta.json gets kernel_lines; a failed journalctl says "not readable"."""
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


class Done:
    def __init__(self, out):
        self.returncode, self.stdout = 0, out


AUDIT = ["2026-11-11T10:34:14+01:00 armada kernel: audit: type=2407 audit(1794389654.227:154460): pid=327976 uid=0",
         "2026-11-11T10:34:15+01:00 armada kernel: kauditd_printk_skb: 12 callbacks suppressed"]
FAULT = ["2026-11-11T10:43:38+01:00 armada kernel: adreno 3d00000.gpu: [drm:a6xx_irq] *ERROR* gpu fault ring 2 fence f0c817"]
kern = {"lines": AUDIT + FAULT}


def runner(args, **kw):
    if args[0] == "journalctl" and "_TRANSPORT=kernel" in args:
        if kern["lines"] is None:
            raise OSError("journalctl failed")
        return Done("\n".join(kern["lines"]) + "\n")
    if args[0] == "journalctl":
        return Done("")
    raise OSError("no tool")


tmp = tempfile.mkdtemp(prefix="vela-rptk-")
clock = [1794390000.0]
R = report.Reporter(os.path.join(tmp, "settings"), tmp, tmp, runner=runner, now=lambda: clock[0], proc=os.path.join(tmp, "np"))


def build():
    p = R.build("548430", "crash", "", "%command%", None, "DRG")
    clock[0] += 1
    z = zipfile.ZipFile(os.path.join(tmp, "settings", "reports", p["id"] + ".zip"))
    return z.read("kernel_gpu.txt").decode(), json.loads(z.read("meta.json"))


txt, meta = build()
head = txt.splitlines()[0]
ok(head.startswith("# kernel journal ") and "3 kernel lines in the run window, 1 about the GPU / display" in head, head)
ok("gpu fault ring 2" in txt and meta["kernel_lines"] == 3, (txt, meta.get("kernel_lines")))
kern["lines"] = AUDIT  # lines, none about the GPU
txt, meta = build()
ok("2 kernel lines in the run window, 0 about the GPU / display (none: no GPU hang" in txt.splitlines()[0], txt)
ok(meta["kernel_lines"] == 2 and len(txt.splitlines()) == 1, meta.get("kernel_lines"))
kern["lines"] = []  # nothing at all in the window (no access, or a quiet kernel): the old error note stays
txt, meta = build()
ok("0 kernel lines in the run window" in txt and any("kernel journal empty" in e for e in meta["errors"]), (txt, meta["errors"]))
kern["lines"] = None  # journalctl fails
txt, meta = build()
ok(txt.startswith("# kernel journal not readable") and "kernel journal not readable" in meta["errors"], (txt, meta["errors"]))
print(f"test_report_kernel: {checks} checks, 0 failed")
