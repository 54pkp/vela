// V06 / V07 / V16: the panel's call ordering (src/serial.ts, compiled to CommonJS by tests/test_v06_v07_v16_panel.py).
// usage: node panel_serial_test.cjs <compiled serial.cjs>      prints PASS / FAIL lines, exit 1 on a failure
const { makeSerial, makeLatest, makePoll } = require(process.argv[2]);
let fails = 0;
const check = (name, ok) => { console.log((ok ? "PASS " : "FAIL ") + name); if (!ok) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// a fake Steam: launch options one string; reading and writing take time, as the real client calls do
function steam(initial) {
  let opts = initial;
  return { read: async () => { await sleep(5); return opts; }, write: async (o) => { await sleep(5); opts = o; }, now: () => opts };
}
// a one-time fix as the panel does it: read the options, ask the backend (it adds / removes ITS token), write the answer
const fix = (st, edit) => async () => { const launch = await st.read(); await sleep(10); await st.write(edit(launch)); };

(async () => {
  // ---- V06a: two fixes scheduled in the same render (llfg_off and launch_fix)
  {
    // the old `run`: `if (busy) return` with busy from the render's closure -> both run at once
    const st = steam("OPTI_SGSRFG=1 %command%");
    const busy = false;                                   // what both closures saw
    const oldRun = async (fn) => { if (busy) return; await fn(); };
    await Promise.all([oldRun(fix(st, (o) => o.replace("OPTI_SGSRFG=1 ", ""))), oldRun(fix(st, (o) => "VELA_NPU=1 " + o))]);
    const lost = st.now() !== "VELA_NPU=1 %command%";
    check(`1 the old pattern loses one fix's edit (result: ${st.now()})`, lost);
    const st2 = steam("OPTI_SGSRFG=1 %command%");
    const q = makeSerial();
    await Promise.all([q.run(fix(st2, (o) => o.replace("OPTI_SGSRFG=1 ", ""))), q.run(fix(st2, (o) => "VELA_NPU=1 " + o))]);
    check(`2 through the queue both edits land (result: ${st2.now()})`, st2.now() === "VELA_NPU=1 %command%");
  }
  // ---- the queue itself
  {
    const q = makeSerial(); const log = [];
    const job = (n, ms, fail) => async () => { log.push("start " + n); await sleep(ms); log.push("end " + n); if (fail) throw new Error("x" + n); return n; };
    check("3 idle queue: not busy", q.busy() === false);
    const a = q.run(job(1, 20)), b = q.run(job(2, 5, true)), c = q.run(job(3, 1));
    check("4 busy while jobs run or wait", q.busy() === true);
    const r = await Promise.allSettled([a, b, c]);
    check("5 jobs never overlap and keep their order", log.join(",") === "start 1,end 1,start 2,end 2,start 3,end 3");
    check("6 a job that fails does not stop the queue; each caller gets its own result", r[0].value === 1 && r[1].status === "rejected" && r[2].value === 3);
    check("7 not busy when all ended", q.busy() === false);
  }
  // ---- V07: the sharpness slider held down (values 0.55 -> 0.60 -> ... -> 0.80 pushed every 3 ms; a send takes 25 ms)
  {
    const st = steam("LP_SHARP=0.50 %command%"); const sent = []; let live = 0, maxLive = 0;
    const send = async (v) => {
      live++; maxLive = Math.max(maxLive, live);
      const launch = await st.read(); await sleep(15);
      await st.write(launch.replace(/LP_SHARP=[\d.]+/, "LP_SHARP=" + v.toFixed(2)));   // the backend: its old token out, the new one in
      sent.push(v); live--;
    };
    const push = makeLatest(send);
    for (const v of [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]) { push(v); await sleep(3); }
    await sleep(120);
    check(`8 never two sends at once (max in flight ${maxLive})`, maxLive === 1);
    check(`9 the last value pushed is the last value sent, values in between are skipped (sent ${sent.join(" ")})`, sent[sent.length - 1] === 0.80 && sent.length < 6 && sent[0] === 0.55);
    check(`10 Steam's options end with exactly one LP_SHARP, the newest (${st.now()})`, st.now() === "LP_SHARP=0.80 %command%");
    // an error in one send does not stop the next value
    const errs = []; const got = [];
    const p2 = makeLatest(async (v) => { await sleep(5); if (v === 1) throw new Error("backend"); got.push(v); }, (e) => errs.push(e.message));
    p2(1); p2(2); await sleep(40);
    check("11 a failed send is reported and the next value still goes out", errs.join() === "backend" && got.join() === "2");
  }
  // ---- V16: the state poll; a poll takes 40 ms, the gap is 10 ms
  {
    let live = 0, maxLive = 0, n = 0;
    const load = async () => { live++; maxLive = Math.max(maxLive, live); n++; await sleep(40); live--; if (n === 2) throw new Error("backend error"); };
    const stop = makePoll(load, 10);
    await sleep(230);
    stop();
    const seen = n;
    await sleep(120);
    check(`12 polls never overlap (max at once ${maxLive}; setInterval(10 ms) with a 40 ms poll overlaps)`, maxLive === 1);
    check(`13 the chain goes on after a poll that failed (${seen} polls in 230 ms)`, seen >= 3 && seen <= 5);
    check("14 stop() ends it: no poll afterwards", n === seen || n === seen + 0);
    // the old pattern for comparison
    let l2 = 0, m2 = 0; const t = setInterval(async () => { l2++; m2 = Math.max(m2, l2); await sleep(40); l2--; }, 10);
    await sleep(120); clearInterval(t); await sleep(60);
    check(`15 the old setInterval pattern does overlap (max at once ${m2})`, m2 > 1);
  }
  console.log("panel_serial_test " + (fails ? "FAIL " + fails : "OK"));
  process.exit(fails ? 1 : 0);
})();
