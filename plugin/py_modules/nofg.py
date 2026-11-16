"""NOFG (owner 2026-11-15: «Выпиливай генерацию кадров. Мы позиционируем себя только на замены апскейлеров в играх и что бы они
работали в нпу»): frame generation is out of Vela. Vela replaces a game's own upscaler (its DLSS / FSR / XeSS input through
OptiScaler) and runs it on the NPU; nothing else. The lp0 Vulkan layer (py_modules/anyfsr4.py, now _removed/py_modules) is gone with
everything it did: AMD fg10 / RIFE frame generation alone (LP_FGONLY=1, for a game without an upscaler input or next to Vela's kit)
and the older builds' "FSR 4 for any game".

This module is only the one-time way back for a console an older Vela left with the layer in a game. It reads the layer's per-game
state as the older build wrote it (<settings>/anyfsr4/<appid>.json) and takes back what that build put in, exactly as its own Off did:
- Steam's launch options (the panel's launch_fix, launch_pending): the options from before byte for byte when nobody touched them
  since (they equal the state's launch_set), else exactly the tokens the state lists as added out and the player's DXVK_CONFIG text
  back (dxvk_swap); never while the game runs (its run keeps what it started with);
- the layer's live file /tmp/vela-live/lp_<appid>.ini: the file as it was before (live_prev) when nobody wrote it since, else only
  the layer's lines (LIVE_KEYS) out; not while the game runs (start, then reconcile when the run has ended);
- the layer manifest in the user's implicit layer dir, when it names the library inside this plugin's folder: moved aside to
  <settings>/anyfsr4/removed/ (never deleted); one somebody else put there stays.
The state file stays, with on / fgo false and the time of the way back (nofg_at): nothing of ours is left in the game. Vela's kit and
the NPU layer of that game (its upscaler settings) are not touched. No game names, no per-game keys.
"""
import json
import os
import time

import launchopts

STATE = "anyfsr4"                      # <settings>/anyfsr4: the layer's state folder of the older builds
LIB = "libVkLayer_VELA_lp0.so"         # the layer library the older builds shipped in <plugin>/assets/anyfsr4
MANIFEST = "VkLayer_VELA_lp0.json"
LIVE_DIR = "/tmp/vela-live"            # the layer's live file lp_<SteamAppId>.ini (Vela's kit file <appid>.ini is live.py's)
LIVE_KEYS = ("late", "sharp", "fg", "fgg", "fsr")  # the layer's live keys (the older anyfsr4.LIVE_KEYS)
ASIDE = "removed"                      # <settings>/anyfsr4/removed: the layer manifest moved here


def _replace_env_token(options, old, new):
    """options with the first env token (before %command%) equal to old replaced by new; the rest byte for byte (anyfsr4's)."""
    toks = launchopts.tokens(options)
    words = [t for t, _, _ in toks]
    ci = words.index(launchopts.CMD) if launchopts.CMD in words else len(words)
    for t, a, b in toks[:ci]:
        if t == old:
            return options[:a] + new + options[b:]
    return options


def restore(options, st):
    """Steam's options without the layer: the exact previous ones when nobody touched them since, else exactly our tokens out and
    the player's DXVK_CONFIG text back. None stays None (not read: nothing is written)."""
    if options is None:
        return None
    if options == st.get("launch_set") and isinstance(st.get("launch_prev"), str):
        return st["launch_prev"]
    out = launchopts.remove(options, st.get("added"))
    sw = st.get("dxvk_swap")
    if out is not None and sw:
        out = _replace_env_token(out, sw[1], sw[0])
    return out


