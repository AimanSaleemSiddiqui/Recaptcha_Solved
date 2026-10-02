"""Measure whether S() keeps re-clicking the checkbox while the grid is open.

Installs a click counter on #recaptcha-anchor inside the anchor iframe, then
samples once a second while a challenge is displayed in the bframe. Also reads
aria-checked, which is what d() keys off inside the anchor frame (the anchor
document has no #recaptcha-verify-button, so d() reduces to the aria-checked
test there).

The sample timeline is anchored to the moment the grid first becomes visible,
so runs against different builds of hekt2/recaptcha.js are directly comparable.

Usage:  venv/bin/python -u probe_anchor.py [label] [2captcha|google]
        SUSPICIOUS=1 forces reCAPTCHA to serve image challenges.
"""
import os
import sys
import time

import Solve
import verify_grid
from verify_grid import ANCHOR, BFRAME, PROBE, TARGETS

# How long to keep sampling after the grid first appears.
WATCH = 45
# How long to wait for a grid to show up at all.
GRID_WAIT = 40

COUNTER = """
const el = document.querySelector('#recaptcha-anchor');
if (el && !window.__hooked) {
    window.__hooked = true;
    window.__clicks = 0;
    el.addEventListener('click', () => { window.__clicks++; }, true);
}
const cb = document.querySelector('.recaptcha-checkbox');
return {
    clicks: window.__clicks === undefined ? null : window.__clicks,
    ariaChecked: cb ? cb.getAttribute('aria-checked') : null,
    hasVerifyButton: !!document.querySelector('#recaptcha-verify-button'),
    spinner: cb ? cb.className : null,
};
"""


def InAnchor(driver, script):
    driver.switch_to.default_content()
    for frame in driver.find_elements('css selector', ANCHOR):
        try:
            if not frame.is_displayed():
                continue
            driver.switch_to.frame(frame)
            out = driver.execute_script(script)
            driver.switch_to.default_content()
            return out
        except Exception:
            driver.switch_to.default_content()
    return None


def InBframe(driver, script):
    driver.switch_to.default_content()
    for frame in driver.find_elements('css selector', BFRAME):
        try:
            if not frame.is_displayed():
                continue
            driver.switch_to.frame(frame)
            out = driver.execute_script(script)
            driver.switch_to.default_content()
            if out and out.get('tiles'):
                return out
        except Exception:
            driver.switch_to.default_content()
    return None


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'run'
    url, sitekey = TARGETS[sys.argv[2] if len(sys.argv) > 2 else 'google']

    driver = verify_grid.Launch(suspicious=os.environ.get('SUSPICIOUS') == '1')
    console = []
    try:
        Solve.Log(f'[{label}] target: {url}')
        driver.get(url)
        Solve.WaitForWidget(driver, '.g-recaptcha', sitekey, url, timeout=30)

        # Hook the counter as early as possible, before the grid opens.
        for _ in range(20):
            if InAnchor(driver, COUNTER):
                break
            time.sleep(0.5)

        # Wait for the grid, remembering how many clicks it took to get there.
        clicks_to_open, deadline = None, time.time() + GRID_WAIT
        while time.time() < deadline:
            b = InBframe(driver, PROBE)
            if b:
                clicks_to_open = (InAnchor(driver, COUNTER) or {}).get('clicks')
                break
            time.sleep(0.5)

        if clicks_to_open is None:
            print(f'[{label}] NO GRID APPEARED within {GRID_WAIT}s '
                  f'(clean IP waved through - rerun with SUSPICIOUS=1)')
            return

        print()
        print(f'--- [{label}] grid visible; t=0 is that moment ---')
        print(f"{'t':>4} {'grid':>6} {'tiles':>5} {'sel':>4} {'anchorClicks':>13} "
              f"{'ariaChecked':>12} {'verifyBtnInAnchor':>18}")
        print('-' * 72)
        start = time.time()
        marks = {}
        while time.time() - start < WATCH:
            t = time.time() - start
            a = InAnchor(driver, COUNTER) or {}
            b = InBframe(driver, PROBE)
            grid = '-' if not b else {9: '3x3', 16: '4x4'}.get(b['tiles'], str(b['tiles']))
            print(f"{t:4.0f} {grid:>6} {(b or {}).get('tiles','-')!s:>5} "
                  f"{(b or {}).get('selected','-')!s:>4} {a.get('clicks')!s:>13} "
                  f"{a.get('ariaChecked')!s:>12} {a.get('hasVerifyButton')!s:>18}")
            for m in (0, 10, 20, 30, 40):
                if m not in marks and t >= m:
                    marks[m] = a.get('clicks')
            console.extend(verify_grid.Console(driver))
            time.sleep(1)

        console.extend(verify_grid.Console(driver))
        print()
        print(f'[{label}] clicks to open the challenge : {clicks_to_open}')
        print(f'[{label}] anchor clicks at t=0/10/20/30/40s : '
              + ' -> '.join(str(marks.get(m)) for m in (0, 10, 20, 30, 40)))
        first, last = marks.get(0), marks.get(40)
        if first is not None and last is not None:
            print(f'[{label}] clicks accrued while the grid was open : {last - first}')
    finally:
        driver.quit()

    interesting = [m for m in console
                   if 'hektCaptcha' in m or 'Failed to fetch' in m
                   or 'hekt.akmal' in m or 'Uncaught' in m]
    print()
    print(f'--- [{label}] console ({len(interesting)} relevant of {len(console)}) ---')
    seen = set()
    for m in interesting:
        key = m.split(' ', 2)[-1][:160]
        if key in seen:
            continue
        seen.add(key)
        print('  ' + m[:400])


if __name__ == '__main__':
    main()
