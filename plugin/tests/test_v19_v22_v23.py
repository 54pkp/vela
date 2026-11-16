"""Three small audit findings (AUD1/audit_plugin.md, 2026-11-09), one section each. Run: python -I tests/test_v19_v22_v23.py [v19|v22|v23]
(VELA_PYMOD=<another py_modules>: the old code fails the section of a finding it does not have).
V19  a game settings file the player made read-only stays read-only after Vela wrote its keys (a rename ignores the target's mode: the file
     came back writable and the game rewrote it at exit, the player's tweaks were lost).
V22  a report upload that never reached the relay (Wi-Fi off) does not use up the hourly limit; one the relay answered does.
V23  a failed automatic update check (no network 60 s after boot) is tried again after an hour, not after a day."""
import io
import json
import os
import stat
import sys
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
only = sys.argv[1] if len(sys.argv) > 1 else ""
fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="v19_")

if only in ("", "v19"):
    import gamecfg  # noqa: E402
    ini = os.path.join(tmp, "GameUserSettings.ini")
    with open(ini, "w", newline="") as f:
        f.write("[ScalabilityGroups]\r\nsg.ResolutionQuality=100\r\nDLSSEnabled=True\r\n")
    os.chmod(ini, stat.S_IREAD)                      # the player's read-only file
    f0 = {"path": ini, "format": "ini", "section": "ScalabilityGroups", "want": {"DLSSEnabled": "False"}}
    try:
        out = gamecfg.GameCfg._apply(dict(f0))
    except PermissionError as e:                      # the old code on Windows: the rename over a read-only file fails outright
        out = None; print("old code:", type(e).__name__)
    out = out or {"orig": {}}
    text = open(ini, newline="").read()
    check("v19 1 Vela's key is written into the read-only file", "DLSSEnabled=False" in text and out["orig"] == {"DLSSEnabled": "True"})
    check("v19 2 the file is still read-only afterwards (was: writable, the game rewrote it at exit)", not os.access(ini, os.W_OK))
    try:
        gamecfg.GameCfg._apply({**f0, "want": {"DLSSEnabled": "True"}, "orig": out["orig"]}, restore=True)
    except PermissionError:
        pass
    check("v19 3 the restore writes the player's value back and the file stays read-only", "DLSSEnabled=True" in open(ini, newline="").read() and not os.access(ini, os.W_OK))
    rw = os.path.join(tmp, "rw.ini")
    with open(rw, "w", newline="") as f:
        f.write("[S]\nA=1\n")
    gamecfg.GameCfg._apply({"path": rw, "format": "ini", "section": "S", "want": {"A": "2"}})
    check("v19 4 a writable file stays writable; no temporary file is left", os.access(rw, os.W_OK) and not [n for n in os.listdir(tmp) if n.endswith(".vela-tmp")])
    os.chmod(ini, stat.S_IREAD | stat.S_IWRITE)

if only in ("", "v22"):
    import report  # noqa: E402
    clock = [1_800_000_000.0]
    mode = {"how": "down"}
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    def urlopen(req, **kw):
        calls.append(mode["how"])
        if mode["how"] == "down":
            raise urllib.error.URLError("Network is unreachable")
        if mode["how"] == "relay429":
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b'{"error":"busy"}'))
        return Resp(b'{"ok": true, "id": "VELA-ABC123"}')

    settings = os.path.join(tmp, "settings")
    R = report.Reporter(settings, os.path.join(tmp, "home"), os.path.join(tmp, "plugin"), log=lambda *a: None, now=lambda: clock[0], urlopen=urlopen)
    R._ssl = "CTX"
    R._write("report.json", {"relay_url": "http://relay.test/upload"})

    def saved(i):
        lid = f"870780-20261110-0101{i:02d}"   # the id form Reporter.record accepts
        R._write(lid + ".json", {"id": lid, "status": "saved", "meta": {"plugin": "0.8.22"}})
        with open(R._path(lid + ".zip"), "wb") as f:
            f.write(b"PK\x03\x04zip")
        return lid

    left0 = R.rate_left() if hasattr(R, "rate_left") else None
    for i in range(3):                               # Wi-Fi off, "Send" three times
        try:
            R.send(saved(i))
        except RuntimeError as e:
            assert str(e).startswith("network:"), e
        clock[0] += 5
    check(f"v22 1 three tries with the network down: the hourly limit is untouched ({len(R.sent_times())} counted, want 0)", len(R.sent_times()) == 0 and R.rate_wait_s() == 0)
    mode["how"] = "ok"
    try:
        rid = R.send(saved(9)).get("report_id")
    except RuntimeError as e:
        rid = str(e)
    check(f"v22 2 Wi-Fi back: the fourth try goes out at once ({rid})", rid == "VELA-ABC123" and len(R.sent_times()) == 1)
    mode["how"] = "relay429"
    try:
        R.send(saved(10))
    except RuntimeError as e:
        pass
    check("v22 3 a try the relay itself refused still counts (its limit is protected)", len(R.sent_times()) == 2)
    mode["how"] = "ok"
    try:
        R.send(saved(11))
    except RuntimeError:
        pass
    clock[0] += 5
    try:
        R.send(saved(12)); lim = ""
    except RuntimeError as e:
        lim = str(e)
    check("v22 4 after three tries that reached the relay: rate limited, as before", lim.startswith("rate_limited:"))

if only in ("", "v23"):
    import updater as U  # noqa: E402
    plug = os.path.join(tmp, "plug"); os.makedirs(plug, exist_ok=True)
    with open(os.path.join(plug, "package.json"), "w") as f:
        json.dump({"version": "0.8.21"}, f)

    class Clock:
        t = 1_800_000_000.0

        def __call__(self):
            return self.t

    clock = Clock()
    net = {"up": False, "n": 0}

    class R2(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    def urlopen(req, **kw):
        net["n"] += 1
        if not net["up"]:
            raise urllib.error.URLError("Temporary failure in name resolution")
        return R2(json.dumps({"tag_name": "v0.8.21", "assets": [], "draft": False, "prerelease": False}).encode())

    up = U.Updater(os.path.join(tmp, "upd"), plug, log=lambda *_: None, urlopen=urlopen, now=clock, ssl_context=lambda: "CTX")
    st = up.check()                                   # the automatic check 60 s after boot, no Wi-Fi yet
    check("v23 1 the failed check is reported, not raised", net["n"] == 1 and st.get("error"))
    clock.t += 600
    check("v23 2 ten minutes later: not due yet (no hammering)", up.due() is False)
    clock.t += 3600
    due = up.due()
    check("v23 3 an hour after the failure: due again (was: 24 h later)", due is True)
    net["up"] = True
    up.check()
    check("v23 4 that try goes out and clears the error", net["n"] == 2 and not up.state().get("error"))
    clock.t += 3600 * 2
    check("v23 5 after a good check the next one is a day later, as before", up.due() is False)
    clock.t += U.CHECK_EVERY
    check("v23 6 ... and due after a day", up.due() is True)

print("test_v19_v22_v23 " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
