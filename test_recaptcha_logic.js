// Offline tests for the hekt2/recaptcha.js control-flow patch.
//
// Rather than re-implementing the logic (which would test the re-implementation,
// not the bundle), this extracts the REAL S() and the REAL label-normalization
// block out of both the pre-patch and the patched bundle and runs them against
// identical stubs. It proves:
//   (a) the anchor loop stops clicking once an image challenge is visible,
//       while checkbox-only behaviour is untouched;
//   (b) the normalized label is byte-identical before and after, i.e. the
//       diagnostics changed nothing about tile selection;
//   (c) the diagnostics name the exact cause of each multi-word mismatch.
//
// Usage:  node test_recaptcha_logic.js
// The pre-patch bundle is taken from git (commit d6078b1 holds the pristine
// upstream copy), so no backup file needs to be kept around.
const fs = require('fs');
const { execSync } = require('child_process');

const PREPATCH_REF = 'd6078b1:hekt2/recaptcha.js';

const NEW = fs.readFileSync('hekt2/recaptcha.js', 'utf8');
const OLD = fs.existsSync('hekt2/recaptcha.js.prepatch.bak')
  ? fs.readFileSync('hekt2/recaptcha.js.prepatch.bak', 'utf8')
  : execSync(`git show ${PREPATCH_REF}`, { maxBuffer: 1 << 28 }).toString();

function slice(src, startMark, endMark) {
  const i = src.indexOf(startMark);
  if (i < 0) throw new Error('start not found: ' + startMark);
  const j = src.indexOf(endMark, i);
  if (j < 0) throw new Error('end not found: ' + endMark);
  return src.slice(i, j);
}

let failures = 0;
function check(name, cond, detail) {
  const tag = cond ? 'PASS' : 'FAIL';
  if (!cond) failures++;
  console.log(`  [${tag}] ${name}${detail ? '  ' + detail : ''}`);
}

// ------------------------------------------------------------------ S() driver
const S_OLD = slice(OLD, 'async function S(){', 'async function A(');
const S_NEW = slice(NEW, 'async function S(){', 'async function A(');

function buildS(body) {
  // body declares `async function S(){...}`; O and HK_HELD live in the closure.
  return new Function('n', 'd', 'e', 'c', 'state', `
    let O = state.O, HK_HELD = state.HK_HELD;
    ${body}
    return (async () => { await S(); state.O = O; state.HK_HELD = HK_HELD; })();
  `);
}

// Simulate N iterations of the driver loop's S() branch.
async function runS(body, plan) {
  const fn = buildS(body);
  const state = { O: false, HK_HELD: false };
  let clicks = 0;
  const logs = [];
  const realLog = console.log;
  for (let i = 0; i < plan.length; i++) {
    const step = plan[i];
    const kv = {
      async get({ key }) {
        if (key === 'recaptcha_widget_visible') return { value: step.widget };
        if (key === 'recaptcha_image_visible') return { value: step.image };
        return { value: undefined };
      },
      async set() { return { status: 'success' }; },
    };
    const utils = { sleep: async () => {}, time: () => Date.now() };
    console.log = (...a) => logs.push(a.join(' '));
    try {
      await fn(kv, () => step.checked, utils, () => { clicks++; }, state);
    } finally {
      console.log = realLog;
    }
    step.clicksAfter = clicks;
  }
  return { clicks, logs, plan };
}

// step helper: 1s driver sleep per iteration -> iteration index ~= seconds
const it = (n, o) => Array.from({ length: n }, () => ({ ...o }));

