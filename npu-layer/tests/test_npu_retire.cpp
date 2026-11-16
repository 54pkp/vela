// NPK7 A1: unit test of vela_npu_retire.h (no Vulkan). Build: g++ -std=c++17 -I.. test_npu_retire.cpp -o t && ./t   (exit 0 = PASS)
// The second part replays the audit's two pile-up scenarios against the rules with a small model of the layer's bookkeeping.
#include <cstdio>
#include <vector>
#include <algorithm>
#include "vela_npu_retire.h"

static int fails = 0;
static void check(const char* name, bool ok) { std::printf("%s %s\n", ok ? "PASS" : "FAIL", name); if (!ok) ++fails; }

struct R { uint32_t gen; double tRet, tUse; };
struct Model {   // what the layer keeps: current generation, retired sets, the hold
  uint32_t gen = 0; bool up = false; std::vector<R> retired; size_t peak = 0; long freed = 0, refused = 0;
  void sweep(uint32_t proven, double now) { for (size_t i = 0; i < retired.size();) { if (npu_retired_free(retired[i].gen, retired[i].tRet, retired[i].tUse, proven, now)) { retired.erase(retired.begin() + i); freed++; } else i++; } }
  bool connect(double now) { sweep(0, now); if (npu_retire_hold(retired.size())) { refused++; return false; } gen++; up = true; return true; }
  void down(double now) { if (!up) return; retired.push_back({gen, now, now}); up = false; peak = std::max(peak, retired.size()); }
  void job_e1(double now) { sweep(gen, now); }                                   // a job of the current generation reached E1
  void marker(uint32_t pad0, double now) { for (R& r : retired) if (r.gen == pad0) r.tUse = now; }   // zero-copy UPSCALE marker
};

int main() {
  // ---- the rules
  check("fresh retired set stays (no proof, not aged)", !npu_retired_free(3, 1000, 1000, 0, 1500));
  check("proof by a newer job, but retired < 1 s ago: stays", !npu_retired_free(3, 1000, 1000, 4, 1500));
  check("proof by a newer job after 1 s: freed", npu_retired_free(3, 1000, 1000, 4, 2000));
  check("a job of the SAME generation is no proof", !npu_retired_free(3, 1000, 1000, 3, 9000));
  check("a job of an OLDER generation is no proof", !npu_retired_free(3, 1000, 1000, 2, 9000));
  check("age: 10 s retired and unused: freed", npu_retired_free(3, 1000, 1000, 0, 11000));
  check("age: retired 60 s ago but the provider named it 2 s ago: stays", !npu_retired_free(3, 1000, 59000, 0, 61000));
  check("age: the provider stopped naming it 10 s ago: freed", npu_retired_free(3, 1000, 59000, 0, 69000));
  check("proof beats a recent provider use (the provider adopted the newer buffer before that job)", npu_retired_free(3, 1000, 1990, 4, 2000));
  check("hold below the cap: no", !npu_retire_hold(NpuRetire::kCap - 1));
  check("hold at the cap: yes", npu_retire_hold(NpuRetire::kCap));

  // ---- scenario a (AUD1 A1): graph nf4_k1h unusable, nf4_exact works; the provider probes k1h every 300 frames (5 s at 60 fps).
  // Each cycle: the working set is retired by the graph switch, k1h fails to connect, exact comes up again and runs jobs.
  { Model m; double t = 0; m.connect(t);
    for (int cyc = 0; cyc < 200; cyc++) {                      // 200 cycles = 1000 s; the old code died after 64
      for (int f = 0; f < 300; f++) { t += 16.7; m.job_e1(t); }
      m.down(t);                                               // PROBE k1h: graph switch
      if (!m.connect(t)) break;                                // PROBE exact (k1h refused before any set was imported)
    }
    std::printf("  scenario a: 200 graph-switch cycles: peak %zu retired, %ld freed, %ld connects refused, %zu left\n", m.peak, m.freed, m.refused, m.retired.size());
    check("scenario a: never more than 2 retired sets, no connect refused", m.peak <= 2 && m.refused == 0 && m.up); }

  // ---- scenario b: every connection imports a buffer, its first job fails (E1 seen, then the daemon reports an error), reconnect 150 ms later.
  // The provider adopts each new buffer from an ack and names it in its next marker; no job ever succeeds.
  { Model m; double t = 0; long connects = 0;
    for (int i = 0; i < 4000; i++) {                           // 4000 x 150 ms = 600 s
      if (m.connect(t)) { connects++; m.marker(m.gen, t); m.job_e1(t); m.down(t); }
      t += 150; }
    std::printf("  scenario b: 600 s of failing first jobs: %ld connects, peak %zu retired, %ld freed, %ld refused\n", connects, m.peak, m.freed, m.refused);
    check("scenario b: retired sets stay at or below the cap for 10 minutes and connects go on", m.peak <= NpuRetire::kCap && connects > 300); }

  // ---- scenario c (AUD1 A11): the daemon is gone, the provider keeps packing into the last buffer every frame: that one set must stay.
  { Model m; double t = 0; m.connect(t); m.job_e1(t); const uint32_t g = m.gen; m.down(t);
    for (int f = 0; f < 6000; f++) { t += 16.7; m.marker(g, t); m.sweep(0, t); }   // 100 s
    check("scenario c: the buffer the provider still writes is kept", m.retired.size() == 1 && m.freed == 0);
    for (int f = 0; f < 700; f++) { t += 16.7; m.sweep(0, t); }                    // the provider stopped (re-probe): 11.7 s later
    check("scenario c: freed 10 s after the provider left it", m.retired.empty()); }

  std::printf("test_npu_retire: %d failed\n", fails); return fails ? 1 : 0;
}
