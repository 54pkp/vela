"""NOFG (owner 2026-11-15: «Выпиливай генерацию кадров. Мы позиционируем себя только на замены апскейлеров в играх и что бы они
работали в нпу»): the real backend (main.Plugin on the bench's fake console, bench/fake_console.py) after an update from an older Vela that
left frame generation (the lp0 layer) in games. The older builds' own modules write their states (tests/prev_build.py). One case per point:
  A  a game without an upscaler input with AMD frame generation alone, closed: the plugin start moves the layer manifest aside (not
     deleted) and gives the live file back; the panel's launch_fix gives Steam's options back byte for byte; the game ends fully Off
     (kind "none": Vela offers nothing for it), nothing left to fix
  B  options the player edited since: exactly the layer's tokens out, his DXVK_CONFIG text back, his own edit kept
  C  the game runs at the plugin start: its live file and Steam's options wait for the end of the run, then go back
  D  a kit game (Manor Lords, FSR 4 through Vela's kit) with frame generation alone next to it: the layer out, the kit and its model stay;
     Off afterwards gives the owner's options byte for byte
  E  RIFE alone and FSR 4 for any game (dd8ba301's states): Off byte for byte
  F  a manifest somebody else put there and a live file somebody else wrote: theirs stays
  G  no frame generation anywhere: no anyfsr4 module or state in game_state, no any_fg call, OptiScaler.ini's FrameGen / OptiFG keys
     off whatever is stored, no FG token in any launch options this build writes, no FG text in the panel
Run: python -I tests/test_nofg.py"""
import asyncio
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, HERE)
import fake_console as fc  # noqa: E402

main, profiles, presets = fc.load()
import launchopts  # noqa: E402
import nofg  # noqa: E402
import sgsr3  # noqa: E402
import prev_build  # noqa: E402

ANY, ML = "9000009", "1363080"
OWNER = "DXVK_CONFIG=dxgi.maxFrameRate=60 MANGOHUD=1 %command% -novid"
FG_TOKEN = re.compile(r"^(LP0_|LP_|TUP_LOG|OPTI_SGSRFG|TU_AUTOTUNE)")
fails, checks = [], 0


def check(what, cond):
    global checks
    checks += 1
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def W(opts):
    return launchopts.words(opts or "")


def fg_in(opts):
    return [t for t in W(opts) if FG_TOKEN.match(t)]


tmp = tempfile.mkdtemp(prefix="nofg_")
games = {a: g for a, g in fc.all_games(profiles.PROFILES).items() if a in (ANY, ML)}
template = fc.build_template(os.path.join(tmp, "library"), games)


def live(P, appid):
    try:
        with open(P.nofg.live_path(appid), encoding="utf-8", newline="") as f:
            return f.read()
    except OSError:
        return None


def manifest(P):
    return os.path.join(P.nofg.layer_dir, nofg.MANIFEST)


async def restart(con):
    """An update to this build: Decky starts the plugin again (its _main) on the same console."""
    con.stop_loops()
    await con.start()
    con.stop_loops()
    return con.plugin


