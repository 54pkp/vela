"""NOMSG (owner 2026-11-11 via the lead: «верни, не делайте особые сообщение для игр»): the plugin shows no game-specific message or hint.
No profile carries a message ("note", "hint", "menu_skip", or any other free-text key the panel could show); the menu hint is the generic text
for every game (Clair Obscur with FSR 3.1 + DLSS inputs gets "choose FSR 3.1 or DLSS" like any such game); main.py hands the panel the game's
scan as it is. Profiles keep only machine keys (settings, env, ini, game_cfg, flags)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import profiles  # noqa: E402
import sgsr3  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


MACHINE = {"name", "lines", "algo", "smooth", "nolock", "env", "ini", "game_cfg", "static_fsr2", "dx12_only", "speed", "follow"}
for appid, p in profiles.PROFILES.items():
    ok(set(p) <= MACHINE, (appid, sorted(set(p) - MACHINE)))
    for k in ("note", "hint", "menu_skip", "message", "text"):
        ok(k not in p, (appid, k))
    pub = json.dumps(profiles.public(appid), ensure_ascii=False)
    ok('"note"' not in pub and '"hint"' not in pub, (appid, "what the panel gets"))
ok(not hasattr(profiles, "menu_inputs"), "no per-game filter of the menu hint")
ok("1903340" not in profiles.PROFILES and "1903340" not in profiles.EXES.values(), "no Clair Obscur profile (CLR1 reverted)")
BOTH = ["FSR 3.1", "DLSS"]
for appid in ("1903340", "1091500", "548430", "999"):
    ok(sgsr3.menu_hint({"appid": appid, "inputs": BOTH}) == "choose FSR 3.1 or DLSS", (appid, sgsr3.menu_hint({"appid": appid, "inputs": BOTH})))
src = open(os.path.join(HERE, "..", "main.py"), encoding="utf-8").read()
ok("menu_inputs" not in src and "menu_skip" not in src, "main.py gives the panel the scan as it is")
print(f"test_no_game_messages: {checks} checks, 0 failed")
