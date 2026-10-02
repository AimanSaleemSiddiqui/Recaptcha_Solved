# Solution_Captcha — reCAPTCHA investigation handoff

Context transfer document. Everything below is verified unless explicitly marked
as unverified/predicted.

---

## 1. Environment

- Main checkout: `/Users/app/Desktop/Solution_Captcha`
- **Work is in a git worktree**: `/Users/app/Desktop/Solution_Captcha/.claude/worktrees/recaptcha-no-inject`
  on branch `worktree-recaptcha-no-inject`
- Python venv: `/Users/app/Desktop/Solution_Captcha/venv` (selenium 4.49.0,
  undetected-chromedriver 3.5.5, websocket-client, requests). System python has none of these.
- Chrome 154.0.8037.58 at `/Applications/Google Chrome.app`
- macOS (Darwin 25.5.0), zsh. `timeout` command is NOT available.
- onnxruntime was installed in a **throwaway** venv under the job tmp dir — that is
  gone now. To redo offline model checks: `python3 -m venv ortenv && ./ortenv/bin/pip install onnxruntime numpy`

### Git state
```
9a1a084 Add probe_anchor.py: measure S() re-click cadence while grid is open
bfbc759 verify_grid: add suspicious-profile mode to force reCAPTCHA challenges
828142b Add verify_grid.py: isolate and verify the hekt2 4x4 local-segmentation path
2080d85 reCAPTCHA: never replace the target page with an injected widget   <-- the actual fix
54169c1 baseline: sync uncommitted working-copy state (CDP extension load, chrome-profile)
d6078b1 Add files via upload  (origin/main, pre-existing)
```
**NOT PUSHED.** `origin` is `https://github.com/abdulrahmanalhattab/Solution_Captcha`
(not the current user's account, `AimanSiddiqui99`), and there are no credentials
in the environment. No PR exists. Commit `54169c1` carries the user's previously
uncommitted working-copy state so the real change diffs cleanly on top of it.

---

## 2. Task 1 (DONE): stop Solve.py injecting a replacement widget

### The original bug
`WaitForWidget()` executed a fallback `script` on its **first** poll iteration
whenever the expected sitekey wasn't immediately visible. That script ran
`document.documentElement.replaceChild(newBody, document.body)` — destroying the
real page and injecting a fresh `.g-recaptcha` div built from the caller's own
sitekey. Consequences:

1. Self-fulfilling check — the injected div carries `key`, so the next poll matched
   and returned True. The "widget never appeared" error was effectively unreachable.
2. Fired even on correct pages — `driver.get()` returns at `readyState=complete`,
   usually *before* `api.js` renders the widget, so a valid target got nuked in the race.
3. Tokens proved nothing — a standalone widget on a stripped body has no site
   context, so Google routinely issues a checkbox-only pass.

### What changed in `Solve.py` (commit 2080d85)
- `ReCaptcha()` has **no injection script at all** now.
- `WaitForWidget(driver, selector, key, url, script=None, timeout=60)` — `script` is
  optional; injection only happens if one is passed. Returns `(found, detected_sitekeys)`.
- New `FindSiteKeys()` returns every sitekey on the page (for diagnostics).
- `WaitForToken(..., probe=None)` — optional per-poll callback; behavior unchanged when unused.
- New `Log()` + `DEBUG` flag, and `CHALLENGE_PROBE` JS that detects a **visible**
  reCAPTCHA `bframe` iframe (>=100x100, visible through the whole ancestor chain).
- Missing/mismatched widget now returns:
  `'Target reCAPTCHA widget/sitekey not found on the original page'`
  plus `expected_sitekey`, `detected_sitekeys`, `challenge_displayed`.
- Success dict gains `challenge_displayed` — **True only if a challenge iframe was
  actually visible during the solve.** `status:True` + `challenge_displayed:False`
  means checkbox-only, NOT a solved grid.
- `HCaptcha()` still passes its script, so its injecting fallback is behaviorally unchanged.

### Preserved unchanged (explicit requirements)
Chrome 137+ `Extensions.loadUnpacked` browser-level CDP install, dedicated
`chrome-profile`, token extraction scripts, `SOLVE_TIMEOUT=180`, `finally: driver.quit()`,
and the `data` JSON string shape. The `hekt2` extension was **not** modified.

### Verification done
- `py_compile` passes; `node --check` on the extracted probe JS passes.
- AST check: no `replaceChild` / `createElement` / `api.js` anywhere in `ReCaptcha`.
- 5 logic tests against a fake driver: mismatched sitekey -> no injection; no widget ->
  no injection; expected key among several -> found; hCaptcha still injects;
  `WaitForToken` unchanged without probe. All passed.
- Live `getSolve.py` run (see section 4).

---

## 3. Task 2 (DONE): why the solver never solves image grids

The repo's `hekt2` extension is **half-functional**. `recaptcha.js` branches on
`k = (cells.length == 9) ? 3 : 4`:

### 3×3 path (9 tiles) — BROKEN, remote dependency
```js
if (3 === k) {
  const e = `https://hekt.akmal.dev/${R}-rc.ort`, n = await fetch(e, {method:"HEAD"});
  if (200 !== n.status) return console.log("error getting model", n, R), _();
```
- **`hekt.akmal.dev` is NXDOMAIN — the domain no longer exists.** Verified by DNS + curl.
- Only `mobilenetv3.ort` (feature extractor) is local; the per-label classification
  head was always remote. Those `<label>-rc.ort` files are **not in the repo**.
- The author guarded `if (200 !== n.status)`, which assumes the request completes.
  On NXDOMAIN `fetch()` **rejects**, so that guard never runs.
- **There is no `try`/`catch` anywhere in `A()` or its driver loop** (verified: 0
  occurrences of `try{`/`catch` in the 4,097-char tail). The rejection escapes `A(t)`,
  escapes `for(;;)`, and **permanently kills the bframe's solve loop**.

### 4×4 path (16 tiles) — WORKS, fully local
```js
else if (4 === k) { ... InferenceSession.create(`chrome-extension://${i}/models/recaptcha-segmentation.ort`),
                        ... mask-yolov5-seg.ort, ... nms-yolov5-det.ort
```
No network at all. Confirmed working in-browser (section 4).

### Second, independent defect: label normalization
The 4×4 gate is an exact string match: `if (j[l.indexOf(c)] !== R) continue;`
```js
let R = g.replace("Select all squares with","").replace("Select all images with","")
         .trim().replace(/^(a|an)\s+/i,"").toLowerCase().replace(" ","_");
R = M[R] || R;
```
Three compounding bugs:
1. JS `String.replace` with a **string** pattern replaces only the **first** space.
2. The alias map `M` (plural->singular) is applied **after** underscoring, so all its
   multi-word keys (`"fire hydrants"`, `"traffic lights"`, `"palm trees"`) are unreachable.
3. `M`'s **values** use spaces (`"fire hydrant"`) while the class list `j` uses
   underscores (`"fire_hydrant"`) — so they wouldn't match even if reached.

Class list `j` (15 entries): `bicycle, bridge, bus, car, chimney, crosswalk,
fire_hydrant, motorcycle, mountain_or_hill, palm_tree, parking_meter, stair, taxi,
tractor, traffic_light`

| Prompt | normalizes to | match? |
|---|---|---|
| `…squares with buses` / `cars` / `bicycles` / `crosswalks` / `taxis` / `stairs` | `bus`/`car`/… | YES |
| `…squares with fire hydrants` | `fire_hydrants` | NO — 0 tiles clicked |
| `…squares with traffic lights` | `traffic_lights` | NO |
| `…squares with palm trees` | `palm_trees` | NO |
| `…squares with parking meters` | `parking_meters` | NO |
| `…squares with mountains or hills` | `mountains_or hills` | NO |
| `…images with a fire hydrant` (singular) | `fire_hydrant` | YES (then dies on dead host) |

Single-word plurals survive because the alias lookup has no space to mangle.
**Evidence status:** the YES row for `buses` is browser-confirmed. The NO rows are
from a faithful Python port of the JS semantics — **predicted, not yet observed
in-browser** (only one 4×4 was ever served and it had a single-word label).

Net effect: **fire hydrants fail on BOTH paths, for two different reasons.**

### Why the symptom is "endless checkbox clicking"
`recaptcha.js` is injected into **both** iframes (`all_frames: true`), producing two
independent content-script instances in separate isolated worlds, each with its own
`for(;;)` loop:
```js
u() && t.recaptcha_auto_open ? await S() : l() && t.recaptcha_auto_solve && await A(t)
function u(){ return null !== document.querySelector(".recaptcha-checkbox") }  // anchor frame
function l(){ return null !== document.querySelector("#rc-imageselect") }      // bframe
function c(){ a(document.querySelector("#recaptcha-anchor")) }                 // clicks checkbox
function d(){ const t = "true" === document.querySelector(".recaptcha-checkbox")?.getAttribute("aria-checked"),
                    e = document.querySelector("#recaptcha-verify-button")?.disabled; return t || e }
function S(){ true === (await n.get({key:"recaptcha_widget_visible", tab_specific:true})).value
              && ( d() ? (O||(O=true)) : (O=false, await sleep(500), c()) ) }
```
- **anchor instance**: `u()` always true there -> always `S()`, can never reach `A()`
- **bframe instance**: `u()` false, `l()` true -> always `A()`, can never reach `S()`

`S()` has **no challenge-visibility guard**. Verified by exhaustive search:
`recaptcha_widget_visible` is read **only** in `S()`; `recaptcha_image_visible` is read
**only** in `A()`. In the anchor document `#recaptcha-verify-button` does not exist, so
`d()` collapses to `aria-checked === "true"`, which stays false while a grid is open.
So `S()` calls `c()` every iteration.

The bframe crash therefore does **not** cause the clicking — the anchor loop always
clicked whenever the checkbox was unchecked. The crash destroys the only component
that could ever make the checkbox become checked, turning a self-terminating loop into
a permanent one. Two independent loops; the terminating condition for the survivor is
reachable only via the one that died.

### Other extension facts (checked, not problems)
- `background.js` defaults are fine: `recaptcha_auto_open: true`, `recaptcha_auto_solve: true`,
  `recaptcha_click_delay_time: 300`, `recaptcha_solve_delay_time: 1000`.
- KV state lives in a plain in-memory `const a = {}` in the MV3 service worker.
  If the worker is terminated all keys vanish and `KV_GET` returns `undefined`; since both
  call sites test `true === value`, both loops would go **dormant**, not mis-fire.
  `recaptcha-visibility.js` pings every 1 s which keeps the worker alive — did not occur in testing.
- `rules.json` only forces `hl=en-US` on reCAPTCHA subframes (the label parser needs English).
  It does **not** redirect the model host.
- Manifest name is "hektCaptcha: hCaptcha Solver" v0.3.0.2 — reCAPTCHA is a secondary feature.

---

## 4. Test results (all reproducible)

### Offline model load (isolated onnxruntime venv)
All four `.ort` files load and execute:
- `recaptcha-segmentation.ort`: `images[1,3,320,320]` -> `output0[1,6300,52]`, `output1[1,32,80,80]`
- `nms-yolov5-det.ort`: `detection`+`config[3]` -> `selected_idx`
- `mask-yolov5-seg.ort`: `detection`+`mask`+`config[9]` -> `mask_filter` uint8 RGBA
- `mobilenetv3.ort`: `[batch,3,224,224]` -> `[batch,576]`

`52 = 4 box + 1 obj + 15 classes + 32 mask coeffs` — matches the 15-entry class list exactly.
`mask_filter` being RGBA matches the JS scanning `bitmap.data[n+3] > 0` (alpha) into
80x80 cells, marking a tile when >10% covered. **4×4 assets are intact and self-consistent.**

### Clean-IP baseline — the false-positive case
8/8 attempts on `google.com/recaptcha/api2/demo` returned a token with **no challenge
whatsoever**. Under the old injecting code all 8 would have looked like proof the solver
works. This is exactly what `challenge_displayed` now exposes.

### Forced-challenge run (12 fresh page loads, `verify_grid.py 12 google`)
- **11 of 12 challenges were 3×3**, 1 was 4×4.
- Attempt 7: `4x4 — 'Select all squares with buses'` -> **`max_selected: 6`**. The
  extension selected 6 tiles with zero network access. **4×4 local path confirmed working.**
- Same attempt, console captured live:
  ```
  https://hekt.akmal.dev/car-rc.ort - Failed to load resource: net::ERR_NAME_NOT_RESOLVED
  chrome-extension://…/recaptcha.js 1:1233892  Uncaught TypeError: Failed to fetch
  ```
  Offset `1233892` is exactly the 3×3 `fetch`. reCAPTCHA chained a 3×3 "cars" follow-up
  after the 4×4; the uncaught rejection killed the loop before verification completed.
- **NOT verified:** whether the 6 selected tiles were *correct* buses. The run died before
  verification could confirm. **No grid challenge has ever been solved end-to-end.**

### Anchor-click measurement (`probe_anchor.py`)
With a 3×3 grid open from t=4s to t=44s:
```
   t   grid tiles  sel  anchorClicks  ariaChecked  verifyBtnInAnchor
   4    3x3     9    0             2        false              False
  24    3x3     9    0            16        false              False
  44    3x3     9    0            29        false              False
```
27 clicks in 40 s = **one per 1.48 s**, matching `sleep(1000)` + `sleep(500)` exactly.
`sel` stayed 0 — not one tile touched. `verifyBtnInAnchor=False` confirms `d()` reduces
to the aria-checked test in the anchor frame.

### `getSolve.py` end-to-end (validates the Solve.py change)
```
[Solve] detected sitekeys: ['6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u']
[Solve] original widget found: True
[Solve] image/grid challenge iframe became visible
[Solve] token obtained: False
[Solve] image/grid challenge displayed: True
{'status': False, 'data': 'not solved within 180s', …, 'challenge_displayed': True}
```
No injection, real widget driven, grid correctly detected, honest failure.

---

## 5. Test tooling added (in the worktree)

- **`verify_grid.py`** — `venv/bin/python verify_grid.py <attempts> [2captcha|google] [burn]`
  - Default mode: N fresh page loads; reports grid size, task text, tiles selected, token,
    filtered console errors. Fresh load per attempt is **required** because the bframe loop
    dies permanently on the first 3×3.
  - `burn` mode: hammers `grecaptcha.reset()` + checkbox clicks until reCAPTCHA starts
    serving challenges, then samples grid types via the reload button. **Needed because a
    clean residential IP gets waved through with no challenge at all.**
  - `SUSPICIOUS=1` env var: throwaway profile + re-exposed `navigator.webdriver` to force
    challenges harder. Written but never actually needed.
- **`probe_anchor.py`** — installs a click counter on `#recaptcha-anchor` and samples
  aria-checked / tiles / selected once a second while a grid is open.

Note: python buffers stdout when redirected — use `python -u` or wait for process exit.

---

## 6. Conclusions

1. **The overall CAPTCHA integration is sound.** `Solve.py`, the CDP `Extensions.loadUnpacked`
   install, the dedicated profile, widget detection, cross-frame plumbing, and local ONNX
   inference all work.
2. **The 4×4 local-segmentation path works** — proven by 6 tiles selected on a live
   "buses" grid with no network.
3. **Primary blocker: the dead `hekt.akmal.dev` 3×3 classifier.** It is worse than "3×3
   doesn't work", because the uncaught rejection kills the whole bframe loop — so a chained
   3×3 follow-up destroys in-flight 4×4 work too. 11/12 served challenges were 3×3.
4. **Secondary blocker: the label-normalization bug**, which breaks all multi-word 4×4
   labels including fire hydrants (predicted by simulation, not yet browser-observed).
5. The user's original hypothesis — "if 4×4 works, the only remaining problem is the 3×3
   classifier" — holds *mostly*, but there are **two** independent defects, not one.

---

## 7. Next steps / open decisions

**Option A — resilience patch. DONE**, including the normalization fix.
Applied as 10 surgical string patches via `patch_recaptcha.py`; see sections 8 and 9.
Still not done: a `Solve.py` preflight that reports "3×3 classifier host unreachable"
immediately instead of burning the full 180 s.

**Option B — restore the models (the only real fix for 3×3). BLOCKED.**
Need the `<label>-rc.ort` files (15 classes, named e.g. `fire_hydrant-rc.ort`, `car-rc.ort`)
from an archived hektCaptcha release, a fork, or a Web Archive copy of `hekt.akmal.dev`.
They do not exist anywhere in the repo. Once obtained: drop them in `hekt2/models/` and
repoint the fetch at `chrome.runtime.getURL(...)` so nothing is remote.
**This is the decision that needs the user's input.**

**Option C — verify the 4×4 path. DONE** (see section 4).

**Also outstanding:** nothing is pushed and no PR exists. Needs either credentials for a
repo the user owns, or `gh auth login`.

---

## 8. Task 3 (DONE): control-flow handling + observable failures

Scope was explicitly *no new solving capability*. `hekt2/recaptcha.js` was patched with
8 surgical string replacements (`patch_recaptcha.py`, refuses to double-apply).

**Anchor loop.** `S()` now reads the existing `recaptcha_image_visible` KV key (set
tab-wide by `recaptcha-visibility.js` from the top frame) and returns early while a grid
is up, logging the suspend/resume transitions once each. No second visibility mechanism
was introduced. Measured on a live 3×3, timeline anchored to grid-visible:

| | t=0 | t=10 s | t=20 s | t=30 s | t=40 s | accrued |
|---|---|---|---|---|---|---|
| before | 1 | 9 | 14 | 22 | 28 | **27** |
| after | 1 | 2 | 2 | 2 | 2 | **1** |

The single residual click is the ≤1 s window before `recaptcha-visibility.js` next polls;
it is bounded by design, not a leak.

**3×3 classifier.** The `fetch` to the NXDOMAIN host is wrapped in try/catch (as is the
`InferenceSession.create` that follows), logging
`[hektCaptcha][recaptcha][classifier] 3x3 classifier UNAVAILABLE …` and aborting the
attempt. The driver `for(;;)` also gained a try/catch so no future rejection can kill the
loop silently. `Uncaught TypeError: Failed to fetch` no longer appears.
Note: the abort deliberately does **not** call `_()` (reload) — cycling to a new challenge
is the opposite of terminating the attempt, and the old `200 !== status` reload path was
never reachable anyway, since `fetch` rejected before it.

**Normalization.** At this stage instrumented only; actually fixed in section 9.

**Tests.** `test_recaptcha_logic.js` extracts the real `S()` and the real normalization
block from both the pre-patch (`git show d6078b1:hekt2/recaptcha.js`) and patched bundles
and runs them against identical stubs — 14 checks, all passing. Live: checkbox-only still
issues tokens (2/2, no errors); 4×4 still selects tiles ("buses" → 11, "stairs" → 4);
`Solve.py` on a forced challenge returns `status False`, `challenge_displayed True`.

**Latent bug noticed, not fixed:** `Solve.WaitForToken`'s `timeout=SOLVE_TIMEOUT` default
binds at def time, so mutating `Solve.SOLVE_TIMEOUT` changes only the log line, not the
actual wait.

---

## 9. Task 4 (DONE): the actual label-normalization fix

The order of operations is now: extract → lowercase → **alias while spaces are still
spaces** → underscore **every** space → exact class-list lookup.

```js
// before (one line, four compounding defects)
let R=g…toLowerCase().replace(" ","_");R=M[R]||R;

// after
const HK_Z0=g…toLowerCase(),                                   // spaces intact
      HK_HAS=t=>Object.prototype.hasOwnProperty.call(M,t),
      HK_HIT=HK_HAS(HK_Z0),
      HK_A=HK_HIT?M[HK_Z0]:HK_Z0;                              // alias first
let R=HK_A.replace(/ /g,"_");                                  // then ALL spaces
```

`hasOwnProperty` replaces the old `M[x]||x`, so a label like `constructor` can no longer
pick up an inherited `Object.prototype` member.

Reordering alone is not sufficient: the alias map had **no key** for two of the prompts
reCAPTCHA actually serves, so two entries were added (values stay space-separated like
the rest of the map; the underscoring step converts them):

```js
"mountains or hills":"mountain or hill",
"parking meters":"parking meter",
```

Nothing else changed — models, model loading, segmentation/mask/NMS, the tile-selection
algorithm, checkbox handling, 3×3 failure handling, `Solve.py` and token handling are all
untouched. Normalization only changes *which existing class* the existing detector is
asked to match.

| label | before | after |
|---|---|---|
| buses / cars / bicycles / crosswalks / taxis / stairs | already correct | unchanged |
| fire hydrants | `fire_hydrants` ✗ | `fire_hydrant` ✓ |
| traffic lights | `traffic_lights` ✗ | `traffic_light` ✓ |
| palm trees | `palm_trees` ✗ | `palm_tree` ✓ |
| parking meters | `parking_meters` ✗ | `parking_meter` ✓ |
| mountains or hills | `mountains_or hills` ✗ | `mountain_or_hill` ✓ |
| mountains | `mountain or hill` ✗ | `mountain_or_hill` ✓ |
| a mountain or hill | `mountain_or hill` ✗ | `mountain_or_hill` ✓ |

`test_recaptcha_logic.js` grew sections 7–12: the 12 required mappings as explicit
equality assertions, "every normalized value is in the existing 15-class list", and a
no-regression check that all 16 previously-matching labels are unchanged. 40 checks,
all passing.

**Live.** A real 4×4 `Select all squares with traffic lights` was observed end to end:

```
[label] grid=4x4 original="Select all squares with traffic lights" extracted="traffic lights"
        aliased="traffic light" alias_hit=true normalized="traffic_light" in_class_list=true
[match] grid=4x4 target="traffic_light" detections=5
        detected_classes=["car","traffic_light","traffic_light","car","traffic_light"]
        matched_detections=3 tiles_selected=4
```

`fire hydrants`, `palm trees`, `parking meters` and `mountains or hills` were **never
served** across 28 live attempts, so they are verified offline only. Labels actually
observed: `traffic lights` (4×4 ×2, 3×3 ×1), `buses`, `stairs`, `bicycles`, `motorcycles`,
`cars`, `taxis`, `bridges`, `crosswalks`, `a bus`.

The 4×4 summary log also gained `matched_detections`, because the earlier
"every detection was rejected by the exact-match gate" message was wrong whenever
detections *did* match but no tile cleared the 10 % mask-coverage threshold — the two
cases are now reported distinctly.
