"""fgtest7: the dxgi_quirks.py mirror of OptiScaler's DisableDxgiSpoofing quirk (report 9NPQFQ, Returnal).
1. stale check: the list is generated from the Quirks.h of the shipped DLL's base (assets/sgsr3/VERSION.json "source"), and
   patch 0000 (upstream sync, the only fork patch that changes Quirks.h) is not in that build; when the fork repo is here
   (VELA_OPTI_REPO, default C:/src/ext/vela7/opti) the header at that base re-parses to the same sha1 and the same exes;
2. ini_values / make_ini: listed exes get Dxgi=false, others keep true, a profile "ini" wins (Control true, Cyberpunk false);
3. the kit's make_ini call (sgsr3._ini_text) passes the scanned exe.
Fix a failure with: python tools/gen_dxgi_quirks.py. Run: python -I tests/test_dxgi_quirks.py"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dxgi_quirks  # noqa: E402
import gen_dxgi_quirks as gen  # noqa: E402
import sgsr3  # noqa: E402

REGEN = " -> run: python tools/gen_dxgi_quirks.py"

# 1. stale check against what ships
base, patches = gen.build_base()
assert dxgi_quirks.BASE == base, f"dxgi_quirks.py is from {dxgi_quirks.BASE}, the DLL from {base}" + REGEN
assert "0000" not in patches, "patch 0000 (changes Quirks.h) is in the DLL build: regenerate from the patched header (--header)"
assert dxgi_quirks.ENTRIES >= 100 and len(dxgi_quirks.EXES) >= dxgi_quirks.ENTRIES, (dxgi_quirks.ENTRIES, len(dxgi_quirks.EXES))
repo = os.environ.get("VELA_OPTI_REPO", gen.DEFAULT_REPO)
data = gen.header_at(repo, base)
if data is None:
    print(f"note: no fork repo at {repo}: header re-parse skipped (VERSION.json base checked)")
else:
    assert hashlib.sha1(data).hexdigest() == dxgi_quirks.SOURCE_SHA1, "Quirks.h differs from the one the list came from" + REGEN
    entries, exes = gen.parse(data)
    assert (entries, frozenset(exes)) == (dxgi_quirks.ENTRIES, dxgi_quirks.EXES), "list differs from the header" + REGEN
    # the parser against a plain count: each DisableDxgiSpoofing in the table belongs to one entry
    table = gen._strip_comments(data.decode("utf-8", "replace"))
    table = table[table.find("quirkTable[]"):]
    table = table[:table.find("};")]
    assert entries == len(re.findall(r"GameQuirk::DisableDxgiSpoofing\b", table)), entries
    assert gen.render(base, dxgi_quirks.SOURCE_SHA1, entries, exes) == open(
        os.path.join(ROOT, "py_modules", "dxgi_quirks.py"), encoding="utf-8").read(), "dxgi_quirks.py edited by hand" + REGEN

# the matcher
for exe in ("Returnal-Win64-Shipping.exe", "returnal-wingdk-shipping.exe", "eldenring.exe", "re4.exe", "RE4.EXE",
            "D:/games/RE4/re4.exe", "C:\\Games\\Returnal\\Returnal\\Binaries\\Win64\\Returnal-Win64-Shipping.exe",
            "control_dx12.exe", "RDR2.exe", "Cyberpunk2077.exe"):  # Cyberpunk: flag on the entry's 2nd line
    assert dxgi_quirks.disables_dxgi(exe), exe
for exe in ("BrightMemoryInfinite-Win64-Shipping.exe", "returnal.exe", "", None):
    assert not dxgi_quirks.disables_dxgi(exe), exe


# 2. the ini
def dxgi(appid, exe):
    return sgsr3.ini_values({"appid": appid, "exe": exe})[("Spoofing", "Dxgi")]


assert dxgi("1649240", "Returnal-Win64-Shipping.exe") == "false"  # profile and list agree
assert dxgi("", "Returnal-Win64-Shipping.exe") == "false"  # list alone (no profile)
assert dxgi("2050650", "re4.exe") == "false"  # RE4: follows upstream (lead 2026-11-09)
assert dxgi("", "eldenring.exe") == "false"
assert dxgi("870780", "Control_DX12.exe") == "true"  # Control: profile keeps true over its quirk
assert dxgi("1091500", "Cyberpunk2077.exe") == "false"  # profile and list agree (upstream's own Dxgi=false)
assert dxgi("1178830", "BrightMemoryInfinite-Win64-Shipping.exe") == "true"
assert dxgi("553420", None) == "true" and dxgi("", "") == "true"  # no exe: as before
assert sgsr3.ini_values({"appid": "", "exe": "eldenring.exe"})[("Spoofing", "StreamlineSpoofing")] == "true"
with open(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini"), encoding="utf-8", newline="") as f:
    TPL = f.read()
ini = sgsr3.make_ini(TPL, {"appid": "2050650", "exe": "re4.exe"})
sec = re.search(r"^\[Spoofing\]\s*$(.*?)(?=^\[)", ini, re.S | re.M).group(1)
assert re.search(r"^Dxgi=false\s*$", sec, re.M), sec[:300]

# 3. the kit's make_ini calls pass the scanned exe
src = open(os.path.join(ROOT, "py_modules", "sgsr3.py"), encoding="utf-8").read()
calls = re.findall(r"make_ini\(f\.read\(\), \{[^}]*\}", src)
assert len(calls) == 1 and all('"exe": sc.get("exe")' in c for c in calls), calls
print(f"PASS test_dxgi_quirks ({dxgi_quirks.ENTRIES} entries, {len(dxgi_quirks.EXES)} exes, base {dxgi_quirks.BASE})")
