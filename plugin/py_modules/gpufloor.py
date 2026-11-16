"""GPU floor (0.8.2): a minimum GPU clock while a game Vela upscales is running.

Why: the Balanced profile (armada-powerd, gpu_min=0.0) lets simple_ondemand drop the Adreno to 220 MHz; the Vela chain
then runs about 3x slower (FSR 4.1 Lite + NPU, 240 frames: 4.65 ms/frame pinned at 680 MHz, 13.2 ms unpinned).

Where Armada keeps a GPU minimum (build 20261010.c3d178c): only per power
profile, `gpu_min` in /usr/share/armada/power-profiles.conf + /etc/armada/power-profiles.conf (root, written by the
root plugin Armada Control). Per-game tweaks (/etc/armada/game-tweaks.json, root) carry no GPU key. So there is no
user-writable per-game GPU minimum in Armada; Vela keeps its own per-game value in <settings>/gpufloor.json and applies
it to /sys/class/devfreq/<gpu>/min_freq, which udev makes group-writable for wheel (60-armada-perf-acls.rules; the
user armada is in wheel). armada-powerd writes min_freq only when it applies a profile (boot, profile or GPU level
change, Reload, resume), never on a timer, so the reconcile loop puts the floor back within 10 s after that.

Rules:
- on: the game has Vela on (sgsr3 enable) and its floor is not 0; applied only while that game runs.
- never lowers a higher minimum (Performance profile gpu_min=1.0, a pinned clock); never above the profile's max_freq.
- userspace governor (Armada's manual GPU clock) is the user's choice: left alone.
- restore: when no floored game runs, min_freq goes back to the value before Vela raised it, but only if min_freq still
  holds Vela's value (powerd may have applied a profile meanwhile: then its value stays).

Access fixes (the plugin log showed "cannot write ... min_freq: [Errno 13]" 30 times; samples of min_freq flipped 220/680):
- Decky drops plugin processes to uid 1000 WITHOUT supplementary groups (/proc/<pid>/status "Groups:" empty), so the
  udev group-write for wheel never applied and the floor was never set. On EACCES the write goes through `sg <group>`
  (setuid newgrp; no password for a listed member: /etc/group wheel:x:10:armada), only when the user is a member.
- Reading min_freq returns max(user floor, the msm driver's fence-deadline boost QoS): the samples flip 220/680
  every 0.1-0.5 s with no writer. One read can therefore see "680" while the user floor is 220. The floor check and the
  "prev" to restore use the lowest of several reads (MIN_READS over READ_SPAN_S), stopping at the first low read.
- fgtest7 (console 2026-11-09: the user floor 220 became 550 for good): the floor check may stop at the first read below the
  target, but "prev" must not: a boost below the target (550 < 680) ended the reads early, "prev" was 550, and the restore
  WROTE 550 as the user floor. "prev" is now the lowest of a full set of reads and of the idle floor: while no floored game
  runs and nothing is applied, each reconcile (10 s loop) reads the floor (IDLE_READS, the GPU mostly idle, so mostly the
  real one) and keeps it for IDLE_MAX_AGE_S.
- fgtest8b (console 2026-11-09 evening: "680 -> 615 (restored)" at 15:28 and 15:51, min_freq 615 at idle in Balanced,
  gpu_min 0): a floor Vela itself had raised (the 550 left by fgtest6) is above the system's real floor; every read is
  max(that floor, boost), so the lowest read can never go below it and each restore wrote it back, or higher when the
  boost held all reads (550 -> 615). The reads cannot find the system's floor once it is wrong. The system's floor is
  armada-powerd's: the active profile's gpu_min_mhz / gpu_min ratio of the stock top step, from
  /usr/share/armada/power-profiles.conf + /etc/armada/power-profiles.conf and /var/lib/armada/powerd.state, snapped
  down to a GPU step (powerd's choose_at_most; gpu_min 0 = the lowest step) and kept <= the profile's gpu_max.
  "prev" (and the restore write) is never above that floor. Repair: while no floored game runs and nothing is
  applied, a min_freq above the profile floor that Vela wrote (a value in "wrote", or once, on the first run of
  this version for a user of the floor, a leftover of an older Vela) is set back to the profile floor (auto GPU
  level and simple_ondemand only; powerd's own value is the profile floor, so this never fights powerd).
- GPF1 (lead 2026-11-09, the owner: «Почему вела не может работать как задумано в режиме баланс от 220 до 600?»): the floor is
  OFF by default. Pinning 680 also pins the top DDR vote (16.5 GB/s) while the GPU idles waiting for the NPU
  (GPF1/research_linux_devfreq.md §4); the lp0 layer asks msm for a 2x / 50 ms boost by a fence deadline on late frames instead
  (LP_DLBOOST, lp_dlboost.h). The floor stays as an opt-in setting: data["opt_in"] (set_opt_in, the plugin's gpu_floor_opt
  call), false by default and for every older gpufloor.json; the per-game values are kept for when it is on. Off with a floor
  still applied (a run of an older Vela): the next reconcile restores it as before (the restore and repair rules above).
"""
import configparser
import glob
import json
import os
import shlex
import shutil
import subprocess
import time


