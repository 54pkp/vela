#pragma once
#include <vulkan/vulkan.h>
#include <cstdint>

namespace fsr4vk {
// Bits in the Vela native-depth capability query.
inline constexpr std::uint32_t d24_depth_only = 1u << 0;
inline constexpr std::uint32_t d24_depth_stencil = 1u << 1;

constexpr std::uint32_t d24_capability(VkFormat format) {
    switch (format) {
    case VK_FORMAT_X8_D24_UNORM_PACK32: return d24_depth_only;
    case VK_FORMAT_D24_UNORM_S8_UINT: return d24_depth_stencil;
    default: return 0;
    }
}

constexpr bool valid_d24_input(VkFormat format, std::uint32_t capabilities, bool depth, bool stencil) {
    const auto required = d24_capability(format);
    return depth && (capabilities & required) != 0 &&
           stencil == (required == d24_depth_stencil);
}

constexpr VkImageAspectFlags external_sample_aspect(VkFormat format) {
    switch (format) {
    case VK_FORMAT_X8_D24_UNORM_PACK32:
    case VK_FORMAT_D24_UNORM_S8_UINT:
    case VK_FORMAT_D32_SFLOAT:
    case VK_FORMAT_D32_SFLOAT_S8_UINT:
        return VK_IMAGE_ASPECT_DEPTH_BIT;
    default:
        return VK_IMAGE_ASPECT_COLOR_BIT;
    }
}
} // namespace fsr4vk
