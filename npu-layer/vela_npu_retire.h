// vela_npu_retire.h - NPK7 (AUD1 A1, 2026-11-10): when a retired tensor set (the dma-buf of an earlier daemon connection, imported into the
// game's device) may be freed, and when the layer holds off new connections. No Vulkan here; tests/test_npu_retire.cpp.
//
// Before: go_down() moved the set to d->retired and nothing freed it before vkDestroyDevice (18-33 MB each); after 64 the layer stopped
// reconnecting for the rest of the session without a word.
// Why a retired set cannot be freed at once: GPU work recorded earlier may still read or write it, and a zero-copy provider keeps
// packing into its device address until it adopts the buffer of a newer connection from an ack. A freed address = a GPU fault.
// A set of generation R is free to go when ONE of these holds:
//   proof: a job of a NEWER generation had its E1 event seen by the worker, and the set was retired at least kProofMs ago.
//          E1 seen = the GPU executed that job's command buffer, so everything submitted before it is done; the job is zero-copy only when
//          its marker carried pad0 == the layer's current generation, so the provider had adopted the newer buffer before recording it;
//   age:   it was retired kAgeMs ago and no zero-copy UPSCALE marker named generation R (pad0) for kAgeMs. A provider that still packs
//          into R sends such a marker every frame (AUD1 A11), so its buffer stays; a provider that left it, or a copy-path provider,
//          lets it go.
// Hold: with kCap sets still retired the layer opens no new connection (each would import another buffer); it tries again every kHoldMs
// and says so once in the log. The rules above bring the count down, so this is a brake, not the old dead end.
#pragma once
#include <cstddef>
#include <cstdint>

struct NpuRetire {
  static constexpr double kProofMs = 1000.0;   // minimum time retired before the E1 proof counts
  static constexpr double kAgeMs = 10000.0;    // retired and unused by the provider for this long
  static constexpr size_t kCap = 8;            // retired sets at which new connections wait
  static constexpr double kHoldMs = 5000.0;    // retry period while held
};
// provenGen: generation of a job whose E1 was just seen (0 = none: only the age rule). tRet / tUse / now in ms on one clock.
inline bool npu_retired_free(uint32_t gen, double tRet, double tUse, uint32_t provenGen, double now) {
  if (provenGen && gen < provenGen && now - tRet >= NpuRetire::kProofMs) return true;
  return now - tRet >= NpuRetire::kAgeMs && now - tUse >= NpuRetire::kAgeMs;
}
inline bool npu_retire_hold(size_t retired) { return retired >= NpuRetire::kCap; }