def _clean_env():
    """V11 (audit 2026-11-09): the environment for a helper program (bash, sg): without the library and Python paths Decky's
    frozen Python exports to the plugin process (a system program could load Decky's bundled libraries and fail to start).
    Kept in this file: the module imports nothing else of the plugin."""
    return {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH")}


try:
    import grp
    import pwd
except ImportError:  # not Linux (tests on Windows): no sg route
    grp = pwd = None

# 680 = the clock all Vela 0.8.x benchmark figures were measured at (the Adreno's top step on the Retroid Pocket 6);
# the lowest clock that keeps the Vela chain near its pinned 4.65 ms is not measured yet.
VELA_GPU_MIN_MHZ = 680

DEVFREQ_GLOB = "/sys/class/devfreq/*.gpu"
FILE = "gpufloor.json"
MIN_READS = 4          # boost-free estimate of the user floor: lowest of this many reads ...
READ_SPAN_S = 0.6      # ... spread over this long (samples: boost windows 0.1-0.3 s)
IDLE_READS = 2         # fgtest7: the floor read on every idle reconcile (no floored game, nothing applied) ...
IDLE_SPAN_S = 0.2
IDLE_MAX_AGE_S = 600   # ... and used as "prev" for this long (the loop runs every 10 s, so normally < 20 s old)
# fgtest8b: armada-powerd's own floor (the profile's gpu_min), the ceiling of "prev"
POWER_PROFILES = ("/usr/share/armada/power-profiles.conf", "/etc/armada/power-profiles.conf")
POWERD_STATE = "/var/lib/armada/powerd.state"
DEVICE_ENV = "/usr/libexec/armada/device-env"   # powerd's ARMADA_GPU_STOCK_MAX_MHZ (only for a gpu_min ratio > 0)
FLOOR_V = 2            # data["floor_v"]: the one-time repair of an older Vela's leftover ran
WROTE_KEEP = 8         # the values Vela wrote to min_freq that are kept for the repair


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _ints(text):
    return sorted(int(x) for x in text.split() if x.isdigit())


def at_most(freqs, hz):
    """The highest step <= hz (the lowest step if none): armada-powerd's choose_at_most."""
    below = [f for f in freqs if f <= hz]
    return below[-1] if below else (freqs[0] if freqs else 0)


def at_least(freqs, hz):
    """The lowest step >= hz (the top step if none)."""
    above = [f for f in freqs if f >= hz]
    return above[0] if above else (freqs[-1] if freqs else 0)


class GpuFloor:
    def __init__(self, settings_dir, log=print, devfreq_glob=DEVFREQ_GLOB, runner=subprocess.run, sg=None, sleep=time.sleep,
                 clock=time.monotonic, profiles=POWER_PROFILES, powerd_state=POWERD_STATE, device_env=None):
        self.path = os.path.join(settings_dir, FILE)
        self.log = log
        self._glob = devfreq_glob
        self._run = runner
        self._sg = sg if sg is not None else (shutil.which("sg") or "")
        self._sleep = sleep
        self._last_err = None
        self._clock = clock
        self._idle = None      # fgtest7: (the floor read while idle, when), the base of "prev"
        self._profiles, self._powerd_state = tuple(profiles), powerd_state
        self._device_env = device_env   # () -> {"ARMADA_...": str}; None = powerd's helper, run once on need
        self._env = None
        self.data = self._load()

    # -- storage: {"games": {appid: {"on": bool, "mhz": int}}, "applied": {"hz": int, "prev": int, "appid": str} | null}

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        games = d.get("games") if isinstance(d.get("games"), dict) else {}
        games = {str(a): {"on": bool(g.get("on")), "mhz": int(g.get("mhz", VELA_GPU_MIN_MHZ))}
                 for a, g in games.items() if str(a).isdigit() and isinstance(g, dict)}
        applied = d.get("applied") if isinstance(d.get("applied"), dict) else None
        wrote = [int(v) for v in d.get("wrote", []) if isinstance(v, int) and v > 0][-WROTE_KEEP:]
        floor_v = d.get("floor_v") if isinstance(d.get("floor_v"), int) else 0
        opt_in = d.get("opt_in") is True   # GPF1: off unless the user turned it on
        return {"games": games, "applied": applied, "wrote": wrote, "floor_v": floor_v, "opt_in": opt_in}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    # -- the GPU's devfreq node

    def gpu(self):
        nodes = sorted(glob.glob(self._glob))
        return nodes[0] if nodes else None

    def freqs(self, node=None):
        node = node or self.gpu()
        return _ints(_read(os.path.join(node, "available_frequencies"))) if node else []

    def writable(self, node=None):
        node = node or self.gpu()
        if not node:
            return False
        mf = os.path.join(node, "min_freq")
        return os.access(mf, os.W_OK) or bool(self._sg_group(mf))

    def _sg_group(self, path):
        """The file's group when it is group-writable and this user is listed in it (sg needs no password then), else ''."""
        if not self._sg or grp is None:
            return ""
        try:
            st = os.stat(path)
            if not st.st_mode & 0o020:
                return ""
            g = grp.getgrgid(st.st_gid)
            me = pwd.getpwuid(os.getuid())
            return g.gr_name if (me.pw_name in g.gr_mem or me.pw_gid == st.st_gid) else ""
        except (OSError, KeyError):
            return ""

    def _min_read(self, path, n=MIN_READS, span=READ_SPAN_S, stop_below=None):
        """Lowest of n reads (the boost QoS only ever raises what is read); stops early once a read is below stop_below."""
        low = None
        for i in range(max(1, n)):
            v = _read(path)
            if v.isdigit():
                low = int(v) if low is None else min(low, int(v))
            if stop_below is not None and low is not None and low < stop_below:
                break
            if i + 1 < n:
                self._sleep(span / max(1, n - 1))
        return low or 0

    # -- armada-powerd's floor (fgtest8b)

    def _stock_max(self, freqs):
        """powerd's gpu_stock_max: ARMADA_GPU_STOCK_MAX_MHZ snapped down to a step, else the top step."""
        if self._env is None:
            try:
                if self._device_env:
                    self._env = dict(self._device_env())
                elif os.path.exists(DEVICE_ENV):
                    cmd = (f'eval "$({shlex.quote(DEVICE_ENV)})"; '
                           'for name in "${!ARMADA_@}"; do printf "%s=%s\\n" "$name" "${!name}"; done')
                    r = self._run(["bash", "-c", cmd], stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                                  env=_clean_env())  # V11
                    out = (r.stdout or b"").decode("utf-8", "replace") if r.returncode == 0 else ""
                    self._env = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
                else:
                    self._env = {}
            except (OSError, subprocess.SubprocessError, ValueError):
                self._env = {}
        stock = str(self._env.get("ARMADA_GPU_STOCK_MAX_MHZ", "")).strip()
        if stock.isdigit() and int(stock) > 0:
            return at_most(freqs, int(stock) * 1_000_000 + 999_999)
        return freqs[-1]

    def profile_floor(self, node=None):
        """The min_freq armada-powerd writes for the active profile (its resolved_gpu_auto_limits), 0 = unknown
        (no profile files, a manual GPU level, a parse error): then "prev" keeps the fgtest7 rule alone."""
        node = node or self.gpu()
        freqs = self.freqs(node) if node else []
        if not freqs:
            return 0
        profile, level = "", "auto"
        for line in _read(self._powerd_state).splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "profile":
                profile = v.strip().lower()
            elif k.strip() == "gpu_level":
                level = v.strip().lower()
        if level != "auto":
            return 0
        parser = configparser.ConfigParser()
        try:
            if not parser.read([p for p in self._profiles if os.path.exists(p)]):
                return 0
            if not profile:
                profile = parser.get("general", "default_profile", fallback="balanced").strip().lower()
            sec = f"profile.{profile}"
            if not parser.has_section(sec):
                sec = "profile.balanced"
            if not parser.has_section(sec):
                return 0

            def target(key):
                mhz = parser.get(sec, f"{key}_mhz", fallback="").strip()
                if mhz.isdigit() and int(mhz) > 0:
                    return int(mhz) * 1_000_000 + 999_999
                ratio = float(parser.get(sec, key, fallback="1.0" if key == "gpu_max" else "0").strip() or 0)
                return 0 if ratio <= 0 else int(self._stock_max(freqs) * ratio)
            lo, hi = at_most(freqs, target("gpu_min")), at_most(freqs, target("gpu_max"))
        except (configparser.Error, ValueError):
            return 0
        return min(lo, hi)

    def _note_wrote(self, hz):
        w = [v for v in self.data.setdefault("wrote", []) if v != int(hz)] + [int(hz)]
        self.data["wrote"] = w[-WROTE_KEEP:]

    def _repair(self, node, mf, idle):
        """Idle and nothing applied: a floor above powerd's that Vela wrote goes back to powerd's floor. idle = the
        idle read just made; the extra reads and the profile files only when it can be a Vela leftover."""
        first = self.data.get("floor_v", 0) < FLOOR_V
        if first:
            self.data["floor_v"] = FLOOR_V
            self._save()
        if not (self.data.get("wrote") or (first and self.data["games"])):
            return
        pf = self.profile_floor(node) if idle else 0
        if not pf or idle <= pf or _read(os.path.join(node, "governor")) != "simple_ondemand":
            return
        low = min(idle, self._min_read(mf))   # every read >= the floor: low > pf means the floor may be above pf
        if low > pf and (low in self.data.get("wrote", []) or first) and self._write(mf, pf):
            self.log(f"gpufloor: min_freq {low} -> {pf} (repair: the profile floor; {low} was left by Vela)")
            self.data["wrote"] = []
            self._save()

    # -- per game

    def known(self, appid):
        return str(appid) in self.data["games"]

    def enable(self, appid):
        """Vela turned on for the game: the floor follows (the game's own value kept, default VELA_GPU_MIN_MHZ)."""
        g = self.data["games"].setdefault(str(appid), {"on": True, "mhz": VELA_GPU_MIN_MHZ})
        g["on"] = True
        self._save()

    def disable(self, appid, running=()):
        """Vela turned off for the game: no floor for it any more (its value is kept for the next enable)."""
        g = self.data["games"].get(str(appid))
        if g and g["on"]:
            g["on"] = False
            self._save()
        self.reconcile(running)

    def set_mhz(self, appid, mhz, running=()):
        """The panel's slider: 0 = no floor for this game, else MHz (snapped to a GPU step when applied)."""
        mhz = max(0, int(mhz))
        g = self.data["games"].setdefault(str(appid), {"on": True, "mhz": VELA_GPU_MIN_MHZ})
        g["mhz"] = mhz
        self._save()
        self.reconcile(running)
        return self.status(appid)

    def set_opt_in(self, on, running=()):
        """GPF1: the floor as a setting (off by default); off restores a floor that is still applied."""
        self.data["opt_in"] = bool(on)
        self._save()
        self.log(f"gpufloor: floor setting {'on' if on else 'off'}")
        self.reconcile(running)
        return {"opt_in": self.data["opt_in"]}

    def want_hz(self, running):
        """The floor the running games ask for (the highest), 0 = none (always 0 while the setting is off)."""
        if not self.data.get("opt_in"):
            return 0
        mhz = [g["mhz"] for a, g in self.data["games"].items() if a in running and g["on"] and g["mhz"] > 0]
        return max(mhz) * 1_000_000 if mhz else 0

    # -- apply / restore

    def reconcile(self, running):
        running = {str(a) for a in running}
        node = self.gpu()
        if not node:
            return
        mf = os.path.join(node, "min_freq")
        applied = self.data["applied"]
        want = self.want_hz(running)
        if not want and not applied:   # fgtest7: idle, remember the system's own floor for the next "prev"
            v = self._min_read(mf, n=IDLE_READS, span=IDLE_SPAN_S)
            if v:
                self._idle = (v, self._clock())
            self._repair(node, mf, v)
            return
        # boost-free floor estimate (one read can show the driver's boost); when floored, stop at the first low read
        cur = self._min_read(mf, stop_below=at_least(self.freqs(node), want) if want else None) if (want or applied) else 0
        gov = _read(os.path.join(node, "governor"))
        if want and gov != "userspace":
            freqs = self.freqs(node)
            top = _read(os.path.join(node, "max_freq"))
            hz = at_least(freqs, want)
            if top.isdigit():
                hz = min(hz, int(top))   # the profile's cap wins (battery saver)
            if cur < hz:
                # fgtest7: "prev" from every read (no early stop) and the idle floor, before our write; a held floor keeps its own
                prev = applied["prev"] if applied and applied.get("hz") == cur else self._base(mf, cur)
                pf = self.profile_floor(node)
                if pf and prev > pf:   # fgtest8b: never above armada-powerd's floor (a raised floor reads as itself)
                    prev = pf
                if self._write(mf, hz):
                    self._note_wrote(hz)
                    self.data["applied"] = {"hz": hz, "prev": prev}
                    self._save()
                    self.log(f"gpufloor: min_freq {cur} -> {hz}")
            return
        if applied:
            if cur == applied.get("hz") and applied.get("prev") is not None:
                back, pf = int(applied["prev"]), self.profile_floor(node)
                if pf and back > pf:   # fgtest8b: a "prev" saved by an older Vela, or the profile changed meanwhile
                    back = pf
                if self._write(mf, back):
                    self._note_wrote(back)
                    self.log(f"gpufloor: min_freq {cur} -> {back} (restored)")
            self.data["applied"] = None
            self._save()

    def _base(self, mf, cur):
        """The floor to restore later: the lowest of cur, a full set of reads and a fresh idle read (each read is
        max(user floor, boost), so the lowest is the closest to the user floor)."""
        vals = [v for v in (cur, self._min_read(mf)) if v]
        if self._idle and self._clock() - self._idle[1] <= IDLE_MAX_AGE_S:
            vals.append(self._idle[0])
        return min(vals) if vals else cur

    def release(self):
        """Plugin unload: give the clock back."""
        self.reconcile(())

    def _write(self, path, hz):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{int(hz)}\n")
            return True
        except PermissionError as e:
            group = self._sg_group(path)
            if group:   # the plugin process has no supplementary groups (Decky); newgrp/sg gives it the file's group
                cmd = [self._sg, group, "-c", f"printf '%s\\n' {int(hz)} > {shlex.quote(path)}"]
                try:
                    r = self._run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=5, env=_clean_env())  # V11
                    if r.returncode == 0:
                        if self._last_err:
                            self.log(f"gpufloor: {path} written through sg {group}")
                        self._last_err = None
                        return True
                    err = f"sg {group}: exit {r.returncode} {(r.stderr or b'').decode('utf-8', 'replace').strip()[:200]}"
                except (OSError, subprocess.SubprocessError) as e2:
                    err = f"sg {group}: {e2}"
            else:
                err = f"{e} (no group-write for a group this user is in, or no sg)"
        except OSError as e:
            err = str(e)
        if err != self._last_err:   # once per distinct error (the 10 s loop logged the same EACCES 30 times in 3 min)
            self.log(f"gpufloor: cannot write {path}: {err}")
            self._last_err = err
        return False

    # -- the panel

    def status(self, appid, running=None):
        node = self.gpu()
        g = self.data["games"].get(str(appid)) or {"on": False, "mhz": VELA_GPU_MIN_MHZ}
        cur = _read(os.path.join(node, "min_freq")) if node else ""
        now = _read(os.path.join(node, "cur_freq")) if node else ""
        applied = self.data["applied"]
        return {
            "on": g["on"], "mhz": g["mhz"], "default_mhz": VELA_GPU_MIN_MHZ, "opt_in": bool(self.data.get("opt_in")),
            "steps_mhz": [f // 1_000_000 for f in self.freqs(node)],
            "min_mhz": int(cur) // 1_000_000 if cur.isdigit() else None,
            "cur_mhz": int(now) // 1_000_000 if now.isdigit() else None,
            "applied": bool(applied) and cur.isdigit() and int(cur) == applied.get("hz"),
            "governor": _read(os.path.join(node, "governor")) if node else None,
            "writable": self.writable(node),
        }
