# NOFSR (2026-11-11): py_modules/anyfsr4.py as of dd8ba301, the last build with "FSR 4 for any game". Tests only: it writes the
# states an older Vela left in a player's settings (a game on FSR 4 for any game), which this build moves to Off.
"""0.8.22: FSR 4 for any game -- the Vulkan layer VK_LAYER_VELA_lp0 (handoff 1106 step 5, PTC2 PLUGIN_SPEC.md).

For a Windows game without DLSS / FSR / XeSS (gamecheck kind "any"). When the game draws in a window smaller than the screen,
our layer under DXVK / vkd3d makes the real 1920x1080 swapchain and runs FSR 4 Fast from the game's frames (on the NPU through
VK_LAYER_VELA_npu when the NPU part is installed, else on the GPU). Nothing goes into the game folder.
PL3 (owner 2026-11-06: «Vela сама не должна ничего сделать, просто говорить может что поставьте разрешение в 360 или выше и
выберите режим в окне»): Vela never sets the game's window. The player picks windowed mode, MIN_WINDOW or more and below the
screen, in the game's own settings; the panel says so before the first run and when the layer log says the game's picture is
not smaller than the screen (fact "full"). The one exception is a one-time cleanup: a game switched on by a PL1 / PL2 test build
has Steam's resolution override at LEGACY_WINDOW and its old value in "resolution_prev"; Off gives that old value back once.

Files:
- assets/anyfsr4/libVkLayer_VELA_lp0.so + VkLayer_VELA_lp0.json (the layer) and libamd_fidelityfx_upscaler_vk.so (the Vela
  provider) are in the plugin zip;
- the provider's network files fsr411/ (173 MB) are the "any-game pack", a separate download the plugin fetches once
  (fetch_pack: sha256 of the zip pinned, every file and the whole set's md5 checked) into <settings>/anyfsr4/pack; a plugin
  build that carries assets/anyfsr4/pack/fsr411 uses that one.
The layer manifest is in ~/.local/share/vulkan/implicit_layer.d (library_path = the plugin's .so) while a game has the mode
on, and only then; it loads only with LP0_ENABLE=1 in a game's launch options.

Launch options: our tokens in front of the player's (launchopts.add); the player's DXVK_CONFIG=<x> becomes
DXVK_CONFIG="<x>;dxvk.tilerMode=False" (one token swapped, the record keeps both texts). Off: the exact previous options when
nobody touched them since, else exactly our tokens out and the player's DXVK_CONFIG text back. The picture mode (PICTURES) is
one more of our tokens: PL3 LP_LATE=<v>, PL5 the layer's player variant LP_LMODE=<1..3> (none for Auto).
PL5 (owner 2026-11-06 «Да, подходит»): four picture modes (PICTURES) and a sharpness (LP_SHARP, only when not the default 0.5).
Both also switch LIVE in a running game: the layer reads /tmp/vela-live/lp_<SteamAppId>.ini every 30 frames (lp0_hooks.inc
lp0_bench_poll) and takes late=<0..3> (LUI3, applied between two frames, one history reset) and sharp=<0..1> (RCAS after FSR,
0 = no pass). While a game is on, that file carries our two lines (a key the layer has read stays in force until the file says
otherwise); Off gives back the file as it was before On (or none), or, when someone else wrote it since, takes only our lines out.
No per-game logic: no game names, no per-game keys.
"""
import hashlib
import json
import os
import re
import shutil
import time
import zipfile

import launchopts

MODEL = "fsr4any"
KIND = "any"
LAYER_NAME = "VK_LAYER_VELA_lp0"
LIB = "libVkLayer_VELA_lp0.so"
MANIFEST = "VkLayer_VELA_lp0.json"
PROVIDER = "libamd_fidelityfx_upscaler_vk.so"
ENABLE_ENV = ("LP0_ENABLE", "1")
DISABLE_ENV = ("LP0_DISABLE", "1")
OUTPUT = "1920x1080"      # LP_OUT = TUP_OUTPUT = the screen
MIN_WINDOW = "640x360"    # the smallest window the hint names (owner 2026-11-06: «разрешение в 360 или выше»; x3 = nf4_k1h_360)
LEGACY_WINDOW = "640x360" # the Steam override PL1 / PL2 test builds wrote (enable returned it); PL3 only takes it back on Off
# PL3: the picture mode -> the layer's LP_LATE (PTC2 R13, cf2df2c, lead 2026-11-06): Auto = unset (the layer's default: start with
# FSR after the scene, move it behind the game's post when the post costs much at the output size); Sharp UI = 1 (FSR after the
# scene the whole session, the layer's own guards stay on); More FPS = 2 (FSR at the end of the frame). Never 0: a debug value that
# also turns the layer's guards off.
LATE_KEY = "LP_LATE"  # PL3, no longer written since PL5
# PL5 (owner 2026-11-06): Auto / Sharp UI / Balanced / More FPS. The layer's player variant (LUI3 82b9d40 / a18872f, lead
# 2026-11-06): env LP_LMODE for the start, the same number as the live key late= of the running game: 1 current (FSR after the
# scene, effects + UI at the output size), 2 late with the UI split (effects at the window size, UI at the output size), 3 late,
# the UI through FSR. Auto = no variant (unset / late=0): the layer's own choice. LP_LATE is no longer written (never 0).
LMODE_KEY = "LP_LMODE"
PICTURES = {"auto": (), "sharp": ("LP_LMODE=1",), "balanced": ("LP_LMODE=2",), "fps": ("LP_LMODE=3",)}
LIVE_LATE = {"auto": 0, "sharp": 1, "balanced": 2, "fps": 3}
# late=0 in a running game is "no player variant, FSR stays where it is" (lp_fsr.inc LUI3): the layer does not start its auto
# measurement again in the same run, so Auto chosen during a run takes effect when the game starts (the panel says so)
PICTURE_LIVE = ("sharp", "balanced", "fps")
PICTURE_DEFAULT = "auto"
# PL5: sharpness = the layer's RCAS after FSR (lp_fsr.inc: live sharp=, else env LP_SHARP, else 0.5; 0 = no pass), the same
# 0..1 / 0.05 slider as Vela's kit sharpness (vela-0.8.16-sharp presets.SHARP_STEP)
SHARP_KEY = "LP_SHARP"
SHARP_DEFAULT = 0.5
SHARP_STEP = 0.05
LIVE_DIR = "/tmp/vela-live"  # the layer's live file lp_<SteamAppId>.ini (Linux); Vela's kit file <appid>.ini is live.py's
# PL6 (owner 2026-11-06, variant A): frame generation Off / 2x of the layer (FGI1, branch vela-fg1): env LP_FG=1 for the start
# (none for Off, the layer's default 0), live key fg=0/1 in the running game. fg= is always written while the mode is on, so a
# running game that had 2x goes back (the layer keeps a live value until the next one) and the file after 2x -> Off is byte for
# byte the file before 2x. Rendered -> shown FPS for the status: the layer's LPT lines (BFG1 LAYER_TIMESTAMPS.md section 1), or
# an "LP FG rendered=<fps> shown=<fps>" summary line (PL6 proposal to FGI1); both TO BE CONFIRMED against the FGI1 build.
# PL7 (owner 2026-11-06 «Вариант А. Выбор офф амд райф»): the generator is the button, Off / AMD / RIFE in his order. A generator
# = LP_FG=1 + LP_FGGEN=<name> for the start and live fg=1 + fgg=<name>; Off = neither token and live fg=0 (fgg= is not written,
# so the file after Off is byte for byte the file before). Names (the layer's LP_FGGEN / fgg=): RIFE "rife" everywhere; AMD
# "fg10-gpu" on the PC (no Snapdragon chip: self.chip is None) and "fg10-npu" on the console, where it is NOT ready yet: offered
# dimmed with its reason (status fg_na), refused by enable / set_fg, a stored AMD gives Off. PL6's "x2" (no generator) reads as RIFE.
FG_KEY = "LP_FG"
FG_GEN_KEY = "LP_FGGEN"
FGS = ("off", "amd", "rife")
FG_GEN = {"amd": {"gpu": "fg10-gpu", "npu": "fg10-npu"}, "rife": {"gpu": "rife", "npu": "rife"}}
FG_READY = {"amd": {"gpu": True, "npu": True}, "rife": {"gpu": True, "npu": True}}  # PL13 (FG9 AMD_FSR_GO): AMD with FSR 4 on the NPU too
FG_LEGACY = {"x2": "rife"}
# PLB5 (fgtest2): RIFE on the console runs on the NPU daemon of Vela NPU package 15 (NPK1: --fg-dir /usr/lib64/vela-npu/fg, socket
# @fsr4npud_fg, extension-release X_VELA_NPU_PACKAGE=15). The layer (vela-fg1 lp_fg_mb.inc rife_connect) connects to @fsr4npud_fg
# when LP_FGNPU_SOCK is unset and asks for these five contexts by name, so the launch gets no socket token. Without the package
# (no fg/ contexts, no FG socket, or a package number below 15) RIFE is dimmed with the reason "npu_pkg" and refused like AMD.
FG_NPU = {"rife"}  # the generators that need the NPU package's FG part on the console
NPU_FG_PACKAGE = 15
NPU_FG_DIR = "/usr/lib64/vela-npu/fg"
NPU_FG_CTX = ("RF3_720_headr4_a8w8", "RF5_720_b0_c_a8w8", "RF5_720_b1_c_a8w8", "RF5_720_b2_c_a8w8", "RF5_720_b3r4ph_g216_a8w8")
NPU_FG_SOCKET = "fsr4npud_fg"
NPU_RELEASE = "/usr/lib/extension-release.d/extension-release.armada-vela-npu"
PROC_NET_UNIX = "/proc/net/unix"