async def go():
    con = fc.Console(os.path.join(tmp, "c1"), template, "v73", "pkg16", anypack=False)
    await con.start()
    con.stop_loops()
    P = con.plugin

    # ---- A. AMD frame generation alone, game closed
    old = prev_build.legacy_fg_only(P, ANY, OWNER, "amd")["launch_options"]
    check(f"A0 the older build's options run the layer ({' '.join(fg_in(old))[:80]}...)", "LP_FGONLY=1" in W(old) and "LP0_ENABLE=1" in W(old))
    check("A0 its manifest and live file are there", os.path.isfile(manifest(P)) and "fg=1" in (live(P, ANY) or ""))
    P = await restart(con)
    aside = os.path.join(P.nofg.dir, nofg.ASIDE)
    check("A1 start: the manifest moved aside, not deleted", not os.path.exists(manifest(P)) and os.path.isdir(aside)
          and any(n.startswith(nofg.MANIFEST) for n in os.listdir(aside)))
    check("A2 start: the live file back as before (there was none)", live(P, ANY) is None)
    gs = P._game_state(ANY, "Default")
    check("A3 the panel asks for launch_fix; no anyfsr4 in the state", gs["launch_fix"] is True and "anyfsr4" not in gs)
    fixed = P._launch_fix(ANY, old)["launch_options"]
    check(f"A4 launch_fix: the owner's options byte for byte ({fixed!r})", fixed == OWNER)
    gs = P._game_state(ANY, "Default")
    st = P.nofg.read(ANY)
    check(f"A5 fully Off: kind {gs['check']['kind']}, model {gs['model']}, nothing left to fix", gs["check"]["kind"] == "none"
          and gs["model"] == "off" and gs["launch_fix"] is False and not st["fgo"] and not st["on"] and st.get("nofg_at"))
    check("A6 launch_fix again: the options as they are", P._launch_fix(ANY, OWNER)["launch_options"] == OWNER)

    # ---- B. options the player edited since
    old = prev_build.legacy_fg_only(P, ANY, OWNER, "amd")["launch_options"]
    edited = old + " -windowed"
    P = await restart(con)
    fixed = P._launch_fix(ANY, edited)["launch_options"]
    check(f"B1 edited: the layer's tokens out, DXVK_CONFIG back, his edit kept ({fixed!r})",
          fixed == OWNER + " -windowed" and not fg_in(fixed))

    # ---- C. the game runs at the plugin start
    old = prev_build.legacy_fg_only(P, ANY, OWNER, "amd")["launch_options"]
    con.set_running(ANY, True)
    P = await restart(con)
    check("C1 running: its live file stays for the run", "fg=1" in (live(P, ANY) or ""))
    gs = P._game_state(ANY, "Default")
    check("C2 running: no launch_fix yet, launch_fix leaves the options", gs["launch_fix"] is False
          and P._launch_fix(ANY, old)["launch_options"] == old)
    con.set_running(ANY, False)
    P.nofg.reconcile(set())
    check("C3 the run ended: the live file back (reconcile)", live(P, ANY) is None)
    gs = P._game_state(ANY, "Default")
    check("C4 then launch_fix: byte for byte", gs["launch_fix"] is True and P._launch_fix(ANY, old)["launch_options"] == OWNER)

    # ---- D. a kit game with frame generation alone next to its kit
    r = P._apply_model(ML, "fsr4", OWNER, "Default")
    kit = r["launch_options"]
    old = prev_build.legacy_fg_only(P, ML, kit, "amd", kit_on=True)["launch_options"]
    P = await restart(con)
    gs = P._game_state(ML, "Default")
    check("D1 kit + FG: launch_fix asked, the kit is on with FSR 4", gs["launch_fix"] is True and gs["sgsr3"]["installed"] and gs["model"] == "fsr4")
    fixed = P._launch_fix(ML, old)["launch_options"]
    gs = P._game_state(ML, "Default")
    check(f"D2 launch_fix: the layer out, the kit's options as before ({fixed!r})", fixed == kit and not fg_in(fixed)
          and gs["sgsr3"]["installed"] and gs["model"] == "fsr4" and gs["launch_fix"] is False)
    kit_opts = P.s3.kit_options(ML) or ""
    check(f"D3 no FG token in the kit's own options ({kit_opts[:80]})", not [t for t in W(kit_opts) if t.startswith(("LP_FG", "LP0_", "OPTI_SGSRFG"))])
    check("D4 Model Off: the owner's options byte for byte", P._apply_model(ML, "off", fixed, "Default")["launch_options"] == OWNER)

    # ---- E. RIFE alone and FSR 4 for any game (dd8ba301)
    old = prev_build.legacy_fg_only(P, ANY, OWNER, "rife", name="anyfsr4_prev")["launch_options"]
    P = await restart(con)
    check(f"E1 RIFE alone ({'LP_FGGEN=rife' in W(old)}): Off byte for byte",
          "LP_FGGEN=rife" in W(old) and P._launch_fix(ANY, old)["launch_options"] == OWNER)
    on = prev_build.legacy_on(P, ANY, OWNER)["launch_options"]
    P = await restart(con)
    check(f"E2 FSR 4 for any game ({'LP_FSR=1' in W(on) or 'LP0_ENABLE=1' in W(on)}): Off byte for byte",
          "LP0_ENABLE=1" in W(on) and P._launch_fix(ANY, on)["launch_options"] == OWNER and not P.nofg.read(ANY)["on"])
    check("E3 no exception logged", not con.exceptions)

    # ---- F. somebody else's manifest and live lines
    other = {"layer": {"name": "VK_LAYER_VELA_lp0", "library_path": "/opt/bench/libVkLayer_VELA_lp0.so"}}
    os.makedirs(P.nofg.layer_dir, exist_ok=True)
    with open(manifest(P), "w", encoding="utf-8") as f:
        json.dump(other, f)
    old = prev_build.of_plugin(P).fg_only(ANY, OWNER, "amd")["launch_options"]  # writes ours over it (an older build did that)
    with open(manifest(P), "w", encoding="utf-8") as f:
        json.dump(other, f)  # and the bench put its own back
    with open(P.nofg.live_path(ANY), "a", encoding="utf-8", newline="") as f:
        f.write("bench=1\n")
    P = await restart(con)
    check("F1 a manifest that names another library stays", os.path.isfile(manifest(P)) and json.load(open(manifest(P))) == other)
    check(f"F2 a live file somebody else wrote: only the layer's lines out ({live(P, ANY)!r})", live(P, ANY) == "bench=1\n")
    check("F3 then Off byte for byte", P._launch_fix(ANY, old)["launch_options"] == OWNER)

    # ---- G. no frame generation anywhere
    check("G1 no any_fg / _af_apply in the backend, no anyfsr4 module", not hasattr(P, "any_fg") and not hasattr(P, "_af_apply")
          and not os.path.exists(os.path.join(ROOT, "py_modules", "anyfsr4.py")))
    ini = sgsr3.make_ini(open(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini"), encoding="utf-8").read()
                         if os.path.isfile(os.path.join(ROOT, "assets", "sgsr3", "OptiScaler.ini")) else "[FrameGen]\n[OptiFG]\n",
                         {"fg": True, "latency": False, "fps": "off"})
    check("G2 OptiScaler.ini: FrameGen / OptiFG off even with an older Vela's fg=True",
          sgsr3.ini_get(ini, "FrameGen", "Enabled") == "false" and sgsr3.ini_get(ini, "FrameGen", "FGOutput") == "auto"
          and sgsr3.ini_get(ini, "FrameGen", "FGInput") == "auto" and sgsr3.ini_get(ini, "OptiFG", "HUDFix") == "auto")
    check("G3 sgsr3: no fg option, launch_build takes none", "fg" not in sgsr3.DEFAULT_OPTS
          and "fg" not in sgsr3.launch_build.__code__.co_varnames and "fg" not in sgsr3.Sgsr3.clean_opts({"fg": True}))
    r = P._apply_model(ML, "fsr3", OWNER, "Default")
    check(f"G4 a new setup writes no FG token ({r['launch_options']!r})", not fg_in(r["launch_options"])
          and not [t for t in W(P.s3.kit_options(ML) or "") if FG_TOKEN.match(t)])
    en = json.load(open(os.path.join(ROOT, "src", "i18n", "en.json"), encoding="utf-8"))
    tsx = open(os.path.join(ROOT, "src", "index.tsx"), encoding="utf-8").read()
    fgkeys = [k for k in en if k.startswith(("fg.", "fgo.", "any.")) or k == "model.note.offFg"]
    fgtext = [k for k, v in en.items() if re.search(r"frame gen|generat", v, re.I)]
    check(f"G5 no FG text in the panel (keys {fgkeys}, texts {fgtext})", not fgkeys and not fgtext)
    check("G6 index.tsx: no frame-generation block, call or status", not re.search(r"anyFg|any_fg|fgBlock|fgOnly|anyfsr4|Frame generation", tsx))
    check("G7 no exception logged", not con.exceptions)


asyncio.run(go())
print(f"test_nofg: {checks} checks, {len(fails)} failed" + (f": {fails}" if fails else ""))
sys.exit(1 if fails else 0)
