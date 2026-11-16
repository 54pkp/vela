"""BOARD row 57 (2026-11-10): Off puts back what the GAME changed because of Vela's key.
Deep Rock Galactic (FIN3 2026-11-03, console): Vela sets UpscalingType 0 -> 3 in GameUserSettings.ini; the game, started with it, rewrote two more keys of the same
section (AntiAliasingType 1 -> 2, TemporalAAUpsamplingEnabled False -> True). Off put back only Vela's own key: the player's anti-aliasing stayed changed.
Now the profile names those keys with the values the game gives them ("follow"); their values are noted the moment Vela takes its own key, and Off puts a key back
only when it holds the game's value and held another one before. A value the player chose himself meanwhile stays. A game set up before this change has no note:
nothing is guessed for it.
Run: python -I tests/test_follow_keys.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(HERE, "..", "py_modules"))
import gamecfg  # noqa: E402
import profiles  # noqa: E402

fails = []
SEC = "/Script/FSD.FSDGameUserSettings"


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def ini(up, aa, taau):
    return ("[/Script/FSD.FSDGameUserSettings]\r\nUpscalingType=%s\r\nAntiAliasingType=%s\r\nTemporalAAUpsamplingEnabled=%s\r\nFOV=90\r\n"
            "[ScalabilityGroups]\r\nsg.ResolutionQuality=100\r\n" % (up, aa, taau))


def setup():
    tmp = tempfile.mkdtemp(prefix="follow_")
    inst = os.path.join(tmp, "game")
    p = os.path.join(inst, "FSD", "Saved", "Config", "WindowsNoEditor", "GameUserSettings.ini")
    os.makedirs(os.path.dirname(p))
    open(p, "w", encoding="utf-8", newline="").write(ini(0, 1, "False"))
    return gamecfg.GameCfg(os.path.join(tmp, "settings"), log=lambda *a: None), inst, p


def val(p, k):
    return gamecfg.ini_get(open(p, encoding="utf-8", newline="").read(), SEC, k)


def game_rewrites(p, **kv):
    t = open(p, encoding="utf-8", newline="").read()
    for k, v in kv.items():
        t, _ = gamecfg.ini_set(t, SEC, k, v)
    open(p, "w", encoding="utf-8", newline="").write(t)


prof = profiles.game_cfg("548430")
check("0 the Deep Rock Galactic profile names the two keys the game changes", set((gamecfg.entries(prof)[0].get("follow") or {})) == {"AntiAliasingType", "TemporalAAUpsamplingEnabled"})

# ---- A. the FIN3 case: On, the game runs and rewrites the two keys, Off
cfg, inst, p = setup()
cfg.enable("548430", inst, prof, False)
check("A1 On: Vela's key is set, the other two are untouched", (val(p, "UpscalingType"), val(p, "AntiAliasingType"), val(p, "TemporalAAUpsamplingEnabled")) == ("3", "1", "False"))
game_rewrites(p, AntiAliasingType=2, TemporalAAUpsamplingEnabled="True")
cfg.disable("548430", False)
got = (val(p, "UpscalingType"), val(p, "AntiAliasingType"), val(p, "TemporalAAUpsamplingEnabled"))
check(f"A2 Off: the file is as before Vela, the game's two changes included ({got})", got == ("0", "1", "False"))
check("A3 ... byte for byte", open(p, encoding="utf-8", newline="").read() == ini(0, 1, "False"))
check("A4 the state file is gone after Off", cfg.read("548430") is None)

# ---- B. the player picks another anti-aliasing himself while Vela is on: his value stays
cfg, inst, p = setup()
cfg.enable("548430", inst, prof, False)
game_rewrites(p, AntiAliasingType=0, TemporalAAUpsamplingEnabled="True")       # 0 is not what the game sets for FSR 2: the player's choice
cfg.disable("548430", False)
got = (val(p, "UpscalingType"), val(p, "AntiAliasingType"), val(p, "TemporalAAUpsamplingEnabled"))
check(f"B a value the game does not set is the player's and stays; the other key goes back ({got})", got == ("0", "0", "False"))

# ---- C. the keys already held the game's values before Vela: nothing to put back
cfg, inst, p = setup()
open(p, "w", encoding="utf-8", newline="").write(ini(0, 2, "True"))
cfg.enable("548430", inst, prof, False)
cfg.disable("548430", False)
check("C the player had TAA before Vela: still has it after Off", (val(p, "AntiAliasingType"), val(p, "TemporalAAUpsamplingEnabled")) == ("2", "True"))

# ---- D. the player's own upscaler in the game (the profile's 'when' does not match): Vela changes nothing, follows nothing
cfg, inst, p = setup()
open(p, "w", encoding="utf-8", newline="").write(ini(2, 1, "False"))
cfg.enable("548430", inst, prof, False)
game_rewrites(p, AntiAliasingType=2)
cfg.disable("548430", False)
check("D Vela did not take the key: Off touches nothing", (val(p, "UpscalingType"), val(p, "AntiAliasingType")) == ("2", "2"))

# ---- E. a game set up by an older Vela (state without the note): nothing is guessed
cfg, inst, p = setup()
old_prof = {k: v for k, v in gamecfg.entries(prof)[0].items() if k != "follow"}
cfg.enable("548430", inst, old_prof, False)
game_rewrites(p, AntiAliasingType=2, TemporalAAUpsamplingEnabled="True")
cfg.ensure("548430", inst, prof, False)                                          # the new plugin starts and sees the game is on
cfg.disable("548430", False)
got = (val(p, "UpscalingType"), val(p, "AntiAliasingType"), val(p, "TemporalAAUpsamplingEnabled"))
check(f"E set up before the change: Vela's own key goes back, the two others are left as they are ({got})", got == ("0", "2", "True"))

# ---- F. On, Off, On again, the game rewrites, Off: the note is the value before the FIRST On
cfg, inst, p = setup()
cfg.enable("548430", inst, prof, False)
game_rewrites(p, AntiAliasingType=2, TemporalAAUpsamplingEnabled="True")
cfg.enable("548430", inst, prof, False)                                          # the panel sets the model again
cfg.disable("548430", False)
got = (val(p, "UpscalingType"), val(p, "AntiAliasingType"), val(p, "TemporalAAUpsamplingEnabled"))
check(f"F a second On does not take the game's values as the player's ({got})", got == ("0", "1", "False"))

# ---- G. Ghostrunner's profile (no follow) behaves as before
gr = profiles.game_cfg("1139900")
check("G a profile without follow keys has none", not gamecfg.entries(gr)[0].get("follow"))
print("test_follow_keys " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
