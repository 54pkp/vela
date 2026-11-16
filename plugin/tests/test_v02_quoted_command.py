"""V02 (audit 2026-11-09): a quoted "%command%" (or one inside $( ... )) is there: Vela must not put a second %command% in front.
Before: launchopts.add looked for a token that is exactly %command%; for `eval $( echo "%command%" | sed "s/Launcher.exe/Game.exe/" )` (a common
recipe to skip a launcher) it gave `<Vela tokens> %command% eval $( echo "%command%" ... )`: the game started by the first %command% with "eval"
and its own command line as arguments, or not at all. In launcher mode the launcher token went in front of "eval".
Run: python -I tests/test_v02_quoted_command.py     (VELA_PYMOD=<another py_modules>: the old code fails)"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.environ.get("VELA_PYMOD") or os.path.join(ROOT, "py_modules"))
import launchopts  # noqa: E402
import sgsr3  # noqa: E402
import velakit  # noqa: E402

fails = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


RECIPE = 'eval $( echo "%command%" | sed "s/Launcher.exe/Game.exe/" )'
new, rec = launchopts.add(RECIPE, ["LP0_ENABLE=1", "LP_FSR=1"], ["-dx12"])
check(f"1a the launcher-skip recipe keeps ONE %command% ({new.count('%command%')})", new.count("%command%") == 1 and rec["cmd"] is False)
check("1b Vela's variables in front, its argument at the end, the recipe untouched between them", new == "LP0_ENABLE=1 LP_FSR=1 " + RECIPE + " -dx12")
check("1c Off gives back the recipe byte for byte", launchopts.remove(new, rec) == RECIPE)
new, rec = launchopts.add('"%command%"', ["A=1"])
check(f"2 a quoted %command% alone: {new!r}", new == 'A=1 "%command%"' and launchopts.remove(new, rec) == '"%command%"')
new, rec = launchopts.add('MANGOHUD=1 gamemoderun "%command%" -novid', ["A=1"], ["-dx12"])
check(f"3 quoted between the player's tokens: {new!r}", new == 'A=1 MANGOHUD=1 gamemoderun "%command%" -novid -dx12')
new, rec = launchopts.add('FOO=2 eval "%command%"', ["FOO=1", "BAR=1"])
check("4 a variable the player sets before the wrapped command is not added again", new == 'BAR=1 FOO=2 eval "%command%"')
new, rec = launchopts.add('eval "%command%" -dx12', [], ["-dx12"])
check("5 an argument already passed after the wrapped command is not added again", new == 'eval "%command%" -dx12' and rec["args"] == [])
# unchanged behaviour for plain options
check("6a no options: %command% is put in", launchopts.add("", ["A=1"]) == ("A=1 %command%", {"env": ["A=1"], "args": [], "cmd": True}))
check("6b options without %command%: put in front of them", launchopts.add("-windowed", ["A=1"])[0] == "A=1 %command% -windowed")
check("6c a plain %command% as before", launchopts.add("X=1 %command% -w", ["A=1"], ["-dx12"])[0] == "A=1 X=1 %command% -w -dx12")
if hasattr(launchopts, "wrapped_cmd"):
    check("7 wrapped_cmd: the recipe and \"%command%\" yes; plain, empty and no %command% no",
          launchopts.wrapped_cmd(RECIPE) and launchopts.wrapped_cmd('"%command%"') and not launchopts.wrapped_cmd("A=1 %command%")
          and not launchopts.wrapped_cmd("") and not launchopts.wrapped_cmd("-windowed") and not launchopts.wrapped_cmd(None))
# launcher mode: the launcher token never goes in front of a wrapped command; a new setup of such a game is a copy setup
tmp = tempfile.mkdtemp(prefix="v02_")
logs = []
s3 = sgsr3.Sgsr3(os.path.join(tmp, "assets"), os.path.join(tmp, "home"), os.path.join(tmp, "settings"), log=logs.append)
os.makedirs(s3.kit_root("30"), exist_ok=True)
out = s3.steam_options("30", RECIPE, True)
check(f"8 launcher mode + the recipe: options left as the player wrote them ({out!r})", out == RECIPE and velakit.LAUNCHER_TOKEN not in out)
out = s3.steam_options("30", "MANGOHUD=1 %command%", True)
check("9 launcher mode + plain options: the launcher token in front, as before", out == velakit.LAUNCHER_TOKEN + " MANGOHUD=1 %command%")
s3.new_mode = "launcher"
s3.scan = lambda appid, *a, **k: {"exe_dir": os.path.join(tmp, "game"), "install_dir": os.path.join(tmp, "game"), "appid": appid}
s3.overlay_ok = lambda appid, sc=None: True
check("10 a new setup with the recipe is a copy setup; with plain options the overlay (launcher)",
      s3._new_mode("31", RECIPE) == "copy" and s3._new_mode("31", "%command%") == "launcher")
print("test_v02_quoted_command " + ("OK" if not fails else f"FAIL {len(fails)}: {fails}"))
raise SystemExit(1 if fails else 0)
