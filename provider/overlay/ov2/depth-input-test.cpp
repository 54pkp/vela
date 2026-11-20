#include "depth-input.hpp"
#include "../../fsr4vk/provider/input-formats.hpp"

#include <cassert>

using namespace fsr4vk;

constexpr auto d24 = VK_FORMAT_X8_D24_UNORM_PACK32;
constexpr auto d24s8 = VK_FORMAT_D24_UNORM_S8_UINT;
constexpr auto d32 = VK_FORMAT_D32_SFLOAT;
constexpr auto d32s8 = VK_FORMAT_D32_SFLOAT_S8_UINT;
constexpr auto r32 = VK_FORMAT_R32_SFLOAT;
constexpr auto d24_formats = d24_depth_only | d24_depth_stencil;

static_assert(valid_d24_input(d24, d24_depth_only, true, false));
static_assert(valid_d24_input(d24s8, d24_depth_stencil, true, true));
static_assert(!valid_d24_input(d24s8, 0, true, true));
static_assert(!valid_d24_input(d24s8, d24_depth_only, true, true));
static_assert(!valid_d24_input(d24s8, d24_formats, true, false));
static_assert(!valid_d24_input(d24s8, d24_formats, false, true));
static_assert(!valid_d24_input(d24, d24_formats, true, true));
static_assert(!valid_d24_input(d32, d24_formats, true, false));
static_assert(!valid_d24_input(d32s8, d24_formats, true, true));
static_assert(!valid_d24_input(r32, d24_formats, false, false));

static_assert(external_sample_aspect(d24) == VK_IMAGE_ASPECT_DEPTH_BIT);
static_assert(external_sample_aspect(d24s8) == VK_IMAGE_ASPECT_DEPTH_BIT);
static_assert(external_sample_aspect(d32) == VK_IMAGE_ASPECT_DEPTH_BIT);
static_assert(external_sample_aspect(d32s8) == VK_IMAGE_ASPECT_DEPTH_BIT);
static_assert(external_sample_aspect(r32) == VK_IMAGE_ASPECT_COLOR_BIT);

int main() {
    constexpr auto depth = FFX_API_RESOURCE_USAGE_DEPTHTARGET;
    constexpr auto stencil = FFX_API_RESOURCE_USAGE_STENCILTARGET;
    assert(depth_view_format(0) == r32);
    assert(depth_view_format(depth) == d32);
    assert(depth_view_format(depth | stencil) == d32s8);
}
