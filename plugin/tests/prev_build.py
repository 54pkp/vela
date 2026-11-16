"""NOFG (2026-11-15): frame generation (the lp0 layer, py_modules/anyfsr4.py) is out of the plugin, but a player's settings may still hold
a game an older Vela set to it. The older builds' own modules write exactly that state on the folders the plugin under test uses:
- tests/fixtures/anyfsr4_fg.py = py_modules/anyfsr4.py of 6d75f725, the last build with frame generation (AMD alone, LP_FGONLY=1, for
  a game without an upscaler input and next to Vela's kit);
- tests/fixtures/anyfsr4_prev.py = the same module of dd8ba301 (FSR 4 for any game, RIFE).
The files those builds shipped in assets/anyfsr4 (the layer, its manifest, the provider, the fg10 set) are made as stand-ins: the new
plugin zip has none of them. Tests only."""
import importlib.util
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_mods = {}


def module(name="anyfsr4_fg"):
    if name not in _mods:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "fixtures", name + ".py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _mods[name] = m
    return _mods[name]


def old_af(assets, home, settings, live_dir, name="anyfsr4_fg", log=print, chip=None):
    """An older build's AnyFsr4 on these folders (assets = <plugin>/assets/anyfsr4) with what it needed. chip None = the PC (AMD
    fg10-gpu needs no NPU package), as the bench runs it."""
    old = module(name)
    old.LIVE_DIR = live_dir
    os.makedirs(assets, exist_ok=True)
    man = os.path.join(assets, old.MANIFEST)
    if not os.path.isfile(man):
        shutil.copyfile(os.path.join(ROOT, "_removed", "assets", "anyfsr4", old.MANIFEST), man)
    for f in (old.LIB, old.PROVIDER):
        if not os.path.isfile(os.path.join(assets, f)):
            open(os.path.join(assets, f), "wb").write(b"so")
    if name == "anyfsr4_prev":  # its FSR 4 On needed the pack
        pack = os.path.join(settings, "anyfsr4", "pack")
        os.makedirs(os.path.join(pack, "fsr411"), exist_ok=True)
        if not os.path.isfile(os.path.join(pack, old.MARKER)):
            open(os.path.join(pack, old.MARKER), "w").write("{}")
    return old.AnyFsr4(assets, home, settings, log=log, chip=chip)


def of_plugin(P, name="anyfsr4_fg"):
    """old_af on the folders of a running main.Plugin P (its NoFg)."""
    home = P.nofg.layer_dir
    for _ in range(4):  # <home>/.local/share/vulkan/implicit_layer.d
        home = os.path.dirname(home)
    return old_af(P.nofg.assets, home, os.path.dirname(P.nofg.dir), P.nofg.live_dir, name, log=P.nofg.log)


def legacy_fg_only(P, appid, launch_options, fg="amd", name="anyfsr4_fg", **kw):
    """An older Vela's frame generation alone (its fg_only): {"launch_options"} as it returned them."""
    return of_plugin(P, name).fg_only(appid, launch_options, fg, **kw)


def legacy_on(P, appid, launch_options, npu=False, **kw):
    """An older Vela's On of FSR 4 for any game (dd8ba301's enable): {"launch_options", "resolution"} as it returned them."""
    return of_plugin(P, "anyfsr4_prev").enable(appid, launch_options, npu, **kw)
