# Solution_Captcha

An **educational, work-in-progress** experiment in automating Google reCAPTCHA v2
("I'm not a robot") with Selenium plus a locally-run, AI-based browser extension.
It exists for learning how reCAPTCHA's checkbox/image-challenge flow works and how
far a purely local solver can get — **on your own demo/test pages only**.

> ⚠️ **Status: partial / research prototype.** This is not a dependable captcha
> solver. Read [What to expect](#what-to-expect) before trying it — some challenge
> types cannot be solved at all with what ships in this repo.

## What it does

- Launches Chrome with a dedicated profile and installs a local ONNX-based solver
  extension (`hekt2/`) over the Chrome DevTools Protocol.
- Navigates to a page you specify, finds that page's own reCAPTCHA widget, and
  waits for the extension to work the challenge.
- Returns a result dict: the `g-recaptcha-response` token on success, or an honest
  failure with a reason. `challenge_displayed` tells you whether an image grid was
  actually shown (vs. a checkbox-only pass).
- All inference runs **locally** — no third-party captcha-solving service is called.

## What to expect

This is the part most "captcha solver" repos leave out. Be realistic:

| Challenge type | Status |
| --- | --- |
| **Checkbox-only pass** (no image challenge) | Works when the browser/session reputation earns it. |
| **4×4 image grids** ("select all squares with…") | Partially works. The local segmentation model often **under-detects** — it finds one instance of the target where the grid expects several — so submissions are frequently incomplete and get a "try again". Multi-challenge chains and the Next/Skip/Verify flow are handled. |
| **3×3 image grids** ("select all images with…") | **Not supported.** The per-label classifier was fetched from a remote host (`hekt.akmal.dev`) that no longer exists, and those model files were never part of this repo. The script detects this, logs `3x3 classifier UNAVAILABLE`, and reloads for a fresh challenge instead of hanging. Google serves 3×3 the majority of the time, so expect many reloads. |

In short: it can pass a checkbox and sometimes complete a 4×4, but **it will not
reliably solve arbitrary challenges**, and it cannot solve 3×3 at all.

## Scope and intended use

- **Demo/test endpoints only** — e.g. Google's own reCAPTCHA v2 demo. Use it to
  learn, not to bypass protections on sites you don't own or aren't authorized to
  test.
- This repo deliberately contains **no bot-detection evasion** — no fingerprint
  spoofing, synthetic mouse movement, or webdriver masking. If the real browser
  session doesn't earn a pass on its own, the script does not try to fake being
  human. (A clean, long-lived Chrome profile is simply treated differently by
  reCAPTCHA than a fresh automation profile — that's the control working, not a bug.)

## Requirements

- Python 3.10+
- Google Chrome (tested with 154)
- `pip install -r requirements.txt`
  (selenium, undetected-chromedriver, requests, websocket-client)

## Install & run

```bash
git clone <your-fork-url>
cd Solution_Captcha
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Edit getSolve.py to point at your own demo page + sitekey, then:
python getSolve.py
```

`getSolve.py` is a thin example; the real entry point is `Solve.ReCaptcha(sitekey, url)`
in `Solve.py`, which returns the result dict described above. `SOLVE_TIMEOUT` in
`Solve.py` bounds the whole attempt.

## Repository layout

```
Solve.py       Main driver: Chrome launch, extension install, ReCaptcha() / HCaptcha().
getSolve.py    Minimal usage example (reCAPTCHA; hCaptcha example commented out).
hekt2/         Local reCAPTCHA solver extension (ONNX models + content scripts).
hekt/          hCaptcha solver extension, used by HCaptcha().
```

Each extension's `models/` directory holds the local ONNX files it ships with.
The remote 3×3 reCAPTCHA classifier models are **not** included and are not
available (see [What to expect](#what-to-expect)).

## Known limitations

- 3×3 challenges are unsolvable here (missing remote models — see above).
- 4×4 accuracy is limited by the segmentation model's recall; expect incomplete
  selections and retries.
- Challenge availability depends on browser/session reputation, which this project
  does not attempt to manipulate.

## License

MIT for the original code in this repo (see [LICENSE](LICENSE)). The bundled
`hekt/` and `hekt2/` extension is third-party code under its own license — see the
`*.LICENSE.txt` files in those directories.

## Disclaimer

Provided for educational and research purposes. You are responsible for using it
only where you have permission to do so. Automating or bypassing captchas on
systems you do not own or operate may violate their terms of service or the law.
