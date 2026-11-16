// vela_npu_poll.h - CPUW (2026-11-09): how the worker waits for E1 (the GPU reached the NPU hand-off), no Vulkan here.
// PWR1 plan rows 5-6: in async mode (F_ASYNC) the worker sleeps through a share of the shortest recent submit->E1 time, then polls the
// event: 8 tight polls, then steps (Ghostrunner: 47-55 polls per frame). The share and the step are environment variables now, the
// defaults are the shipped ones (85 %, 100 us) until the CPUW kit decides. Exact mode (no F_ASYNC) is not changed (70 %, 20 us, 200 tight).
//   VELA_NPU_E1_SLEEP_PCT  async sleep share in % of the low submit->E1 (default 85; 50..99 accepted, else the default)
//   VELA_NPU_E1_STEP_US    async poll step in us after the tight polls (default 100; 20..2000 accepted, else the default)
//   VELA_NPU_LIVE_FILE     CPUW2 (KIT_TIME_RULES: several variants in one game launch): a file the worker reads again when its
//                          time changes (checked every NPU_LIVE_EVERY jobs, one stat). Lines key=value:
//                            e1_sleep_pct=97   e1_step_us=250   worker_cpus=0-2     (worker_cpus= or "all": every CPU)
//                          A key left out keeps the value from the environment. No variable = no file is ever looked at.
#pragma once
#include <cstdlib>
#include <cstring>
#include <string>

static const int NPU_LIVE_EVERY = 64;   // jobs between two looks at the live file (~1 s at 60 fps)

struct NpuPollCfg {
  double asyncShare = 0.85;      // shipped
  long asyncStepNs = 100000L;    // shipped
  int asyncTight = 8;            // not configurable (the kit measures share and step only)
  static constexpr double kExactShare = 0.70;
  static constexpr long kExactStepNs = 20000L;
  static constexpr int kExactTight = 200;
  bool shareSet = false, stepSet = false;   // a valid value came from the environment (the log line says so)
};

// parse one value: whole number in [lo, hi], else -1
inline long npu_poll_parse(const char* v, long lo, long hi) {
  if (!v || !*v) return -1;
  char* e = nullptr; long x = std::strtol(v, &e, 10);
  if (e == v || *e || x < lo || x > hi) return -1;
  return x;
}

inline NpuPollCfg npu_poll_cfg(const char* sharePct, const char* stepUs) {
  NpuPollCfg c;
  long p = npu_poll_parse(sharePct, 50, 99);
  if (p > 0) { c.asyncShare = p / 100.0; c.shareSet = true; }
  long s = npu_poll_parse(stepUs, 20, 2000);
  if (s > 0) { c.asyncStepNs = s * 1000L; c.stepSet = true; }
  return c;
}

// CPUW2: one live file's text over the environment's settings. cpus: the worker_cpus value ("" = key not in the file,
// "all" = every CPU); returns the settings to use now.
inline NpuPollCfg npu_poll_live(const NpuPollCfg& env, const char* text, std::string* cpus) {
  NpuPollCfg c = env;
  if (cpus) cpus->clear();
  for (const char* p = text ? text : ""; *p;) {
    const char* e = std::strchr(p, '\n'); size_t n = e ? size_t(e - p) : std::strlen(p);
    std::string ln(p, n); p += n + (e ? 1 : 0);
    while (!ln.empty() && (ln.back() == '\r' || ln.back() == ' ' || ln.back() == '\t')) ln.pop_back();
    size_t eq = ln.find('=');
    if (eq == std::string::npos || ln[0] == '#') continue;
    std::string k = ln.substr(0, eq), v = ln.substr(eq + 1);
    if (k == "e1_sleep_pct") { long x = npu_poll_parse(v.c_str(), 50, 99); if (x > 0) { c.asyncShare = x / 100.0; c.shareSet = true; } }
    else if (k == "e1_step_us") { long x = npu_poll_parse(v.c_str(), 20, 2000); if (x > 0) { c.asyncStepNs = x * 1000L; c.stepSet = true; } }
    else if (k == "worker_cpus" && cpus) *cpus = v.empty() ? "all" : v;
  }
  return c;
}

// "0-2", "3,5", "0-2,7" -> the CPU numbers (at most max of them, each < limit); "all" / "" -> none (the caller sets every CPU)
inline int npu_cpu_list(const char* s, int* out, int max, int limit) {
  int n = 0, a = -1; char* e = nullptr;
  if (!s || !std::strcmp(s, "all")) return 0;
  for (const char* q = s; *q;) {
    long v = std::strtol(q, &e, 10); if (e == q) break; q = e;
    if (a >= 0) { for (long c = a; c <= v && c < limit && n < max; c++) out[n++] = int(c); a = -1; }
    else if (*q == '-') a = int(v);
    else if (v >= 0 && v < limit && n < max) out[n++] = int(v);
    if (*q == '-' || *q == ',') q++;
  }
  return n;
}

// the worker's wake-up time for a job (ms, now_ms() base): sleep through `share` of the low submit->E1, minus 0.25 ms; 0 = no sleep
inline double npu_e1_wake(const NpuPollCfg& c, double tSubmit, double e1Low, bool async) {
  return e1Low > 1.0 ? tSubmit + e1Low * (async ? c.asyncShare : NpuPollCfg::kExactShare) - 0.25 : 0.0;
}
inline int npu_tight_polls(const NpuPollCfg& c, bool async) { return async ? c.asyncTight : NpuPollCfg::kExactTight; }
inline long npu_step_ns(const NpuPollCfg& c, bool async) { return async ? c.asyncStepNs : NpuPollCfg::kExactStepNs; }
