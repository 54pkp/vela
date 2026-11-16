// serial.ts - V06 / V07 / V16 (audit 2026-11-09): how the panel orders its own calls. Pure (no React, no Decky): tests/panel_serial_test.cjs
// runs it under Node.
//
// Before: (V06a) `run` tested `busy` from the render's closure, so two one-time fixes scheduled in one render both saw false, both read
// the same Steam launch options and both wrote them: the last write dropped the other's edit. (V07) every step of the sharpness slider
// read the options and called the backend on its own; a second step read the options from before the first step's write, and the backend
// took its NEW record out of the OLD text (the old LP_SHARP stayed as "the player's"). (V16) setInterval started a new state poll every
// 1.5 s whether or not the last one had come back.

/** One queue: each job starts after every job queued before it has ended (rejected ones included). busy(): a job runs or waits. */
export function makeSerial() {
  let tail: Promise<unknown> = Promise.resolve();
  let depth = 0;
  return {
    run<T>(fn: () => Promise<T>): Promise<T> {
      depth++;
      const p = tail.then(fn, fn);
      tail = p.then(() => { depth--; }, () => { depth--; });
      return p;
    },
    busy(): boolean { return depth > 0; },
  };
}

/** Latest wins: while `send` runs, only the newest value pushed meanwhile is kept and sent next (a held slider pushes many). */
export function makeLatest<V>(send: (v: V) => Promise<void>, onError: (e: unknown) => void = () => {}) {
  let running = false;
  let next: { v: V } | null = null;
  return function push(v: V): void {
    if (running) { next = { v }; return; }
    running = true;
    (async () => {
      let cur: { v: V } | null = { v };
      while (cur) {
        try { await send(cur.v); } catch (e) { onError(e); }
        cur = next; next = null;
      }
      running = false;
    })();
  };
}

/** A poll chain: `load` now, then again `gapMs` after the previous one RETURNED (never two at once). Returns stop(). */
export function makePoll(load: () => Promise<void>, gapMs: number,
                         timers: { set: (fn: () => void, ms: number) => unknown; clear: (t: unknown) => void } =
                           { set: (fn, ms) => setTimeout(fn, ms), clear: (t) => clearTimeout(t as ReturnType<typeof setTimeout>) }) {
  let stopped = false;
  let timer: unknown = null;
  const tick = async () => {
    try { await load(); } catch { /* the panel shows its own error; the chain goes on */ }
    if (!stopped) timer = timers.set(tick, gapMs);
  };
  tick();
  return () => { stopped = true; if (timer !== null) timers.clear(timer); };
}