class NoFg:
    def __init__(self, assets_dir, home, settings_dir, log=print):
        self.assets = assets_dir  # <plugin>/assets/anyfsr4: where the older builds' layer library was (no longer in the zip)
        self.dir = os.path.join(settings_dir, STATE)
        self.layer_dir = os.path.join(home, ".local", "share", "vulkan", "implicit_layer.d")
        self.log = log
        self.live_dir = LIVE_DIR
        self._live_left = set()  # games whose layer live file still waits for the end of their run

    # -- the older builds' state

    def _state_path(self, appid):
        return os.path.join(self.dir, f"{appid}.json")

    def read(self, appid):
        try:
            with open(self._state_path(appid), encoding="utf-8") as f:
                st = json.load(f)
            return st if isinstance(st, dict) else None
        except (OSError, ValueError):
            return None

    def _write(self, appid, st):
        tmp = self._state_path(appid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        os.replace(tmp, self._state_path(appid))

    def games(self):
        try:
            return sorted(f[:-5] for f in os.listdir(self.dir) if f.endswith(".json"))
        except OSError:
            return []

    def in_launch(self, appid):
        """An older build's layer is still in the game's Steam launch options (FSR 4 for any game on, or frame generation alone)."""
        st = self.read(appid) or {}
        return bool(st.get("on") or st.get("fgo"))

    # -- the live file

    def live_path(self, appid):
        return os.path.join(self.live_dir, f"lp_{appid}.ini")

    def _live_off(self, appid, st):
        """The layer's live file as it was before the older build wrote it when nobody wrote it since, else only the layer's lines
        out (no file when nothing is left and there was none). True: st changed."""
        if "live_set" not in st and "live_prev" not in st:
            return False
        prev = st.pop("live_prev", None)
        mine = st.pop("live_set", None)
        try:
            with open(self.live_path(appid), encoding="utf-8", newline="") as f:
                now = f.read()
        except OSError:
            return True
        if mine is not None and now == mine:
            back = prev
        else:
            back = "".join(ln for ln in now.splitlines(True) if ln.strip().partition("=")[0] not in LIVE_KEYS) or prev
        try:
            if back is None:
                os.remove(self.live_path(appid))  # the older build's own file in /tmp: it made it
            else:
                tmp = self.live_path(appid) + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    f.write(back)
                os.replace(tmp, self.live_path(appid))
            self.log(f"nofg: {appid} the layer's live file back as before frame generation")
        except OSError as e:
            self.log(f"nofg: {appid} live file back: {e}")
        return True

    def _settle(self, appid, running):
        """The live file of one game, unless it runs; the run marks of the older build gone. True when nothing is left to wait for."""
        if appid in running:
            return False
        st = self.read(appid)
        if not st:
            return True
        changed = self._live_off(appid, st)
        for k in ("auto_wait", "fg_run", "fg_wait", "fsr_live", "run_off", "fgo_run"):
            if k in st:
                st.pop(k)
                changed = True
        if changed:
            self._write(appid, st)
        return True

    # -- the layer manifest

    def manifest_aside(self):
        """The older builds' layer manifest out of the user's implicit layer dir (moved to <settings>/anyfsr4/removed), when it names
        the library inside this plugin's folder; one somebody else put there stays. The path it was moved to, None: nothing moved."""
        path = os.path.join(self.layer_dir, MANIFEST)
        try:
            with open(path, encoding="utf-8") as f:
                lib = json.load(f).get("layer", {}).get("library_path")
        except (OSError, ValueError, AttributeError):
            return None
        if lib != os.path.join(os.path.abspath(self.assets), LIB):
            return None
        aside = os.path.join(self.dir, ASIDE)
        os.makedirs(aside, exist_ok=True)
        dst = os.path.join(aside, f"{MANIFEST}.{time.strftime('%Y%m%d-%H%M%S')}")
        n = 1
        while os.path.exists(dst):
            n += 1
            dst = os.path.join(aside, f"{MANIFEST}.{time.strftime('%Y%m%d-%H%M%S')}.{n}")
        os.replace(path, dst)
        self.log(f"nofg: the frame-generation layer's manifest moved out of {self.layer_dir} to {dst}")
        return dst

    # -- the plugin's steps

    def start(self, running):
        """Plugin start: the manifest aside, the live files of the games that are not running back; the running ones wait (reconcile).
        Returns the games whose layer is still in Steam's launch options (the panel's launch_fix takes it out)."""
        running = {str(a) for a in running}
        self.manifest_aside()
        self._live_left = {a for a in self.games() if not self._settle(a, running)}
        return [a for a in self.games() if self.in_launch(a)]

    def reconcile(self, running):
        """The 10 s loop: a run that had the layer has ended: its live file back. Nothing to do once every game is settled."""
        if not self._live_left:
            return []
        running = {str(a) for a in running}
        done = sorted(a for a in self._live_left if self._settle(a, running))
        self._live_left -= set(done)
        return done

    def launch_pending(self, appid, running):
        """The panel's launch_fix has work: the layer is in the game's Steam options and the game is not running."""
        return str(appid) not in {str(a) for a in running} and self.in_launch(appid)

    def launch_fix(self, appid, launch_options, running=()):
        """Steam's options without the layer (restore); the state Off, the live file back. None (not read): nothing changes."""
        st = self.read(appid)
        if launch_options is None or not st or not (st.get("on") or st.get("fgo")) or str(appid) in {str(a) for a in running}:
            return launch_options
        out = restore(launch_options, st)
        self._live_off(appid, st)
        for k in ("auto_wait", "fg_run", "fg_wait", "fsr_live", "run_off", "fgo_run"):
            st.pop(k, None)
        was = "FSR 4 for any game" if st.get("on") else "frame generation"
        st.update({"on": False, "fgo": False, "fg": "off", "nofg_at": time.time()})
        self._write(appid, st)
        self._live_left.discard(str(appid))
        self.log(f"nofg: {appid} {was} is no longer in Vela: Off, launch: {out}")
        return out
