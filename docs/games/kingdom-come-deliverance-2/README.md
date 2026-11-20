# Kingdom Come: Deliverance II and Vela FSR 4

If Vela logs `Unsupported Vela FSR 4 VK: depth format VkFormat 129` and falls back to SGSR 2,
try using a 32-bit depth buffer in the game. This is a per-game setting for the Vulkan FSR 4 provider.

## Apply the setting

1. Exit the game. In the Steam library, select **Manage > Browse local files**. Use the installation
   folder that contains `system.cfg` and `Bin`.
2. Back up any existing `user.cfg` in that folder. In that file, set `r_DepthBits = 32`. If the
   setting is already present, change its value and keep the other settings. If there is no
   `user.cfg`, use the [example file](user.cfg).
3. Select **FSR 4** for the game in Vela, start the game, and select **DLSS** in its graphics
   settings. The game reads `user.cfg` at startup. For FSR 4 on the NPU, install the
   [Vela NPU component](../../../npu/README.md).

To revert, close the game and restore your previous `r_DepthBits` setting or remove the line if you
added it. If you created `user.cfg` solely for this setting, remove the file. Restart the game.

## Verified on AYN Odin 3

Tested on armadaOS with Vela 0.8.22, Proton Experimental (ARM64), and Steam build 23914554.
Before the change, the game supplied `VK_FORMAT_D24_UNORM_S8_UINT` (129), which Vela rejected
before falling back to SGSR 2. With the setting applied, the game supplied
`VK_FORMAT_D32_SFLOAT_S8_UINT` (130), Vela logged its first FSR 4 dispatch at
960 × 540 → 1920 × 1080, and the NPU layer logged `window 600 ok jobs`.

This check covered one device and game build. Performance, visual differences, and longer play
sessions were outside the test.