def npu_package(path=NPU_RELEASE):
    """The installed Vela NPU package number (X_VELA_NPU_PACKAGE of its extension-release), None when unknown."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            m = re.search(r'^X_VELA_NPU_PACKAGE="?(\d+)', f.read(), re.M)
    except OSError:
        return None
    return int(m.group(1)) if m else None


def fg_socket(proc_net_unix=PROC_NET_UNIX, name=NPU_FG_SOCKET):
    """The NPU daemon's FG socket is bound (abstract @fsr4npud_fg in /proc/net/unix)."""
    try:
        with open(proc_net_unix, encoding="utf-8", errors="replace") as f:
            return any(len(ln.split()) >= 8 and ln.split()[-1] == "@" + name for ln in f)
    except OSError:
        return False
FG_DEFAULT = "off"
# PL9 (owner 2026-11-07, PL8 «Вариант А»): frame generation without the upscaler = the layer's LP_FGONLY=1 (FGI1 R30, vela-fgonly
# c66eea4): the game renders at its own size, no FSR (no pack, no provider, no NPU layer, no TUP_OUTPUT / LP_OUT / LP_FSR / LP_FAST /
# LP_NPU / LP_PROVIDER / FSR4_VK_ASSET_ROOT / LP_LMODE / LP_SHARP), the generator at the chain size. It is on while the model is Off
# and a generator is picked (state "fgo"); Off / Off gives the launch options and the live file back byte for byte.
FGONLY_KEY = "LP_FGONLY"
# readiness without FSR: R30 ran both generators on the console without FSR (AMD fg10-npu 98.5-99.9 %, RIFE 95.4-99.1 % G)
FG_READY_ONLY = {"amd": {"gpu": True, "npu": True}, "rife": {"gpu": True, "npu": True}}
# AMD fg10-npu on the console needs what R30's runs had (plans fgi28/stage/ptc2_fg28tb / ub, OWNDEV = the best variant): the
# generator library and its data (LP_FGGEN_LIB / LP_FG10_DIR / LP_FG10_BLOB) and the six 720p AMD contexts in the NPU daemon's fg
# dir. NPU package 15 carries only RIFE's five (NPK1: "AMD FG11 set: left out") and the plugin zip no fg10 library: without them
# AMD stays dimmed (reason "amd_set"), else the layer would run its built-in stub under the name AMD.
FG10_DIR = "fg10"            # <plugin>/assets/anyfsr4/fg10
FG10_LIB = "libfg10_gen.so"
FG10_BLOB = "fg_blob.bin"
NPU_FG10_CTX = ("FG11_fg10_s0_18_720p", "FG11_fg10_s18_54_720p", "FG11_fg10_s54_83_720p", "FG11_fg10_s83_112_720p",
                "FG11_fg10_s112_149_720p", "FG11_fg10_s152_190_720p")
# PL10: Vela NPU package 16 (NPK2) = 15 + these six 720p contexts; the zip ships the library + data (assets/anyfsr4/fg10, NPK2
# plugin_fg10_md5.txt, 1920x1080/ left out). Package 16 has 720p contexts only, so the network is pinned to 720p (LP_FG10_NETRES).
NPU_FG10_PACKAGE = 16
# PL10 (lead 2026-11-07, R31): RIFE on the NPU records its passes ahead (LP_RIFE_PREREC=1): call -> G -0.04...-0.32 ms in all 4 runs,
# nothing worse. RIFE OWNDEV stays off (works, no gain); PASS_TIMING stays off (diagnosis only).
# PL15 (fgtest6, FGI1 R40 5 + d): RIFE FAST=31 (call -> G 8.79 / 9.46 ms in game, below RF6 and R31) and the hys mode-B rule
# written out (the layer's default with the gate on since RF7b 2cc5167; written so a layer without RF7b rides out bursts the same way).
RIFE_NPU_ENV = ("LP_RIFE_PREREC=1", "LP_RIFE_FAST=31", "LP_FGMB_RULE=hys")
# PL15 (FGI1 R40 5, lead): the letterbox / pillarbox scene depth of UPX2 D2 (2a29f58) stays off until its 4:3 A/B proves it
LBOX_ENV = ("LP_LBOX=0",)
FG10_NETRES = "1280x720"
# PL13 (PL12: RIFE on the PC "create failed (VkResult -8)": the panel said «can't keep up — 0 %»): the generator's create result, the
# later word wins ("on at f=" after a failed create of an earlier chain)
_RX_GENX = re.compile(r"LP FGGEN: generator (\S+) (on at f=|create failed \(VkResult (-?\d+)\))")
# PL15: the layer could not set FG up on a chain (a format / colour space it cannot take); a later "on chain" (a chain set up) clears it
_RX_FGINIT = re.compile(r"LP FG: (?:init failed, FG off on chain \S+(?: \(format (-?\d+) colour space (-?\d+)\))?|(on chain ))")
# PL15 (fgtest6 safety net, lp_fg_loop.h): the chain was remade in a loop while FG was on; FG is off until the game exits
FG_LOOP_LINE = "LP FG OFF: chain loop"
_RX_FGO_SIZE = re.compile(r"LP FGONLY: \S+ at the chain size (\d+x\d+)")  # lp_fg.inc: the generator's size = the game's chain
LIVE_KEYS = ("late", "sharp", "fg", "fgg", "fsr")  # UPX1: fsr= = Off / On inside a running game (lp0_hooks.inc: live fsr=0|1)


# R6C (RIFE 2026-11-11, lead: into the build after 10c): the generator skips its MV fill pass and fuses the network input
# (LP_FG10_MV_FILL=0 LP_FG10_FUSE_IN=1; the installed generator lib and override_0_netin.spv already support both): -0.9 ms GPU per
# generated frame (-16 % of fg10's GPU time); DREDGE FG on +3.8 %, Ghostrunner ABBA +1.7 %, p99 not worse, picture 35.0 vs 35.6 dB
# inside the run-to-run spread (AUD1/RIFE_RESULTS.md R6C / R6XG, AUD1/runs/r6x/)
FG10_R6C_ENV = ("LP_FG10_MV_FILL=0", "LP_FG10_FUSE_IN=1")


def fg_env(fg, where):
    """The launch tokens of a frame generation choice on a device ("gpu": the PC, "npu": the console)."""
    return () if fg == "off" else (f"{FG_KEY}=1", f"{FG_GEN_KEY}={FG_GEN[fg][where]}")


def fg_mode_env(fg):
    """PL11: the FG mode token (x2 by default, no panel control yet), after all other FG tokens; none for Off."""
    return [] if fg == "off" else [f"{FG_MODE_KEY}={FG_MODE}"]


def fg_live(fg, where):
    """Its lines in the layer's live file."""
    return "fg=0\n" if fg == "off" else f"fg=1\nfgg={FG_GEN[fg][where]}\n"
DXVK_KEY = "DXVK_CONFIG"
TILER = "dxvk.tilerMode=False"  # Turnip / Adreno: DXVK 2.7.1 must not record passes into secondary buffers (PTC2 R6/R7)
# the any-game pack: fsr411/ of the provider (PTC2 R3 set, 1446 files); md5 of `find . -type f -exec md5sum {} + | sort -k2`
PACK_FILES = 1446
PACK_SET_MD5 = "b0ef746935cd6b1a5504a5593ab6f573"
PACK_NAME = "vela-anygame-pack-r3.zip"
PACK_URL = "https://github.com/zrprod9-cmyk/vela/releases/download/anygame-pack-r3/" + PACK_NAME
PACK_SHA256 = None  # set by the release that publishes the pack (PL1: built, not published); None: any zip whose set md5 matches
PACK_MB = 53
MARKER = "VELA_PACK.json"
LOG_CHUNK = 1 << 20  # the layer log is read in pieces of this, from where the last read stopped (PL2: no tail-only read)
HEAD_SIG = 256       # the first bytes of a log tell one run's file from the next one's
LOG_CAP = 8 * 1024 * 1024  # PLT1 bug 2: a running game's layer log past this is cut back to nothing (its facts are kept)
LOG_IDLE_S = 60      # a log of a game that is not running and was not written for this long holds a finished run
QUIET = "LP0_LOG_EVERY=0"  # the layer's per-frame CAM line off (lp0_hooks.inc: LP0_LOG_EVERY=N, CAM line every N frames)


