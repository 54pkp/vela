// CPUW: unit test of vela_npu_poll.h (no Vulkan). Build: g++ -std=c++17 -I.. test_npu_poll.cpp -o t && ./t   (exit 0 = PASS)
#include <cstdio>
#include <cmath>
#include "vela_npu_poll.h"

static int fails = 0;
static void check(const char* name, bool ok) { std::printf("%s %s\n", ok ? "PASS" : "FAIL", name); if (!ok) ++fails; }
static bool near(double a, double b) { return std::fabs(a - b) < 1e-9; }

int main() {
  // 1. no environment: the shipped values (85 %, 8 tight, 100 us async; 70 %, 200 tight, 20 us exact)
  NpuPollCfg d = npu_poll_cfg(nullptr, nullptr);
  check("1a default async share 0.85", near(d.asyncShare, 0.85) && !d.shareSet);
  check("1b default async step 100 us", d.asyncStepNs == 100000L && !d.stepSet);
  check("1c tight polls 8 async / 200 exact", npu_tight_polls(d, true) == 8 && npu_tight_polls(d, false) == 200);
  check("1d steps 100 us async / 20 us exact", npu_step_ns(d, true) == 100000L && npu_step_ns(d, false) == 20000L);
  // the shipped e1_wake: tSubmit + e1Low * (async ? 0.85 : 0.70) - 0.25, 0 when e1Low <= 1 ms
  check("1e wake async = 100 + 30 * 0.85 - 0.25", near(npu_e1_wake(d, 100.0, 30.0, true), 100.0 + 30.0 * 0.85 - 0.25));
  check("1f wake exact = 100 + 30 * 0.70 - 0.25", near(npu_e1_wake(d, 100.0, 30.0, false), 100.0 + 30.0 * 0.70 - 0.25));
  check("1g no low yet (<= 1 ms): no sleep", npu_e1_wake(d, 100.0, 1.0, true) == 0.0 && npu_e1_wake(d, 100.0, 0.0, false) == 0.0);
  // 2. the kit's cells: 97 % and 250 / 500 us; exact untouched
  NpuPollCfg c = npu_poll_cfg("97", "500");
  check("2a share 97 % set", near(c.asyncShare, 0.97) && c.shareSet);
  check("2b step 500 us set", c.asyncStepNs == 500000L && c.stepSet);
  check("2c async wake uses 97 %", near(npu_e1_wake(c, 0.0, 30.0, true), 30.0 * 0.97 - 0.25));
  check("2d exact wake still 70 %, step 20 us, 200 tight", near(npu_e1_wake(c, 0.0, 30.0, false), 30.0 * 0.70 - 0.25) && npu_step_ns(c, false) == 20000L && npu_tight_polls(c, false) == 200);
  check("2e step 250 us", npu_poll_cfg(nullptr, "250").asyncStepNs == 250000L);
  // 3. bad values fall back to the defaults (never a 0 step or a 100 % sleep)
  const char* bad[] = {"", "abc", "97x", "0", "49", "100", "-5", "1e2"};
  bool ok = true; for (const char* b : bad) { NpuPollCfg x = npu_poll_cfg(b, nullptr); ok = ok && near(x.asyncShare, 0.85) && !x.shareSet; }
  check("3a share: empty / text / 0 / 49 / 100 / -5 / 1e2 -> 85 %", ok);
  const char* badStep[] = {"", "x", "19", "2001", "0", "-100", "250us"};
  ok = true; for (const char* b : badStep) { NpuPollCfg x = npu_poll_cfg(nullptr, b); ok = ok && x.asyncStepNs == 100000L && !x.stepSet; }
  check("3b step: empty / text / 19 / 2001 / 0 / -100 / 250us -> 100 us", ok);
  check("3c edges 50 / 99 and 20 / 2000 accepted", near(npu_poll_cfg("50", nullptr).asyncShare, 0.5) && near(npu_poll_cfg("99", nullptr).asyncShare, 0.99) &&
        npu_poll_cfg(nullptr, "20").asyncStepNs == 20000L && npu_poll_cfg(nullptr, "2000").asyncStepNs == 2000000L);
  // 4. CPUW2: the live file's keys go on top of the environment's settings; a key left out keeps the environment's value
  NpuPollCfg env = npu_poll_cfg("90", nullptr); std::string cpus;
  NpuPollCfg l = npu_poll_live(env, "e1_step_us=250\nworker_cpus=0-2\n", &cpus);
  check("4a live: step from the file, share from the environment, cpus read", l.asyncStepNs == 250000L && near(l.asyncShare, 0.90) && cpus == "0-2");
  l = npu_poll_live(env, "# variant D\r\ne1_sleep_pct=97\r\ne1_step_us=500\r\n", &cpus);
  check("4b live: CRLF and a comment line; no worker_cpus key = cpus empty (affinity untouched)", near(l.asyncShare, 0.97) && l.asyncStepNs == 500000L && cpus.empty());
  l = npu_poll_live(env, "e1_sleep_pct=10\ne1_step_us=abc\nworker_cpus=\n", &cpus);
  check("4c live: bad values keep the environment's; an empty worker_cpus means every CPU", near(l.asyncShare, 0.90) && l.asyncStepNs == 100000L && cpus == "all");
  l = npu_poll_live(env, "", &cpus);
  check("4d live: an empty file = the environment's settings again (back to the baseline variant)", near(l.asyncShare, 0.90) && l.asyncStepNs == 100000L && cpus.empty());
  check("4e exact mode is never touched by the live file", npu_step_ns(npu_poll_live(env, "e1_step_us=500\n", nullptr), false) == 20000L);
  int cl[8];
  check("5a cpu list 0-2 -> 0 1 2", npu_cpu_list("0-2", cl, 8, 64) == 3 && cl[0] == 0 && cl[2] == 2);
  check("5b cpu list 3-6 -> 4 CPUs; 0-2,7 -> 4 CPUs ending with 7", npu_cpu_list("3-6", cl, 8, 64) == 4 && npu_cpu_list("0-2,7", cl, 8, 64) == 4 && cl[3] == 7);
  check("5c all / empty / text -> 0 (every CPU); numbers past the limit are left out", npu_cpu_list("all", cl, 8, 64) == 0 && npu_cpu_list("", cl, 8, 64) == 0 &&
        npu_cpu_list("x", cl, 8, 64) == 0 && npu_cpu_list("0,99", cl, 8, 8) == 1);
  std::printf("test_npu_poll %s\n", fails ? "FAIL" : "OK");
  return fails ? 1 : 0;
}