(async () => {
  console.log('\n=== 1. Anchor loop: checkbox-only flow (no image challenge) ===');
  {
    // widget visible, never checked, challenge never appears -> must keep clicking
    const plan = it(10, { widget: true, image: undefined, checked: false });
    const o = await runS(S_OLD, plan.map(x => ({ ...x })));
    const nw = await runS(S_NEW, plan.map(x => ({ ...x })));
    check('old clicks every iteration', o.clicks === 10, `clicks=${o.clicks}`);
    check('new behaves identically (no regression)', nw.clicks === o.clicks,
      `old=${o.clicks} new=${nw.clicks}`);
  }

  console.log('\n=== 2. Anchor loop: checkbox-only, image_visible explicitly false ===');
  {
    const plan = it(10, { widget: true, image: false, checked: false });
    const o = await runS(S_OLD, plan.map(x => ({ ...x })));
    const nw = await runS(S_NEW, plan.map(x => ({ ...x })));
    check('new behaves identically (no regression)', nw.clicks === o.clicks,
      `old=${o.clicks} new=${nw.clicks}`);
  }

  console.log('\n=== 3. Anchor loop: checkbox checked -> no interaction either way ===');
  {
    const plan = it(10, { widget: true, image: false, checked: true });
    const o = await runS(S_OLD, plan.map(x => ({ ...x })));
    const nw = await runS(S_NEW, plan.map(x => ({ ...x })));
    check('old: 0 clicks', o.clicks === 0, `clicks=${o.clicks}`);
    check('new: 0 clicks', nw.clicks === 0, `clicks=${nw.clicks}`);
  }

  console.log('\n=== 4. Anchor loop: grid opens at t=4s, stays open to t=44s ===');
  {
    // 45 iterations ~= 45s. Challenge visible from iteration 4 onward.
    // In the anchor document #recaptcha-verify-button does not exist, so
    // d() stays false the whole time -> this is the runaway-click case.
    const mk = () => Array.from({ length: 45 }, (_, i) => ({
      widget: true, image: i >= 4, checked: false,
    }));
    const o = await runS(S_OLD, mk());
    const nw = await runS(S_NEW, mk());
    const at = (r, i) => r.plan[i].clicksAfter;
    console.log(`    old click count  t=4s:${at(o,4)}  t=14s:${at(o,14)}  t=24s:${at(o,24)}  t=34s:${at(o,34)}  t=44s:${at(o,44)}`);
    console.log(`    new click count  t=4s:${at(nw,4)}  t=14s:${at(nw,14)}  t=24s:${at(nw,24)}  t=34s:${at(nw,34)}  t=44s:${at(nw,44)}`);
    check('old keeps climbing while grid is open', at(o, 44) > at(o, 4), `${at(o,4)} -> ${at(o,44)}`);
    check('new stops climbing once grid is visible', at(nw, 44) === at(nw, 4), `${at(nw,4)} -> ${at(nw,44)}`);
    check('new preserved the opening clicks (t<4s)', at(nw, 3) === 4, `clicks before grid=${at(nw,3)}`);
    check('new logged the suspend once', nw.logs.filter(l => l.includes('suspending')).length === 1,
      JSON.stringify(nw.logs.filter(l => l.includes('suspending'))));
  }

  console.log('\n=== 5. Anchor loop: grid closes again -> interaction resumes ===');
  {
    const mk = () => Array.from({ length: 20 }, (_, i) => ({
      widget: true, image: i >= 4 && i < 12, checked: false,
    }));
    const nw = await runS(S_NEW, mk());
    const at = i => nw.plan[i].clicksAfter;
    check('frozen while visible', at(11) === at(4), `${at(4)} -> ${at(11)}`);
    check('resumes after close', at(19) > at(11), `${at(11)} -> ${at(19)}`);
    check('logged re-enable', nw.logs.some(l => l.includes('re-enabled')));
  }

  console.log('\n=== 6. Anchor loop: widget not visible -> never interacts ===');
  {
    const plan = it(5, { widget: false, image: true, checked: false });
    const nw = await runS(S_NEW, plan.map(x => ({ ...x })));
    check('0 clicks', nw.clicks === 0, `clicks=${nw.clicks}`);
  }

  // -------------------------------------------------------- label normalization
  // Both the pre-patch and the patched normalization block are extracted along
  // with the alias map M and class list j that each version ships, so the two
  // are compared exactly as they run in the browser.
  const NORM_OLD = slice(OLD, 'const M={bicycles:', 'let R=g.replace')
    + slice(OLD, 'let R=g.replace', 'const L=[];');
  const NORM_NEW = slice(NEW, 'const M={bicycles:', 'const HK_Z0=')
    + slice(NEW, 'const HK_Z0=', 'const L=[];');

  const oldNorm = new Function('g', 'k', NORM_OLD + '\nreturn {R, j, M};');
  const newNorm = new Function('g', 'k', NORM_NEW + '\nreturn {R, j, M};');

  // label -> required class-list value. The first block is the contract from the
  // task; the rest is extra coverage so single-word and singular forms are
  // pinned down too.
  const REQUIRED = {
    'buses': 'bus',
    'cars': 'car',
    'bicycles': 'bicycle',
    'crosswalks': 'crosswalk',
    'taxis': 'taxi',
    'stairs': 'stair',
    'fire hydrants': 'fire_hydrant',
    'traffic lights': 'traffic_light',
    'palm trees': 'palm_tree',
    'parking meters': 'parking_meter',
    'mountains or hills': 'mountain_or_hill',
    'vehicles': 'car',
  };
  const EXTRA = {
    'bridges': 'bridge',
    'motorcycles': 'motorcycle',
    'chimneys': 'chimney',
    'tractors': 'tractor',
    'mountains': 'mountain_or_hill',
    // singular forms, as served on 3x3 ("Select all images with a fire hydrant")
    'a fire hydrant': 'fire_hydrant',
    'a bus': 'bus',
    'a traffic light': 'traffic_light',
    'a palm tree': 'palm_tree',
    'a parking meter': 'parking_meter',
    'a mountain or hill': 'mountain_or_hill',
  };

  // 4x4 prompts say "squares", 3x3 prompts say "images".
  const CASES = [
    ...Object.entries(REQUIRED).map(([label, want]) =>
      ({ label, want, k: 4, g: `Select all squares with ${label}`, required: true })),
    ...Object.entries(EXTRA).map(([label, want]) =>
      ({ label, want, k: 3, g: `Select all images with ${label}`, required: false })),
  ];

  const rows = [];
  const diagLines = [];
  for (const c of CASES) {
    const before = oldNorm(c.g, c.k);
    const realLog = console.log;
    console.log = (...x) => diagLines.push(x.join(' '));
    let after;
    try { after = newNorm(c.g, c.k); } finally { console.log = realLog; }
    rows.push({
      ...c,
      oldR: before.R, newR: after.R,
      oldOk: before.j.includes(before.R),
      newOk: after.j.includes(after.R),
      classList: after.j,
    });
  }

  console.log('\n=== 7. Label normalization: before vs after ===');
  console.log('    label                  before              after               want                ok');
  for (const r of rows) {
    const ok = r.newR === r.want ? 'YES' : 'NO';
    console.log(`    ${r.label.padEnd(22)} ${String(r.oldR).padEnd(19)} `
      + `${String(r.newR).padEnd(19)} ${r.want.padEnd(19)} ${ok}`);
  }

  console.log('\n=== 8. Required mappings (the task contract) ===');
  const required = rows.filter(r => r.required);
  for (const r of required) {
    check(`${r.label.padEnd(20)} == ${r.want}`, r.newR === r.want, `got ${r.newR}`);
  }

  console.log('\n=== 9. Every normalized value is in the existing 15-class list ===');
  check('class list is still the original 15 entries',
    rows[0].classList.length === 15
    && rows[0].classList.join(',') === 'bicycle,bridge,bus,car,chimney,crosswalk,fire_hydrant,'
      + 'motorcycle,mountain_or_hill,palm_tree,parking_meter,stair,taxi,tractor,traffic_light',
    JSON.stringify(rows[0].classList));
  const notInList = rows.filter(r => !r.newOk).map(r => `${r.label}->${r.newR}`);
  check(`all ${rows.length} normalized values present in the class list`,
    notInList.length === 0, JSON.stringify(notInList));

  console.log('\n=== 10. No single-word regression ===');
  // Everything that already worked before must still produce the same value.
  const wasWorking = rows.filter(r => r.oldOk);
  const changed = wasWorking.filter(r => r.newR !== r.oldR)
    .map(r => `${r.label}: ${r.oldR} -> ${r.newR}`);
  check(`all ${wasWorking.length} previously-matching labels unchanged`,
    changed.length === 0, JSON.stringify(changed));

  console.log('\n=== 11. The multi-word labels that used to miss now hit ===');
  const FIXED = ['fire hydrants', 'traffic lights', 'palm trees', 'parking meters',
    'mountains or hills'];
  for (const label of FIXED) {
    const r = rows.find(x => x.label === label);
    check(`${label.padEnd(20)} was broken, now ${r.want}`,
      !r.oldOk && r.newR === r.want, `before=${r.oldR} after=${r.newR}`);
  }

  console.log('\n=== 12. Diagnostics: alias_hit / in_class_list for the fixed labels ===');
  check('one diagnostic line per challenge', diagLines.length === CASES.length,
    `lines=${diagLines.length}`);
  for (const label of FIXED) {
    const line = diagLines.find(l => l.includes(`extracted="${label}"`));
    check(`${label.padEnd(20)} reports alias_hit=true in_class_list=true`,
      !!line && line.includes('alias_hit=true') && line.includes('in_class_list=true')
      && line.includes(`normalized="${REQUIRED[label]}"`),
      line ? line.slice(line.indexOf('original=')) : 'no diagnostic line');
  }

  console.log('\n    sample diagnostic lines:');
  for (const label of FIXED) {
    const line = diagLines.find(l => l.includes(`extracted="${label}"`));
    if (line) console.log('      ' + line.slice(line.indexOf('original=')));
  }

  // ------------------------------------------------- y() lifecycle (fixes 1/2/3)
  // Extracts the REAL m(), the module-level signature `b`, and the REAL y() and
  // drives them against a stubbed DOM, so these exercise shipped code rather
  // than a re-implementation.
  const Y_SRC = slice(NEW, 'async function m(t)', 'function v()');

  function buildY() {
    const fn = new Function('document', 'e', 'g',
      Y_SRC + '\nreturn {y, getB:()=>b, setB:v=>{b=v}};');
    return fn;
  }

  // cells: n tds, each holding an <img>. `width` 0 models an undecoded image.
  function makeDoc(spec) {
    const cells = spec.srcs.map((src, i) => ({
      querySelector: sel => (sel === 'img' && src !== null
        ? { get naturalWidth() { return spec.width(i); }, src }
        : null),
    }));
    cells.length = spec.srcs.length;
    return {
      querySelector: sel => (sel === '.rc-imageselect-instructions'
        ? (spec.instructions === null ? null : { innerText: spec.instructions })
        : null),
      querySelectorAll: sel => (sel === 'table tr td' ? cells : []),
    };
  }

  const utils = { time: () => Date.now(), sleep: () => Promise.resolve() };
  const gStub = t => t?.src?.trim();
  const TASK3 = 'Select all squares with\nbuses\nIf there are none, click skip';

  function capture() {
    const lines = [];
    const real = { log: console.log, error: console.error };
    console.log = (...a) => lines.push(a.join(' '));
    console.error = (...a) => lines.push(a.join(' '));
    return { lines, restore: () => { console.log = real.log; console.error = real.error; } };
  }

  console.log('\n=== 13. FIX 1: unchanged signature resolves null instead of hanging ===');
  {
    const doc = makeDoc({ instructions: TASK3, srcs: Array(16).fill('BG1'), width: () => 400 });
    const api = buildY()(doc, utils, gStub);
    api.setB(JSON.stringify(['BG1', Array(16).fill(null)]));  // pretend already seen
    const cap = capture();
    const t0 = Date.now();
    let out;
    try { out = await api.y(10, 300); } finally { cap.restore(); }
    const dt = Date.now() - t0;
    check('resolved (did not hang)', out === null, `returned ${JSON.stringify(out)}`);
    check('resolved at roughly the deadline', dt >= 250 && dt < 2500, `${dt}ms`);
    check('reported the identical-signature reason',
      cap.lines.some(l => l.includes('signature identical')),
      JSON.stringify(cap.lines.slice(-1)));
  }

  console.log('\n=== 14. FIX 2: a throwing m() no longer wedges the poll guard ===');
  {
    // Single-line instructions -> m() takes `e.join()` with e===null and throws.
    const doc = makeDoc({ instructions: 'OneLineOnly', srcs: Array(16).fill('BG2'), width: () => 400 });
    const api = buildY()(doc, utils, gStub);
    const cap = capture();
    let out, threw = null;
    try { out = await api.y(10, 300); } catch (err) { threw = err; } finally { cap.restore(); }
    check('m() genuinely throws on single-line instructions',
      cap.lines.some(l => l.includes('poll threw')), JSON.stringify(cap.lines.slice(0, 1)));
    check('y() still resolves null (guard was released in finally)',
      threw === null && out === null, `threw=${threw} out=${JSON.stringify(out)}`);
    // If `n` had stuck true, the deadline branch could never be reached at all.
    check('deadline branch was reachable after the throw',
      cap.lines.some(l => l.includes('no new challenge within')));
  }

  console.log('\n=== 15. FIX 3: all-null sample is discarded, not resolved ===');
  {
    let loaded = false;
    const doc = makeDoc({
      instructions: TASK3,
      srcs: Array(16).fill('BG3'),
      width: () => (loaded ? 400 : 0),   // 0 = not yet decoded
    });
    const api = buildY()(doc, utils, gStub);
    const cap = capture();
    const pending = api.y(10, 4000);
    let settled = false;
    pending.then(() => { settled = true; });
    await new Promise(r => setTimeout(r, 200));           // ~20 polls
    const earlyB = api.getB();
    cap.restore();
    check('did NOT resolve while every image was undecoded', settled === false);
    check('malformed sample never became the stored signature',
      earlyB === null, `b=${JSON.stringify(earlyB)}`);
    loaded = true;                                        // images decode
    const out = await pending;
    check('resolves normally once the images decode',
      out && out.background_url === 'BG3' && out.cells.length === 16,
      JSON.stringify(out && { bg: out.background_url, cells: out.cells.length }));

    // A grid that never decodes must time out naming the malformed sample,
    // rather than resolving with an empty image list.
    const stuck = makeDoc({ instructions: TASK3, srcs: Array(16).fill('BG5'), width: () => 0 });
    const api2 = buildY()(stuck, utils, gStub);
    const cap2 = capture();
    let out2;
    try { out2 = await api2.y(10, 250); } finally { cap2.restore(); }
    check('permanently undecoded grid times out as null', out2 === null,
      JSON.stringify(out2));
    check('timeout names the malformed-sample reason',
      cap2.lines.some(l => l.includes('malformed all-null sample')),
      JSON.stringify(cap2.lines.slice(-1)));
    check('stored signature still untouched', api2.getB() === null,
      `b=${JSON.stringify(api2.getB())}`);
  }

  console.log('\n=== 16. No regression: a genuinely new challenge still resolves at once ===');
  {
    const doc = makeDoc({ instructions: TASK3, srcs: Array(16).fill('BG4'), width: () => 400 });
    const api = buildY()(doc, utils, gStub);
    const t0 = Date.now();
    const out = await api.y(10, 3000);
    const dt = Date.now() - t0;
    check('resolved promptly', out !== null && dt < 400, `${dt}ms`);
    check('payload shape unchanged',
      out.task === 'Select all squares with buses' && out.is_hard === true
      && out.cells.length === 16 && out.background_url === 'BG4'
      && out.urls.length === 16 && out.urls.every(u => u === null),
      JSON.stringify({ task: out.task, is_hard: out.is_hard, bg: out.background_url }));
    check('signature was stored', api.getB() === JSON.stringify(['BG4', Array(16).fill(null)]));
  }

  console.log('\n=== 17. No regression: 9-tile url-based grid still accepted by FIX 3 ===');
  {
    // c===true (tile urls present) with l===null must NOT be treated as malformed.
    const srcs = Array.from({ length: 9 }, (_, i) => `T${i}`);
    const doc = makeDoc({ instructions: 'Select all images with\nbuses\nClick verify once there are none left', srcs, width: () => 100 });
    const api = buildY()(doc, utils, gStub);
    const out = await api.y(10, 3000);
    check('resolved', out !== null);
    check('background_url null but urls populated (unchanged semantics)',
      out && out.background_url === null && out.urls.length === 9
      && out.urls.every((u, i) => u === `T${i}`),
      JSON.stringify(out && { bg: out.background_url, urls: out.urls }));
  }

  console.log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : failures + ' CHECK(S) FAILED'}`);
  process.exit(failures === 0 ? 0 : 1);
})();