_RX_CTX = re.compile(r"LP: ffxCreateContext \d+, (\d+x\d+) -> (\d+x\d+)")
_RX_SWAP = re.compile(r"game swapchain (\d+x\d+) -> real (\d+x\d+)")
_RX_HTP = re.compile(r"Vela NPU: \d+ frames, HTP ([\d.]+) ms, fallbacks (\d+)")
_RX_SAFE = re.compile(r"LP SAFE off reason=(\S+)")
# PL3: the game's picture is not below the screen (lp_fsr.inc: "LP: scene WxH is not below the output WxH: no upscale, FSR waits"),
# or the layer made a bigger swapchain for a smaller game window (swap_upscale.h "game swapchain WxH -> real WxH"): the later wins
_RX_SIZE = re.compile(r"LP: scene (\d+x\d+) is not below the output \d+x\d+|game swapchain (\d+x\d+) -> real \d+x\d+")
_RX_LPT = re.compile(r"LPT q=\d+ kind=(real|gen) f=\d+ t_call=\d+ t_out=(\d+)")  # BFG1 LAYER_TIMESTAMPS.md 1, per present
_RX_FGSTAT = re.compile(r"LP FG rendered=([\d.]+) shown=([\d.]+)")  # PL6 proposal: the layer's own summary (every 300 presents)
# PL11 (PLT4: the panel said 60 -> 119 while RIFE made 1 frame of 1120): the layer's line also says what the generator itself made
_RX_FGX = re.compile(r"LP FG rendered=([\d.]+) shown=([\d.]+) generated=([\d.]+) slots=([\d.]+) skip_screen=([\d.]+) skip_time=([\d.]+) "
                     r"refresh=([\d.]+)")
FGX_LINES = 5       # PL11: the last lines (about a second each) that give the generated share for the status
# PL11 (lead 2026-11-07): FG modes like Lossless Scaling: x2 (default), x3 (only with a generator that takes any t), adaptive (target
# = the display refresh). No mode control in the panel yet: the default goes into the launch options with FG.
FG_MODE_KEY = "LP_FG_MODE"
FG_MODE = "x2"
LPT_WINDOW = 600     # the last presents of a log piece that give the rendered / shown FPS
LPT_MIN_S = 0.5      # a shorter stretch of presents gives no number
_RX_FRAMES = re.compile(r"(?:LP STAT f=|2D: )(\d+)")  # frames so far: the layer's summary every 300, its stretch count every 3000
# PL2 (PLT1 bug 3): the layer's FSR 1 stretch on screen for this many frames (1 min at 60 fps) and no FSR 4 frame yet: the panel
# says so plainly. The first FSR frame of the working test game came at frame 1664 (its menus).
STRETCH_FRAMES = 3600


def set_md5(root):
    """md5 of the lines `<md5>  ./<path>` of every file under root, sorted by path (as md5sum | sort -k2 | md5sum on the console)."""
    rows = []
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                rows.append(("./" + os.path.relpath(p, root).replace(os.sep, "/"), hashlib.md5(fh.read()).hexdigest()))
    rows.sort(key=lambda r: r[0].encode())
    return hashlib.md5("".join(f"{m}  {n}\n" for n, m in rows).encode()).hexdigest(), len(rows)


def new_facts():
    return {"lp": False, "ctx": None, "swap": None, "npu": None, "htp": None, "fsr": False, "safe": None, "fsr1": False, "frames": 0,
            "full": None, "fg": None, "fgonly": False, "chain": None, "genfail": None, "fgloop": False, "fginit": None}


# UPX1 (owner 2026-11-07): the layer writes this when the game makes its Vulkan device. A game started again within LOG_IDLE_S
# appends its new run to the same log: the facts start over there, so the last run's «FSR 4 turned itself off» (a per-device
# state in the layer) is not shown for the new run. The owner's test on the console: two runs, one log, a device each.
_RX_DEVICE = re.compile(r"^tup: device created: ", re.M)


def scan_text(text, f):
    """f (what one run's log said so far) updated with the lines of text. The one-time start lines (Vela NPU: on, LP: first
    FSR frame, ffxCreateContext, game swapchain) stay once seen, however many lines come after them (PLT1 bug 1). UPX1: a new
    Vulkan device (a new run in the same log) starts the facts over."""
    devs = list(_RX_DEVICE.finditer(text))
    # only a device made after a swap chain is a new run (a game makes its devices before its first swap chain: DXVK two)
    if devs and (f.get("swap") or _RX_SWAP.search(text, 0, devs[-1].start())):
        n = f.get("devices", 0) + len(devs)
        f.clear()
        f.update(new_facts())
        f["devices"] = n
        text = text[devs[-1].start():]
    ctx, swap, htp, safe = _RX_CTX.findall(text), _RX_SWAP.findall(text), _RX_HTP.findall(text), _RX_SAFE.findall(text)
    if ctx:
        f["ctx"] = list(ctx[-1])
    if swap:
        f["swap"] = list(swap[-1])
    if htp:
        f["htp"] = [float(htp[-1][0]), int(htp[-1][1])]
    if safe:
        f["safe"] = safe[-1]
    if "Vela NPU: on" in text:
        f["npu"] = "on"
    elif f["npu"] is None and "Vela NPU: fallback size" in text:
        f["npu"] = "fallback"
    f["fsr"] = f["fsr"] or "LP: first FSR frame" in text
    f["lp"] = f["lp"] or "LP" in text
    f["fsr1"] = f.get("fsr1") or "2D: ready, FSR 1" in text  # the layer's own stretch of the window to the screen
    sizes = _RX_SIZE.findall(text)
    if sizes:  # PL3: the last word on the game's size: its full-size scene (nothing to upscale) or a smaller window
        f["full"] = sizes[-1][0] or None
    f["fgonly"] = f.get("fgonly") or "LP FGONLY: frame generation only" in text  # PL9: the layer started without FSR
    chain = _RX_FGO_SIZE.findall(text)
    if chain:
        f["chain"] = chain[-1]
    for m in _RX_GENX.finditer(text):  # PL13
        f["genfail"] = None if m.group(2).startswith("on") else {"gen": m.group(1), "vk": int(m.group(3))}
    f["fgloop"] = f.get("fgloop") or FG_LOOP_LINE in text  # PL15: sticky for the run (the layer keeps FG off)
    for m in _RX_FGINIT.finditer(text):  # PL15
        f["fginit"] = None if m.group(3) else {"fmt": int(m.group(1)) if m.group(1) else None, "cs": int(m.group(2)) if m.group(2) else None}
    fg = fg_rates(text)  # PL6
    if fg:
        f["fg"] = fg
    fx = [[float(v) for v in m] for m in _RX_FGX.findall(text)]  # PL11
    if fx:
        f["fgx"] = (f.get("fgx") or [])[-FGX_LINES:] + fx
        f["fgx"] = f["fgx"][-FGX_LINES:]
    n = _RX_FRAMES.findall(text)
    if n:
        f["frames"] = max(f.get("frames", 0), max(map(int, n)))
    return f


def fg_rates(text):
    """PL6: [rendered FPS, shown FPS] of the last presents in text, None when the layer wrote no frame-generation timing. The
    layer's summary line wins when it is the later word; else the LPT lines (kind=real = the game's frames, all = the presents)."""
    stat = list(_RX_FGSTAT.finditer(text))
    lpt = _RX_LPT.findall(text)[-LPT_WINDOW:]
    if stat and (not lpt or stat[-1].start() > text.rfind("LPT q=")):
        x = _RX_FGX.match(text, stat[-1].start())
        if x:  # PL11: shown = the game's frames + the generator's own (no stub, no copy, no held frame)
            return [round(float(x.group(1)), 1), round(float(x.group(1)) + float(x.group(3)), 1)]
        return [round(float(stat[-1].group(1)), 1), round(float(stat[-1].group(2)), 1)]
    if len(lpt) < 3:
        return None
    t0, t1 = int(lpt[0][1]), int(lpt[-1][1])
    span = (t1 - t0) / 1e9
    if span < LPT_MIN_S:
        return None
    shown = (len(lpt) - 1) / span
    real = sum(1 for k, _t in lpt if k == "real")
    return [round(shown * real / len(lpt), 1), round(shown, 1)]


def fg_mean(rows):
    """PL11: the mean of the layer's last FG lines as {r, g, slots, ks, kt, hz}, None when the layer does not say what it generated."""
    if not rows:
        return None
    n = len(rows)
    m = [round(sum(r[i] for r in rows) / n, 1) for i in range(7)]
    return {"r": m[0], "g": m[2], "slots": m[3], "ks": m[4], "kt": m[5], "hz": rows[-1][6]}


