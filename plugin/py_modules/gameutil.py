"""Small helpers shared by the per-game modes: which Steam games run now, the Proton prefix of a game, the Unity
screen settings Wine keeps in the prefix's user.reg. Pure standard library (Decky's frozen Python)."""
import os
import re

import sgsr3

_RX_APPID = re.compile(rb"AppId=(\d+)")


def running_appids(proc="/proc"):
    """appids of the games Steam runs now: Steam's reaper keeps "SteamLaunch AppId=<id>" in its command line for
    the game's whole life (Proton and native games alike)."""
    out = set()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "cmdline"), "rb") as f:
                cmd = f.read(4096)
        except OSError:
            continue
        if b"SteamLaunch" in cmd:
            out.update(m.decode() for m in _RX_APPID.findall(cmd))
    return out


def run_started(appid, proc="/proc"):
    """V03 (audit 2026-11-09): when the game's current run started (epoch seconds): the oldest "SteamLaunch AppId=<id>" process,
    from its start time in /proc/<pid>/stat (field 22, clock ticks after boot) and the boot time in /proc/stat. None: the game
    does not run, or the times cannot be read. A log older than this is the previous run's."""
    key = re.compile(rb"AppId=" + str(appid).encode() + rb"(?!\d)")
    try:
        with open(os.path.join(proc, "stat"), "rb") as f:
            boot = int(re.search(rb"^btime\s+(\d+)", f.read(), re.M).group(1))
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except (OSError, AttributeError, ValueError):
        return None
    tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    best = None
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "cmdline"), "rb") as f:
                cmd = f.read(4096)
            if b"SteamLaunch" not in cmd or not key.search(cmd):
                continue
            with open(os.path.join(proc, pid, "stat"), "rb") as f:
                st = f.read()
            t = boot + int(st[st.rindex(b")") + 2:].split()[19]) / tck  # field 22; the name (field 2) may hold spaces
        except (OSError, ValueError, IndexError):
            continue
        best = t if best is None else min(best, t)
    return best


def prefix_busy(pfx, proc="/proc"):
    """A Wine process (wineserver included, it writes user.reg when it exits) still runs in this prefix."""
    if not pfx:
        return False
    key = ("WINEPREFIX=" + pfx.rstrip("/")).encode()
    key2 = ("STEAM_COMPAT_DATA_PATH=" + os.path.dirname(pfx.rstrip("/"))).encode()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "environ"), "rb") as f:
                env = f.read()
        except OSError:
            continue
        for item in env.split(b"\0"):
            if item.rstrip(b"/") in (key, key2):
                return True
    return False


def prefix_dir(home, appid):
    """The game's Proton prefix (…/steamapps/compatdata/<appid>/pfx), or None."""
    for lib in sgsr3.steam_libraries(home):
        p = os.path.join(lib, "steamapps", "compatdata", str(appid), "pfx")
        if os.path.isdir(p):
            return p
    return None


# ---- Unity's screen settings in user.reg ------------------------------------------------------------------------
# A Unity game keeps its last resolution and window mode in HKCU\Software\<company>\<product> as
# "Screenmanager Resolution Width_h…", "… Height_h…", "Screenmanager Fullscreen mode_h…" (and others). Played at a
# lower resolution (Steam's resolution override), it starts there again after the override is gone (found with
# TUNIC). Wine writes user.reg when the prefix's wineserver exits, so it is edited only while
# the game is not running.

_RX_SECTION = re.compile(r"^\[(.+?)\](?:\s+\d+)?\s*$")
_RX_SCREEN = re.compile(r'^"(Screenmanager [^"]*)"=')


def unity_screen_values(text):
    """{(section, key): line} of every Screenmanager value in a user.reg text."""
    out, section = {}, None
    for line in text.splitlines():
        m = _RX_SECTION.match(line)
        if m:
            section = m.group(1)
            continue
        m = _RX_SCREEN.match(line)
        if m and section:
            out[f"{section}\n{m.group(1)}"] = line
    return out


def unity_restore(text, saved):
    """user.reg text with the Screenmanager values exactly as in `saved` (unity_screen_values of the text before):
    changed ones get their old line back, ones that did not exist then are removed, ones that were removed come
    back under their section. Everything else is kept byte for byte."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    out, section, seen = [], None, set()
    insert_at = {}  # section -> index in out after its header (and Wine's #time line)
    for line in lines:
        m = _RX_SECTION.match(line)
        if m:
            section = m.group(1)
            out.append(line)
            insert_at[section] = len(out)
            continue
        if line.startswith("#time=") and section in insert_at and insert_at[section] == len(out):
            out.append(line)
            insert_at[section] = len(out)
            continue
        m = _RX_SCREEN.match(line)
        if m and section:
            k = f"{section}\n{m.group(1)}"
            if k in saved:
                out.append(saved[k])
                seen.add(k)
            continue  # a value the game added while upscaled: gone
        out.append(line)
    # values that were there before and are missing now: back into their section (sections never disappear in Wine)
    for k in sorted(set(saved) - seen, reverse=True):
        sec = k.split("\n", 1)[0]
        if sec in insert_at:
            i = insert_at[sec]
            out.insert(i, saved[k])
            for s2, j in insert_at.items():
                if j >= i and s2 != sec:
                    insert_at[s2] = j + 1
    return nl.join(out)
