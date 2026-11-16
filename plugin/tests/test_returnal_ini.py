"""fgtest7 (report 9NPQFQ): Returnal (1649240) gets upstream OptiScaler's own Dxgi=false, as Cyberpunk 2077 does: our explicit
Dxgi=true reset the fork's DisableDxgiSpoofing quirk (dllmain.cpp: the quirk only applies when the ini has no Dxgi value), the game took
its Streamline DLSS-G / Reflex path and died before any upscaler call. Every other game keeps Dxgi=true. Run: python -I tests/test_returnal_ini.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
import profiles  # noqa: E402
import sgsr3  # noqa: E402

with open(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini"), encoding="utf-8", newline="") as f:
    TPL = f.read()


def section_value(text, section, key):
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1].lower()
        elif cur == section.lower() and "=" in s and s.split("=", 1)[0].strip().lower() == key.lower():
            return s.split("=", 1)[1].strip()
    return None


assert profiles.ini_overrides("1649240") == {("Spoofing", "Dxgi"): "false"}
assert profiles.ini_overrides(1649240) == {("Spoofing", "Dxgi"): "false"}
assert profiles.env_tokens("1649240") == []  # no env for Returnal
v = sgsr3.ini_values({"appid": "1649240"})
assert v[("Spoofing", "Dxgi")] == "false"
assert v[("Spoofing", "StreamlineSpoofing")] == "true"  # Streamline spoofing stays: it opens DLSS inputs without GPU spoofing
assert section_value(sgsr3.make_ini(TPL, {"appid": "1649240"}), "Spoofing", "Dxgi") == "false"
# others unchanged
for other in ("870780", "1178830", "553420", ""):
    assert sgsr3.ini_values({"appid": other})[("Spoofing", "Dxgi")] == "true", other
assert section_value(sgsr3.make_ini(TPL, {"appid": "1178830"}), "Spoofing", "Dxgi") == "true"
# the panel's view of the profile (tuple keys joined, json-safe)
import json  # noqa: E402
pp = profiles.panel_profile("1649240") if hasattr(profiles, "panel_profile") else None
if pp is not None:
    json.dumps(pp)
    assert pp["ini"] == {"Spoofing.Dxgi": "false"}, pp
print("PASS test_returnal_ini")