def summary(f):
    """What the layer log says (PLUGIN_SPEC.md section 3), from the facts of scan_text; pure."""
    if f is None:
        return None
    pair = f["ctx"] or f["swap"] or [None, None]
    return {"loaded": bool(f["swap"] or f["ctx"] or f["lp"]), "fsr": f["fsr"] and not f["safe"], "render": pair[0], "output": pair[1],
            "npu": f["npu"], "htp_ms": f["htp"][0] if f["htp"] else None, "fallbacks": f["htp"][1] if f["htp"] else None,
            "safe_off": f["safe"], "frames": f.get("frames", 0),
            # PL3: the game's picture (WxH) is not smaller than the screen: nothing to upscale, FSR 4 waits
            "full": f.get("full") if not f["fsr"] else None,
            # FSR 1 fallback: the picture on screen is the layer's plain FSR 1 stretch, FSR 4 never started in this run
            # PL6: [rendered, shown] FPS from the layer's frame-generation timing (None: not written)
            "fg_fps": f.get("fg"),
            # PL11: means of the last lines: r rendered, g generated by the generator, slots, ks / kt skipped for the screen / for time, hz
            "fg_x": fg_mean(f.get("fgx")),
            # PL9: frame generation alone (LP_FGONLY=1) and the size it generates at (the game's own chain)
            "fgonly": bool(f.get("fgonly")), "size": f.get("chain"),
            # PL13: the generator was not created (its name and VkResult): the layer runs only its built-in stub
            "fg_fail": f.get("genfail"),
            # PL15: FG switched off by the layer for this run (the chain was remade in a loop), and FG that could not be set up on the chain
            "fg_loop": bool(f.get("fgloop")),
            "fg_init": f.get("fginit"),
            "stretch": bool(f.get("fsr1") and not f["fsr"] and not f["safe"] and f.get("frames", 0) >= STRETCH_FRAMES)}


def parse_log(text):
    """What the layer log says (PLUGIN_SPEC.md section 3); pure."""
    if not text:
        return None
    return summary(scan_text(text, new_facts()))


def _md5_head(fh, n):
    fh.seek(0)
    return hashlib.md5(fh.read(n)).hexdigest()


def _unquote(v):
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def dxvk_swap(options):
    """(old token, new token) for the player's own DXVK_CONFIG before %command%, None: he has none (ours is added as a token),
    ("", "") : his already names dxvk.tilerMode (left as it is)."""
    toks = launchopts.tokens(options)
    words = [t for t, _, _ in toks]
    ci = words.index(launchopts.CMD) if launchopts.CMD in words else len(words)
    for t in words[:ci]:
        if launchopts.env_name(t) == DXVK_KEY:
            value = _unquote(t[len(DXVK_KEY) + 1:])
            if "dxvk.tilerMode" in value:
                return "", ""
            new = f"{value};{TILER}" if value.strip() else TILER
            q = "'" if '"' in new else '"'
            return t, f"{DXVK_KEY}={q}{new}{q}" if ";" in new else f"{DXVK_KEY}={new}"
    return None


def _replace_env_token(options, old, new):
    """options with the first env token (before %command%) equal to old replaced by new; the rest byte for byte."""
    toks = launchopts.tokens(options)
    words = [t for t, _, _ in toks]
    ci = words.index(launchopts.CMD) if launchopts.CMD in words else len(words)
    for t, a, b in toks[:ci]:
        if t == old:
            return options[:a] + new + options[b:]
    return options


