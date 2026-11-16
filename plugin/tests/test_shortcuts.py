"""0.8.22: a non-Steam shortcut (a GOG copy added with "Add a Non-Steam Game") is found through Steam's shortcuts.vdf,
and vela-launch finds its kit when Steam names the shortcut only in SteamGameId or STEAM_COMPAT_DATA_PATH.
Run: python -I tests/test_shortcuts.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))
import sgsr3  # noqa: E402
import vela_launch  # noqa: E402

NUL = bytes([0])


def s(key, value):
    return b"\x01" + key.encode() + NUL + value.encode() + NUL


def i32(key, value):
    return b"\x02" + key.encode() + NUL + int(value).to_bytes(4, "little", signed=True)


def entry(index, appid, name, exe, start):
    signed = appid - 2 ** 32 if appid >= 2 ** 31 else appid
    return (b"\x00" + str(index).encode() + NUL + i32("appid", signed) + s("AppName", name) + s("Exe", f'"{exe}"') +
            s("StartDir", f'"{start}"') + s("icon", "") + b"\x00tags" + NUL + b"\x08" + b"\x08")


def vdf(*entries):
    return b"\x00shortcuts" + NUL + b"".join(entries) + b"\x08\x08"


with tempfile.TemporaryDirectory() as home:
    game = os.path.join(home, "Games", "The Witcher 3 Wild Hunt GOTY")
    exe_dir = os.path.join(game, "bin", "x64_dx12")
    os.makedirs(exe_dir)
    other = os.path.join(home, "Games", "OnlyExe")
    os.makedirs(other)
    cfg = os.path.join(home, ".local", "share", "Steam", "userdata", "10001", "config")
    os.makedirs(cfg)
    apps = os.path.join(home, "Applications")
    os.makedirs(os.path.join(apps, "Xenia"))
    open(os.path.join(apps, "Xenia", "xenia_canary.exe"), "wb").close()
    open(os.path.join(apps, "Ryujinx.AppImage"), "wb").close()
    # the consoles's real shortcuts.vdf (60 entries, 2026-11-05): emulators with Start In = the home folder or /usr/bin
    data = vdf(entry(0, 3123456789, "The Witcher 3", os.path.join(exe_dir, "witcher3.exe"), exe_dir),
               entry(1, 3200000001, "Card game", "/run/media/card/Gone/game.exe", "/run/media/card/Gone"),
               entry(2, 3300000002, "Start In empty", os.path.join(other, "g.exe"), ""),
               entry(3, 3877193403, "Ryujinx", os.path.join(apps, "Ryujinx.AppImage"), home),
               entry(4, 3400000004, "Start In elsewhere", os.path.join(other, "g.exe"), apps))
    with open(os.path.join(cfg, "shortcuts.vdf"), "wb") as f:
        f.write(data)
    parsed = sgsr3.parse_binary_vdf(data)["shortcuts"]
    assert parsed["0"]["appid"] == 3123456789 - 2 ** 32 and parsed["0"]["AppName"] == "The Witcher 3", parsed["0"]
    sc = sgsr3.shortcuts(home)
    assert [x["appid"] for x in sc] == ["3123456789", "3200000001", "3300000002", "3877193403", "3400000004"], sc
    # an emulator is a Linux program: never a game folder to scan (its home-folder Start In holds Xenia's exe)
    assert sgsr3.find_install(home, "3877193403") == (None, None)
    assert sgsr3.shortcut_install(home, "3877193403") == (apps, "Ryujinx", False)
    s3 = sgsr3.Sgsr3.__new__(sgsr3.Sgsr3)
    s3.home, s3.cache = home, {}
    r = s3.scan("3877193403")
    assert r["install_dir"] == apps and r["exe_dir"] is None and r["name"] == "Ryujinx", r
    # the exe outside its Start In folder: the exe's folder
    assert sgsr3.find_install(home, "3400000004") == (other, "Start In elsewhere")
    assert sc[0]["exe"] == os.path.join(exe_dir, "witcher3.exe"), sc[0]  # quotes taken off
    # found by the unsigned and by the signed appid; its Start In folder; a missing folder is not a game folder
    assert sgsr3.find_install(home, "3123456789") == (exe_dir, "The Witcher 3")
    assert sgsr3.find_install(home, str(3123456789 - 2 ** 32)) == (exe_dir, "The Witcher 3")
    assert sgsr3.find_install(home, "3200000001") == (None, None)
    assert sgsr3.find_install(home, "3300000002") == (other, "Start In empty")  # the exe's folder
    assert sgsr3.find_install(home, "3999999999") == (None, None)
    assert sgsr3.find_install(home, "1817190") == (None, None)  # a Steam game is never looked up there
    # a cut or foreign file gives nothing, never an exception
    assert isinstance(sgsr3.parse_binary_vdf(data[:40]), dict)
    assert sgsr3.parse_binary_vdf(b"\x05junk") == {}

    # vela-launch: the appid of a shortcut from each way Steam may name it
    kits = os.path.join(home, "kits")
    os.makedirs(os.path.join(kits, "3123456789"))
    with open(os.path.join(kits, "3123456789", "launch.json"), "w") as f:
        f.write("{}")
    gid = str((3123456789 << 32) | 0x02000000)
    assert vela_launch.app_id({"SteamAppId": "0", "SteamGameId": gid}, kits) == "3123456789"
    assert vela_launch.app_id({"STEAM_COMPAT_APP_ID": "0", "STEAM_COMPAT_DATA_PATH": "/h/steamapps/compatdata/3123456789/"},
                              kits) == "3123456789"
    # a name without a kit loses to one with a kit; a Steam game reads as before
    assert vela_launch.app_id({"STEAM_COMPAT_APP_ID": "123", "SteamGameId": gid}, kits) == "3123456789"
    assert vela_launch.app_id({"STEAM_COMPAT_APP_ID": "1817190", "SteamAppId": "1817190"}, kits) == "1817190"
    assert vela_launch.app_id({"SteamAppId": "0"}, kits) is None
    assert vela_launch.app_id({}, kits) is None

    # a shortcut of a profiled game (Manor Lords, the console's SC1 run) gets that game's profile through its exe
    import gamecfg  # noqa: E402
    import profiles  # noqa: E402
    ml = "4085793122"
    assert profiles.profile(ml) is None
    profiles.link_shortcut(ml, "/g/ManorLords/Binaries/Win64/ManorLords-Win64-Shipping.exe")
    assert profiles.key(ml) == "1363080" and "VKD3D_SHADER_MODEL=6_6" in profiles.env_tokens(ml), profiles.env_tokens(ml)
    profiles.link_shortcut(ml, "/g/Other.exe")  # a rescan that finds another exe drops the link
    assert profiles.profile(ml) is None
    profiles.link_shortcut("3123456789", "witcher3.exe")  # a game without a profile: none
    assert profiles.profile("3123456789") is None
    assert profiles.profile("1363080")["name"] == "Manor Lords"  # Steam games as before
    # every exe names a real profile, and every profile has an exe
    assert set(profiles.EXES.values()) == set(profiles.PROFILES), (set(profiles.EXES.values()) ^ set(profiles.PROFILES))
    # the prefix of a shortcut's game (Ghostrunner's game_cfg is in the prefix): the main library's compatdata/<appid>
    steam_pfx = gamecfg.prefix_user("/lib/steamapps/common/Ghostrunner", "1139900", home)
    assert steam_pfx.replace(os.sep, "/").startswith("/lib/steamapps/compatdata/1139900/"), steam_pfx
    sc_pfx = gamecfg.prefix_user(os.path.join(home, "Games", "Ghostrunner"), "4000000001", home)
    assert sc_pfx == os.path.join(home, ".local", "share", "Steam", "steamapps", "compatdata", "4000000001", "pfx", "drive_c",
                                  "users", "steamuser"), sc_pfx
print("test_shortcuts OK")