def sharp_snap(v):
    """A slider value on the 0..1 / SHARP_STEP grid, None when it is not a number."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(round(max(0.0, min(1.0, f)) / SHARP_STEP) * SHARP_STEP, 2)


def live_text(picture, sharp, old=None, fg=FG_DEFAULT, where="gpu", fsr=None):
    """The layer's live file: the lines of someone else (old) as they are, then our late=, sharp= and (PL6/PL7) fg= / fgg=.
    UPX1: fsr=0 / 1 only in a run that was switched Off (and On again) while it ran; else no fsr= line (the layer's default 1)."""
    keep = [ln for ln in (old or "").splitlines(True) if ln.strip().partition("=")[0] not in LIVE_KEYS]
    if keep and not keep[-1].endswith("\n"):
        keep[-1] += "\n"
    return "".join(keep) + f"late={LIVE_LATE[picture]}\nsharp={sharp:.2f}\n" + fg_live(fg, where) + ("" if fsr is None else f"fsr={int(fsr)}\n")


def live_text_fgo(fg, old=None, where="gpu"):
    """PL9: the live file of frame generation alone: someone else's lines as they are, then fg= / fgg= (no FSR keys)."""
    keep = [ln for ln in (old or "").splitlines(True) if ln.strip().partition("=")[0] not in LIVE_KEYS]
    if keep and not keep[-1].endswith("\n"):
        keep[-1] += "\n"
    return "".join(keep) + fg_live(fg, where)


class AnyFsr4:
    def __init__(self, assets_dir, home, settings_dir, log=print, chip=None, plugin_pack=None):
        self.assets = assets_dir                                  # <plugin>/assets/anyfsr4
        self.dir = os.path.join(settings_dir, "anyfsr4")
        self.layer_dir = os.path.join(home, ".local", "share", "vulkan", "implicit_layer.d")
        self.rotated = []  # UPX1: appids whose finished run's log reconcile just moved to the .prev.log
        self.plugin_pack = plugin_pack or os.path.join(assets_dir, "pack")  # an offline build's pack
        self.log = log
        self.chip = chip
        self.npu_fg_dir, self.npu_release, self.proc_net_unix = NPU_FG_DIR, NPU_RELEASE, PROC_NET_UNIX  # PLB5

    # -- files

    def layer_found(self):
        return all(os.path.isfile(os.path.join(self.assets, f)) for f in (LIB, MANIFEST, PROVIDER))

    def chip_ok(self):
        return self.chip is None or bool(self.chip.get("fsr4", True))

    def available(self):
        """The panel may offer any-game mode: the layer files are in the plugin and the chip has FSR 4."""
        return self.layer_found() and self.chip_ok()

    def pack_root(self):
        """The folder that holds fsr411/ (FSR4_VK_ASSET_ROOT), None: no checked pack yet."""
        if os.path.isdir(os.path.join(self.plugin_pack, "fsr411")):
            return self.plugin_pack
        root = os.path.join(self.dir, "pack")
        if os.path.isfile(os.path.join(root, MARKER)) and os.path.isdir(os.path.join(root, "fsr411")):
            return root
        return None

    def fetch_pack(self, url=PACK_URL, sha256=PACK_SHA256, opener=None):
        """Download the pack once, check it, unpack it to <settings>/anyfsr4/pack. Returns the pack root. Raises on any
        mismatch; a failed try leaves only its own temporary folder's removal behind (nothing of the player's)."""
        have = self.pack_root()
        if have:
            return have
        os.makedirs(self.dir, exist_ok=True)
        stamp = time.time_ns()
        tmp_zip = os.path.join(self.dir, f"pack-{stamp}.zip.partial")
        part = os.path.join(self.dir, f"pack-{stamp}.partial")
        if opener is None:
            import urllib.request
            opener = lambda u: urllib.request.urlopen(u, timeout=60)  # noqa: E731
        h = hashlib.sha256()
        try:
            with opener(url) as r, open(tmp_zip, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
                    f.write(b)
            if sha256 and h.hexdigest() != sha256:
                raise RuntimeError(f"any-game pack: sha256 {h.hexdigest()[:12]}, expected {sha256[:12]}")
            with zipfile.ZipFile(tmp_zip) as z:
                for n in z.namelist():
                    if n.startswith("/") or ".." in n.split("/") or not n.startswith("fsr411/"):
                        raise RuntimeError(f"any-game pack: unexpected entry {n}")
                z.extractall(part)
            got, count = set_md5(part)
            if got != PACK_SET_MD5 or count != PACK_FILES:
                raise RuntimeError(f"any-game pack: {count} files, set md5 {got[:8]}, expected {PACK_FILES} / {PACK_SET_MD5[:8]}")
            with open(os.path.join(part, MARKER), "w", encoding="utf-8") as f:
                json.dump({"set_md5": got, "files": count, "zip_sha256": h.hexdigest(), "url": url, "at": time.time()}, f)
            os.replace(part, os.path.join(self.dir, "pack"))
        finally:
            for p in (tmp_zip, part):  # our own temporary download only
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.isfile(p):
                    os.remove(p)
        self.log(f"anyfsr4: pack checked ({PACK_FILES} files, {PACK_SET_MD5[:8]}) -> {self.pack_root()}")
        return self.pack_root()

    # -- the layer manifest (like npu.sync_manifest)

    def manifest_text(self):
        with open(os.path.join(self.assets, MANIFEST), encoding="utf-8") as f:
            m = json.load(f)
        layer = m.setdefault("layer", {})
        layer["name"] = LAYER_NAME
        layer["library_path"] = os.path.join(os.path.abspath(self.assets), LIB)
        layer["enable_environment"] = {ENABLE_ENV[0]: ENABLE_ENV[1]}
        layer["disable_environment"] = {DISABLE_ENV[0]: DISABLE_ENV[1]}
        return json.dumps(m, indent=2) + "\n"

    def installed_manifest(self):
        return os.path.join(self.layer_dir, MANIFEST)

    def sync_manifest(self):
        """The manifest is in the user's layer dir while some game has any-game mode on, and only then."""
        path = self.installed_manifest()
        if self.layer_found() and self.layer_games():  # PL9: frame generation alone needs the layer too
            text = self.manifest_text()
            try:
                with open(path, encoding="utf-8") as f:
                    if f.read() == text:
                        return True
            except OSError:
                pass
            os.makedirs(self.layer_dir, exist_ok=True)
            tmp = path + ".upscale-tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
            self.log(f"anyfsr4: layer manifest -> {path}")
            return True
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    ours = json.load(f).get("layer", {}).get("library_path") == os.path.join(os.path.abspath(self.assets), LIB)
            except (OSError, ValueError):
                ours = False
            if ours:  # a manifest someone else put there (a bench) stays
                os.remove(path)
                self.log(f"anyfsr4: layer manifest removed ({path})")
        return False

    # -- per game state

    def _state_path(self, appid):
        return os.path.join(self.dir, f"{appid}.json")

    def read(self, appid):
        try:
            with open(self._state_path(appid), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write(self, appid, st):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._state_path(appid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        os.replace(tmp, self._state_path(appid))

    def is_on(self, appid):
        return bool((self.read(appid) or {}).get("on"))

    def games_on(self):
        try:
            names = [f[:-5] for f in os.listdir(self.dir) if f.endswith(".json")]
        except OSError:
            return []
        return sorted(a for a in names if self.is_on(a))

    def layer_on(self, appid):
        """PL9: our layer is in the game's launch options: FSR 4 on, or frame generation alone."""
        st = self.read(appid) or {}
        return bool(st.get("on") or st.get("fgo"))

    def layer_games(self):
        try:
            names = [f[:-5] for f in os.listdir(self.dir) if f.endswith(".json")]
        except OSError:
            return []
        return sorted(a for a in names if self.layer_on(a))

    def layer_log(self, appid):
        return os.path.join(self.dir, f"layer-{appid}.log")

    def _scan_path(self, appid):  # no .json: games_on lists the *.json state files
        return os.path.join(self.dir, f"layer-{appid}.scan")

    def _read_scan(self, appid):
        try:
            with open(self._scan_path(appid), encoding="utf-8") as f:
                sc = json.load(f)
            return sc if isinstance(sc, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_scan(self, appid, sc):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._scan_path(appid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sc, f)
        os.replace(tmp, self._scan_path(appid))

    def scan_log(self, appid):
        """The facts of the run in the layer log (scan_text), None: no log. Each call reads only the bytes written since the
        last one; the facts and the read offset live in layer-<appid>.scan, so a plugin restart or a long log keeps the
        one-time start lines (PLT1 bug 1: a 256 KB tail of a 2.4 MB log had none of them). Another file (a new run, the
        bench's rewrite) starts over."""
        p = self.layer_log(appid)
        try:
            fh = open(p, "rb")
        except OSError:
            return None
        with fh:
            size = os.fstat(fh.fileno()).st_size
            ino = os.fstat(fh.fileno()).st_ino
            sc = self._read_scan(appid)
            hlen = min(HEAD_SIG, size)
            head = hashlib.md5(fh.read(hlen)).hexdigest()
            sig = sc.get("head")
            same = (isinstance(sc.get("facts"), dict) and sc.get("ino") == ino and 0 <= sc.get("offset", -1) <= size
                    and (sig is None or (sc.get("head_len", 0) <= hlen and _md5_head(fh, sc.get("head_len", 0)) == sig)))
            if not same:
                sc = {"ino": ino, "offset": 0, "facts": new_facts()}
            if sig is None or not same or sc.get("head_len", 0) < hlen:
                sc.update(head=head, head_len=hlen)
            pos, start = sc["offset"], sc["offset"]
            fh.seek(pos)
            while True:
                b = fh.read(LOG_CHUNK)
                if not b:
                    break
                k = b.rfind(b"\n")
                if k < 0:
                    if len(b) < LOG_CHUNK:
                        break  # a line the layer is still writing: next time
                    k = len(b) - 1
                scan_text(b[:k + 1].decode("utf-8", "replace"), sc["facts"])
                pos += k + 1
                fh.seek(pos)
            sc["offset"] = pos
        if pos != start or not same or sig is None:
            self._write_scan(appid, sc)
        return sc["facts"]

    def prev_log(self, appid):
        return os.path.join(self.dir, f"layer-{appid}.prev.log")

    def rotate(self, appid):
        """The layer log becomes layer-<appid>.prev.log (the last finished run only: the one before is replaced); the next
        run writes a new log (the layer opens TUP_LOG_FILE to append)."""
        p = self.layer_log(appid)
        try:
            if os.path.getsize(p) == 0:
                return False
            os.replace(p, self.prev_log(appid))
        except OSError:
            return False
        self._write_scan(appid, {})
        return True

    def reconcile(self, running):
        """main.py every 10 s, with the panel closed too (PLT1 bug 2: 2.4 MB in 2 min and 10 MB in 2.5 min in the two test games,
        into the player's settings folder). A running game's log past LOG_CAP: read to its end (the facts stay in the scan state), then
        cut to 0 bytes in place (the layer appends, its next line lands at the new end). A game that has quit (no write for
        LOG_IDLE_S): its log becomes the .prev.log. Returns the appids whose log was cut or moved."""
        self.end_run_off(running)  # UPX1
        running = {str(a) for a in running}
        for a in self.games_on():  # PL5: Auto picked during a run waits for the next start; that run has ended
            st = self.read(a) or {}
            if (st.get("auto_wait") or st.get("fg_run") or st.get("fg_wait")) and a not in running:  # PL7: fg_run / fg_wait too
                st.update(auto_wait=False, fg_run=None, fg_wait=False)
                self._write(a, st)
        try:
            names = [f[6:-4] for f in os.listdir(self.dir) if f.startswith("layer-") and f.endswith(".log") and not f.endswith(".prev.log")]
        except OSError:
            return []
        done = []
        for appid in sorted(names):
            p = self.layer_log(appid)
            try:
                s = os.stat(p)
            except OSError:
                continue
            if appid in running:
                if s.st_size > LOG_CAP:
                    self.scan_log(appid)
                    try:
                        os.truncate(p, 0)
                    except OSError:
                        continue
                    sc = self._read_scan(appid)
                    sc.update(offset=0, head=None, head_len=0, cuts=sc.get("cuts", 0) + 1)
                    self._write_scan(appid, sc)
                    self.log(f"anyfsr4: {appid} layer log cut at {s.st_size // 1048576} MB (cut {sc['cuts']})")
                    done.append(appid)
            elif s.st_size and time.time() - s.st_mtime > LOG_IDLE_S and self.rotate(appid):
                self.log(f"anyfsr4: {appid} layer log of the last run -> {self.prev_log(appid)}")
                done.append(appid)
                self.rotated.append(appid)  # UPX1: the run's end for the report prompt (main.py takes and clears the list)
        return done

    def picture(self, appid):
        p = (self.read(appid) or {}).get("picture")
        return p if p in PICTURES else PICTURE_DEFAULT

    def sharpness(self, appid):
        v = sharp_snap((self.read(appid) or {}).get("sharp"))
        return SHARP_DEFAULT if v is None else v

    def frame_gen(self, appid, fsr=None):
        """PL7: the frame generation of a game: "off" (default), "amd" or "rife"; one this device cannot run reads as Off.
        PL9: fsr = with FSR 4 (True) or alone (False); None = the game's own mode, and the model Off without a generator = Off."""
        st = self.read(appid) or {}
        if fsr is None:
            if not (st.get("on") or st.get("fgo")):
                return FG_DEFAULT
            fsr = bool(st.get("on"))
        v = FG_LEGACY.get(st.get("fg"), st.get("fg"))
        return v if v in FGS and self.fg_ok(v, fsr) else FG_DEFAULT

    def fg_alone(self, appid):
        """PL9: the stored generator frame generation alone can run (the model goes Off and the generator stays), else Off."""
        v = (self.read(appid) or {}).get("fg")
        v = FG_LEGACY.get(v, v)
        return v if v in FGS and v != FG_DEFAULT and self.fg_ok(v, False) else FG_DEFAULT

    def fg_where(self):
        """PL7: where a generator runs: "gpu" on the PC (no Snapdragon chip), "npu" on the console."""
        return "gpu" if self.chip is None else "npu"

    def npu_fg_missing(self):
        """PLB5: why the console's NPU cannot run RIFE ("npu_pkg": package 15's fg/ contexts, its FG socket or the number is
        missing), None when it can."""
        pkg = npu_package(self.npu_release)
        if pkg is not None and pkg < NPU_FG_PACKAGE:
            return "npu_pkg"
        if not all(os.path.isfile(os.path.join(self.npu_fg_dir, n + ".bin")) for n in NPU_FG_CTX):
            return "npu_pkg"
        return None if fg_socket(self.proc_net_unix) else "npu_pkg"

    def fg10_dir(self):
        return os.path.join(os.path.abspath(self.assets), FG10_DIR)

    def fg10_missing(self):
        """PL9: AMD fg10-npu's parts (R30): the generator library + blob in the plugin and the AMD contexts in the daemon's fg dir."""
        pkg = npu_package(self.npu_release)  # PL10: "npu_pkg16" = no package 16 (or 15's FG part); "amd_set" = our own files gone
        if self.npu_fg_missing() or (pkg is not None and pkg < NPU_FG10_PACKAGE) or \
                not all(os.path.isfile(os.path.join(self.npu_fg_dir, n + ".bin")) for n in NPU_FG10_CTX):
            return "npu_pkg16"
        if not all(os.path.isfile(os.path.join(self.fg10_dir(), n)) for n in (FG10_LIB, FG10_BLOB)):
            return "amd_set"
        return None

    def fg_reason(self, fg, fsr=True):
        """PL7 / PLB5: None when this device can run the generator, else its reason: "not_ready" (AMD on the console) or
        "npu_pkg" (RIFE on a console without Vela NPU package 15). PL9: fsr False = frame generation alone (FG_READY_ONLY);
        "not_ready_fsr" = AMD next to FSR 4 on the console (alone it is offered); "amd_set" = AMD alone without its parts."""
        if fg == "off":
            return None
        where = self.fg_where()
        ready = FG_READY if fsr else FG_READY_ONLY
        if fg not in ready or not ready[fg][where]:
            return "not_ready_fsr" if fsr and FG_READY_ONLY.get(fg, {}).get(where) else "not_ready"
        if fg in FG_NPU and where == "npu":
            return self.npu_fg_missing()
        if fg == "amd" and where == "npu":  # PL13: with FSR 4 too (package 16 + the plugin's fg10 files)
            return self.fg10_missing()
        return None

    def fg_ok(self, fg, fsr=True):
        return fg == "off" or (fg in FG_READY and self.fg_reason(fg, fsr) is None)

    def fg_na(self, fsr=True):
        """PL7: the generators this device cannot run, with their reason (the panel dims them, never hides them)."""
        na = {f: self.fg_reason(f, fsr) for f in FGS}
        return {f: r for f, r in na.items() if r}

    # -- the layer's live file (PL5)

    @staticmethod
    def live_path(appid):
        return os.path.join(LIVE_DIR, f"lp_{appid}.ini")

    def _live_read(self, appid):
        try:
            with open(self.live_path(appid), encoding="utf-8", newline="") as f:
                return f.read()
        except OSError:
            return None

    def _live_put(self, appid, text):
        os.makedirs(LIVE_DIR, exist_ok=True)
        tmp = self.live_path(appid) + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, self.live_path(appid))

    def write_live(self, appid, st):
        """Our late= / sharp= into the running (or next) game's live file; st["live_set"] = what we wrote."""
        pic = st.get("picture") if st.get("picture") in PICTURES else PICTURE_DEFAULT
        shp = sharp_snap(st.get("sharp"))
        fgo = bool(st.get("fgo") and not st.get("on"))  # PL9
        fg = FG_LEGACY.get(st.get("fg"), st.get("fg"))
        fg = fg if fg in FGS and self.fg_ok(fg, not fgo) else FG_DEFAULT
        text = live_text_fgo(fg, self._live_read(appid), self.fg_where()) if fgo else live_text(pic, SHARP_DEFAULT if shp is None else shp, self._live_read(appid), fg, self.fg_where(), st.get("fsr_live"))
        try:
            self._live_put(appid, text)
        except OSError as e:
            self.log(f"anyfsr4: {appid} live file {self.live_path(appid)}: {e}")
            return None
        st["live_set"] = text
        return text

    def _live_off(self, appid, st):
        """Off: the file as it was before On when nobody wrote it since, else only our lines out (no file when nothing is left)."""
        now = self._live_read(appid)
        prev = st.pop("live_prev", None)
        mine = st.pop("live_set", None)
        if now is None:
            return
        if mine is not None and now == mine:
            back = prev
        else:
            back = "".join(ln for ln in now.splitlines(True) if ln.strip().partition("=")[0] not in LIVE_KEYS) or prev
        try:
            if back is None:
                os.remove(self.live_path(appid))  # the plugin's own file in /tmp: it made it at On
            else:
                self._live_put(appid, back)
        except OSError as e:
            self.log(f"anyfsr4: {appid} live file back: {e}")

    def sync_live(self):
        """Plugin start (a reboot empties /tmp): every game that is on gets its live file again."""
        for appid in self.layer_games():  # PL9
            st = self.read(appid) or {}
            if self._live_read(appid) != st.get("live_set"):
                self.write_live(appid, st)
                self._write(appid, st)

    def manifest_out(self):
        """V08 (audit 2026-11-09): plugin uninstall: our manifest leaves the user's layer dir (it names a library inside the
        plugin folder); one somebody else put there stays. The next plugin start writes it again. True: ours was there."""
        path = self.installed_manifest()
        try:
            with open(path, encoding="utf-8") as f:
                ours = json.load(f).get("layer", {}).get("library_path") == os.path.join(os.path.abspath(self.assets), LIB)
        except (OSError, ValueError):
            return False
        if not ours:
            return False
        os.remove(path)
        self.log(f"anyfsr4: layer manifest removed at uninstall ({path})")
        return True

    def ensure_live(self):
        """V04 (audit 2026-11-09): the layer's live file of a game that is on is there. sync_live runs only at plugin start;
        when /tmp is cleaned while the plugin runs the layer started with its defaults (no late= / sharp= / fg= of the
        player's). Only a MISSING file is written (an existing one may hold a run's own state); a game switched Off in its
        running game is left alone. Returns the appids written again."""
        back = []
        for appid in self.layer_games():
            st = self.read(appid) or {}
            if st.get("live_set") is None or st.get("run_off") or os.path.exists(self.live_path(appid)):
                continue
            if self.write_live(appid, st) is not None:
                self._write(appid, st)
                back.append(appid)
                self.log(f"anyfsr4: {appid} live file was gone, written again")
        return back

    def tokens(self, appid, npu, pack, picture=PICTURE_DEFAULT, sharp=SHARP_DEFAULT, fg=FG_DEFAULT):
        """Our env tokens (the NPU layer's own VELA_NPU=1 comes from npu.enable, on top). npu: the NPU part is ready."""
        t = [f"{ENABLE_ENV[0]}={ENABLE_ENV[1]}", f"TUP_OUTPUT={OUTPUT}", f"LP_OUT={OUTPUT}", "LP_FSR=1", "LP_FAST=1",
             f"LP_NPU={1 if npu else 0}", f"LP_PROVIDER={os.path.join(os.path.abspath(self.assets), PROVIDER)}",
             f"FSR4_VK_ASSET_ROOT={os.path.abspath(pack)}", f"TUP_LOG_FILE={self.layer_log(appid)}", "TUP_LOG_EVERY=0", QUIET] + list(PICTURES[picture]) + \
            ([f"{SHARP_KEY}={sharp:.2f}"] if sharp != SHARP_DEFAULT else []) + list(fg_env(fg, self.fg_where())) + self.amd_env(fg) + self.rife_env(fg) + fg_mode_env(fg) + list(LBOX_ENV)
        bad = [x for x in t if re.search(r"\s|[\"';]", x)]
        if bad:
            raise RuntimeError(f"a path with a space or quote cannot go into the launch options: {bad[0]}")
        return t

    def amd_env(self, fg):
        """PL13 (FG9 AMD_FSR_GO, OWNDEV + hys + NETRES 720p): AMD fg10-npu next to FSR 4 gets the same env as AMD alone; none on the PC."""
        return self.fg10_env() if fg == "amd" and self.fg_where() == "npu" else []

    def rife_env(self, fg):
        """PL10: RIFE's start switches on the console (R31: PREREC on; PL15: FAST=31, hys); none on the PC."""
        return list(RIFE_NPU_ENV) if fg == "rife" and self.fg_where() == "npu" else []

    def fg10_env(self):
        """PL9: AMD fg10-npu's env as R30 ran it (fg28tb / ub, OWNDEV): bench-only keys left out (LP_FG10_LOG, LP_FG10_PASS_TIMING,
        LP_TIMING, the test socket LP_FG10_NPU_SOCK=npd1_fg: the generator's default is the installed daemon's fsr4npud_fg)."""
        d = self.fg10_dir()
        # PL10 (FG11/RC_NOTE, R29): own HIGH device + the hys mode-B rule together; 720p network (package 16 has 720p only).
        # LP_FG_OWNFENCE is the layer's own default in FG-only (507eecf); RIFE's OWNDEV / PREREC stay off (R31).
        return ["LP_FGGEN_SHAREQ=1", "LP_FGGEN_OWNDEV=1", "LP_FGMB_RULE=hys", f"LP_FGGEN_LIB={os.path.join(d, FG10_LIB)}", f"LP_FG10_DIR={d}",
                f"LP_FG10_BLOB={os.path.join(d, FG10_BLOB)}", "LP_FG10_COMPILE_THREADS=0",
                f"LP_FG10_CACHE_DIR={os.path.join(os.path.abspath(self.dir), 'fg10cache')}", "LP_FG10_SPIN=1",
                f"LP_FG10_NETRES={FG10_NETRES}"] + list(FG10_R6C_ENV)

    def fgonly_tokens(self, appid, fg):
        """PL9: our env tokens of frame generation alone: the layer, LP_FGONLY=1, the generator, the layer log; no FSR token."""
        where = self.fg_where()
        t = [f"{ENABLE_ENV[0]}={ENABLE_ENV[1]}", f"{FGONLY_KEY}=1"] + list(fg_env(fg, where)) + \
            (self.fg10_env() if fg == "amd" and where == "npu" else []) + self.rife_env(fg) + fg_mode_env(fg) + \
            [f"TUP_LOG_FILE={self.layer_log(appid)}", "TUP_LOG_EVERY=0", QUIET]
        bad = [x for x in t if re.search(r"\s|[\"';]", x)]
        if bad:
            raise RuntimeError(f"a path with a space or quote cannot go into the launch options: {bad[0]}")
        return t

    def fg_only(self, appid, launch_options, fg, running=False, scan=None, kit_on=False):
        """PL9 (variant A): frame generation without the upscaler, the model Off. fg "amd" / "rife": our FG-only tokens in the
        launch options (a generator change swaps them; a running game that has the layer switches at once through fgg=, one started
        without it gets frame generation at its next start). "off": the options back (exactly the old ones when nobody touched
        them), the live file back (a running game: fg=0 now, the file back when the run ends). {"launch_options"}."""
        if fg not in FGS:
            raise RuntimeError(f"unknown frame generation {fg}")
        if launch_options is None:
            raise RuntimeError("Steam's launch options were not read")
        st = self.read(appid) or {}
        if st.get("on"):
            raise RuntimeError("FSR 4 is on for this game: its frame generation goes through enable")
        if fg != FG_DEFAULT and not self.fg_ok(fg, False):
            raise RuntimeError(f"frame generation {fg} is not ready on this device")
        if fg == FG_DEFAULT:
            st["fg"] = FG_DEFAULT
            if not st.get("fgo"):
                self._write(appid, st)
                return {"launch_options": launch_options}
            return self._fgo_leave(appid, launch_options, st, running)
        if kit_on:  # PL13 (owner: FG does not depend on the upscaler): the layer in FG-only mode next to Vela's kit (OptiScaler)
            self.log(f"anyfsr4: {appid} frame generation alone next to Vela's in-game upscaler")
        if (scan or {}).get("anticheat"):
            raise RuntimeError("anti-cheat in the game, the layer is not used")
        if not self.layer_found():
            raise RuntimeError(f"plugin files assets/anyfsr4 ({LIB}, {MANIFEST}, {PROVIDER}) are missing")
        if st.get("fgo"):
            if fg == FG_LEGACY.get(st.get("fg"), st.get("fg")) and launch_options == st.get("launch_set"):
                if not st.get("run_off") and self._live_read(appid) != st.get("live_set"):
                    self.write_live(appid, st)
                    self._write(appid, st)
                return {"launch_options": launch_options}
            # PL13: options someone else edited since (Vela's kit put its tokens in): the new exact base is them without ours
            changed = launch_options != st.get("launch_set")
            launch_options = self._remove(launch_options, st)
            prev, live_prev, installed = (launch_options if changed else st.get("launch_prev")), st.get("live_prev"), st.get("installed_at")
        else:
            prev = launch_options
            # a run switched Off while it ran keeps the live file it had before On for the run's end (UPX1)
            live_prev = st["live_prev"] if "live_prev" in st else self._live_read(appid)
            if not running:
                self.rotate(appid)  # an earlier period's log is not this one's
            installed = time.time()
        base = launch_options
        swap = dxvk_swap(base)
        if swap and swap[0]:
            base = _replace_env_token(base, swap[0], swap[1])
        extra = [] if swap else [f"{DXVK_KEY}={TILER}"]
        new, rec = launchopts.add(base, self.fgonly_tokens(appid, fg) + extra)
        keep = {k: st[k] for k in ("picture", "sharp", "run_off", "fsr_live", "off_at") if k in st}
        st2 = {"on": False, "fgo": True, "launch_prev": prev, "launch_set": new, "added": rec,
               "dxvk_swap": list(swap) if swap and swap[0] else None, "fg": fg, "live_prev": live_prev,
               "installed_at": installed or time.time(), "updated_at": time.time(), **keep}
        if st.get("run_off"):  # the FSR run switched Off still runs: its live file (fsr=0 fg=0) stays until it ends
            st2["live_set"] = st.get("live_set")
        else:
            self.write_live(appid, st2)
        self._write(appid, st2)
        self.sync_manifest()
        self.log(f"anyfsr4: {appid} frame generation alone ({fg}), launch: {new}")
        return {"launch_options": new}

    def _fgo_leave(self, appid, launch_options, st, running):
        """PL9: frame generation alone -> Off (the model is Off already): everything back as before."""
        if launch_options == st.get("launch_set"):
            restored = st.get("launch_prev") or ""
        else:
            restored = self._remove(launch_options, st)
        if st.get("run_off"):
            pass  # the FSR run switched Off earlier still runs: end_run_off gives its file back
        elif running and self.layer_in_run(appid):
            tmp = {**st, "fg": FG_DEFAULT}  # the running game's generator off now (live fg=0); the file back when the run ends
            self.write_live(appid, tmp)
            st["live_set"] = tmp.get("live_set")
            st["fgo_run"] = True
        else:
            self._live_off(appid, st)
        st.update({"fgo": False, "fg": FG_DEFAULT, "off_at": time.time()})
        self._write(appid, st)
        self.sync_manifest()
        self.log(f"anyfsr4: {appid} frame generation alone off, launch: {restored}")
        return {"launch_options": restored}

    # -- on / off

    def enable(self, appid, launch_options, npu, scan=None, kit_on=False, picture=None, sharp=None, running=False, fg=None):
        """{"launch_options", "resolution"}: the options to set; "resolution" is always None (PL3: Vela never sets the game's
        window). picture: a PICTURES key to switch to (None: the one the game has); sharp: 0..1 (None: the game's). PL5: both
        also go into the layer's live file at once (running: the game runs now, for the "when the game starts" note of Auto)."""
        if launch_options is None:
            raise RuntimeError("Steam's launch options were not read")
        if kit_on:
            raise RuntimeError("Vela's in-game upscaler is on for this game: switch it off first")
        if (scan or {}).get("anticheat"):
            raise RuntimeError("anti-cheat in the game, the layer is not used")
        if not self.layer_found():
            raise RuntimeError(f"plugin files assets/anyfsr4 ({LIB}, {MANIFEST}, {PROVIDER}) are missing")
        if not self.chip_ok():
            raise RuntimeError("FSR 4 is not offered on this chip")
        if picture is not None and picture not in PICTURES:
            raise RuntimeError(f"unknown picture mode {picture}")
        if sharp is not None and sharp_snap(sharp) is None:
            raise RuntimeError(f"sharpness is not a number: {sharp!r}")
        if fg is not None and fg not in FGS:
            raise RuntimeError(f"unknown frame generation {fg}")
        if fg is not None and not self.fg_ok(fg):
            raise RuntimeError(f"frame generation {fg} is not ready on this device")
        pack = self.pack_root()
        if not pack:
            raise RuntimeError("the any-game pack is not downloaded")
        st = self.read(appid) or {}
        pic = picture or self.picture(appid)
        shp = sharp_snap(sharp) if sharp is not None else self.sharpness(appid)
        old_pic = self.picture(appid)
        fgv = fg or self.frame_gen(appid, True if (st.get("on") or st.get("fgo")) else None)  # PL6; PL9: the game's choice with FSR
        # Auto picked while the game runs with another mode: the layer keeps that mode until the game starts again
        in_run = bool(running and (st.get("on") or st.get("run_off")))  # UPX1: Off and On in one run is still that run
        wait = bool(in_run and pic == "auto" and (old_pic != "auto" or st.get("auto_wait")))
        # PL7 (PLB4): the layer prepares frame generation only with LP_FG at the start. fg_run = the choice this run started with
        # (taken at the first change during the run, cleared when it ends); a run started with Off gets AMD / RIFE at its next start
        fg_run = (st.get("fg_run") or self.frame_gen(appid)) if in_run else None
        fg_wait = bool(fg_run == "off" and fgv != "off")
        legacy = {}  # PL3: a game a PL1 / PL2 build switched on keeps its old override for the one-time cleanup on Off
        if st.get("fsr_live") is not None:  # UPX1: the run that was switched Off and On again keeps its fsr=1 until it ends
            legacy["fsr_live"] = st["fsr_live"]
        if st.get("on"):
            if launch_options == st.get("launch_set") and pic == old_pic and shp == self.sharpness(appid) \
                    and fgv == self.frame_gen(appid):
                if self._live_read(appid) != st.get("live_set"):
                    self.write_live(appid, st)
                    self._write(appid, st)
                return {"launch_options": launch_options, "resolution": None}
            # V01 (audit 2026-11-09): options the player edited while Vela was on are the new "before Vela" (ours taken out), as
            # fg_only does; before, Off after "edit, then a change in the panel" gave back the options of the first On
            changed = launch_options is not None and launch_options != st.get("launch_set")
            launch_options = self._remove(launch_options, st)  # changed since, or another picture: ours out, in again below
            prev = launch_options if changed else st.get("launch_prev")
            legacy["live_prev"] = st.get("live_prev")
            if "resolution_prev" in st:
                legacy["resolution_prev"] = st["resolution_prev"]
        elif st.get("fgo"):
            # PL9: from frame generation alone to FSR 4: our FG-only tokens out (the record kept), a new on-period (FSR loads at the
            # next start; a running game's log is moved away, so the panel says «start the game again»)
            changed = launch_options is not None and launch_options != st.get("launch_set")  # V01: as above
            launch_options = self._remove(launch_options, st)
            prev = launch_options if changed else st.get("launch_prev")
            legacy["live_prev"] = st.get("live_prev")
            st = {**st, "installed_at": None}
            self.rotate(appid)
        elif running and st.get("run_off"):
            # UPX1 (owner 2026-11-07 «отключил апскейл и включил говорит нужен перезапуск»): Off in this run left the layer in the
            # game (it loads only at the start) with live fsr=0; On again in the same run = fsr=1, no restart. The log is this run's.
            prev = launch_options
            legacy["live_prev"] = st.get("live_prev")
            legacy["fsr_live"] = 1
            legacy["run_off"] = False
            self.log(f"anyfsr4: {appid} on again in the running game: live fsr=1 (the layer has been in the game since its start)")
        else:
            prev = launch_options
            legacy["live_prev"] = self._live_read(appid)  # PL5: the layer's live file before On (None: there was none)
            self.rotate(appid)  # an earlier on-period's log is not this run's
        base = launch_options
        swap = dxvk_swap(base)
        if swap and swap[0]:
            base = _replace_env_token(base, swap[0], swap[1])
        extra = [] if swap else [f"{DXVK_KEY}={TILER}"]
        new, rec = launchopts.add(base, self.tokens(appid, npu, pack, pic, shp, fgv) + extra)
        st = {"on": True, "launch_prev": prev, "launch_set": new, "added": rec, "dxvk_swap": list(swap) if swap and swap[0] else None,
              "picture": pic, "sharp": shp, "fg": fgv, "auto_wait": wait, "fg_run": fg_run, "fg_wait": fg_wait, "npu": bool(npu), "installed_at": st.get("installed_at") or time.time(), "updated_at": time.time(),
              **legacy}
        self.write_live(appid, st)
        self._write(appid, st)
        self.sync_manifest()
        self.log(f"anyfsr4: {appid} on, launch: {new}, picture {pic}, sharpness {shp:.2f}, frame generation {fgv}, live late={LIVE_LATE[pic]} "
                 f"{fg_live(fgv, self.fg_where()).strip().replace(chr(10), ' ')}; "
                 "the game's window is the player's")
        return {"launch_options": new, "resolution": None}

    def set_picture(self, appid, picture):
        """The picture mode of a game that is not on: kept for its next On (no launch options touched)."""
        if picture not in PICTURES:
            raise RuntimeError(f"unknown picture mode {picture}")
        st = self.read(appid) or {}
        if st.get("on"):
            raise RuntimeError("the game is on: the picture mode goes through enable")
        st["picture"] = picture
        st.pop("auto_wait", None)
        self._write(appid, st)
        return picture

    def set_sharp(self, appid, value):
        """PL5: the sharpness of a game that is not on: kept for its next On."""
        v = sharp_snap(value)
        if v is None:
            raise RuntimeError(f"sharpness is not a number: {value!r}")
        st = self.read(appid) or {}
        if st.get("on"):
            raise RuntimeError("the game is on: the sharpness goes through enable")
        st["sharp"] = v
        self._write(appid, st)
        return v

    def set_fg(self, appid, fg):
        """PL6: the frame generation of a game that is not on: kept for its next On."""
        if fg not in FGS:
            raise RuntimeError(f"unknown frame generation {fg}")
        if not self.fg_ok(fg):
            raise RuntimeError(f"frame generation {fg} is not ready on this device")
        st = self.read(appid) or {}
        if st.get("on"):
            raise RuntimeError("the game is on: frame generation goes through enable")
        st["fg"] = fg
        self._write(appid, st)
        return fg

    @staticmethod
    def _remove(options, st):
        out = launchopts.remove(options, st.get("added"))
        sw = st.get("dxvk_swap")
        if out is not None and sw:
            out = _replace_env_token(out, sw[1], sw[0])
        return out

    def layer_in_run(self, appid):
        """UPX1: the running game's log says our layer is in it (it loads only at the game's start, LP0_ENABLE)."""
        try:
            if os.path.getsize(self.layer_log(appid)) == 0:
                return False
        except OSError:
            return False
        s = summary(self.scan_log(appid))
        return bool(s and s["loaded"])

    def disable(self, appid, launch_options, resolution=None, running=False):
        """{"launch_options", "resolution"}: exactly the options from before when nobody touched them since; "resolution" is None
        (Steam's override is the player's), except the one-time cleanup of a PL1 / PL2 build's own override: the state has
        "resolution_prev" and Steam's override (resolution, as the panel read it; None = not read) is still LEGACY_WINDOW.
        UPX1: Off in a running game that has the layer = live fsr=0 at once (the game's own picture); the live file goes back to
        what it was when that run ends (reconcile), the launch options at once (the next start has no layer)."""
        st = self.read(appid)
        if not st or not st.get("on"):
            return {"launch_options": launch_options, "resolution": None}
        live_off = bool(running and self.layer_in_run(appid))
        if launch_options is None or launch_options == st.get("launch_set"):
            restored = st.get("launch_prev") or ""
        else:
            restored = self._remove(launch_options, st)
        res = None
        if "resolution_prev" in st:
            old = st.pop("resolution_prev")
            if resolution is None or str(resolution).strip().lower().replace("\u00d7", "x") == LEGACY_WINDOW:
                res = old or "Default"
            self.log(f"anyfsr4: {appid} one-time cleanup of an old test build's window override: "
                     f"{('back to ' + res) if res else ('left as it is: ' + str(resolution) + ' is not ours')}")
        if live_off:
            st["fsr_live"] = 0
            tmp = {**st, "fg": FG_DEFAULT}  # Off is Off for frame generation too (live fg=0); st keeps the player's choice
            self.write_live(appid, tmp)  # live_prev stays for the end of the run
            st["live_set"] = tmp.get("live_set")
            st["run_off"] = True
        else:
            self._live_off(appid, st)  # PL5
            for k in ("auto_wait", "fg_run", "fg_wait", "fsr_live", "run_off"):
                st.pop(k, None)
        st.update({"on": False, "off_at": time.time()})
        self._write(appid, st)
        self.sync_manifest()
        self.log(f"anyfsr4: {appid} off, launch: {restored}" + ("; live fsr=0 in the running game" if live_off else ""))
        return {"launch_options": restored, "resolution": res}

    def end_run_off(self, running):
        """UPX1: a run switched Off while it ran has ended: its live file back as before On, the run's marks gone. A game that is
        on again keeps its file without the fsr= line."""
        running = {str(a) for a in running}
        try:
            names = [f[:-5] for f in os.listdir(self.dir) if f.endswith(".json")]
        except OSError:
            return []
        done = []
        for a in sorted(names):
            if a in running:
                continue
            st = self.read(a) or {}
            if not (st.get("run_off") or st.get("fsr_live") is not None or st.get("fgo_run")):  # PL9: fgo_run
                continue
            if st.get("on") or st.get("fgo"):  # PL9: frame generation alone after an FSR run switched Off: its own file now
                st.pop("fsr_live", None)
                st.pop("run_off", None)
                st.pop("fgo_run", None)
                self.write_live(a, st)
            else:
                self._live_off(a, st)
                for k in ("auto_wait", "fg_run", "fg_wait", "fsr_live", "run_off", "fgo_run"):
                    st.pop(k, None)
            self._write(a, st)
            self.log(f"anyfsr4: {a} the run switched off / on while it ran has ended: live file back")
            done.append(a)
        return done

    # -- status for the panel

    def status(self, appid, npu_ready=False, running=None):
        st = self.read(appid) or {}
        on = bool(st.get("on"))
        fgo = bool(st.get("fgo")) and not on  # PL9: frame generation alone
        if (st.get("auto_wait") or st.get("fg_run") or st.get("fg_wait")) and running is False:  # the run that kept the old mode
            st.update(auto_wait=False, fg_run=None, fg_wait=False)  # has ended: the next start has the new one (PL7: frame generation too)
            self._write(appid, st)
        log = None
        if on or fgo:
            try:
                if os.stat(self.layer_log(appid)).st_mtime >= (st.get("installed_at") or 0):
                    log = summary(self.scan_log(appid))
            except OSError:
                log = None
        return {"available": self.available(), "layer_found": self.layer_found(), "pack": bool(self.pack_root()),
                "pack_mb": PACK_MB, "on": on, "npu": bool(st.get("npu")) if on else bool(npu_ready), "min_window": MIN_WINDOW,
                "output": OUTPUT, "log": log, "picture": self.picture(appid), "pictures": list(PICTURES),
                # PL5: the modes that switch in the running game; restart: Auto was picked during a run (it takes effect when the
                # game starts)
                "picture_live": list(PICTURE_LIVE), "restart": bool(on and st.get("auto_wait")),
                "sharp": {"value": self.sharpness(appid), "default": SHARP_DEFAULT, "step": SHARP_STEP},
                "fg": self.frame_gen(appid), "fgs": list(FGS), "fg_na": self.fg_na(on), "fg_restart": bool(on and st.get("fg_wait")),
                # PL9: frame generation without the upscaler (the panel's Off note and status line); fg_na above is for the mode a
                # pick would give: with FSR 4 when it is on, else alone
                "fg_only": fgo,
                # UPX1: Off in this run: the layer stays in the game until it closes, FSR 4 is off in it now (live fsr=0)
                "live_off": bool(not on and st.get("run_off") and running is not False)}  # PL6; PL7 Off / AMD / RIFE, fg_na
