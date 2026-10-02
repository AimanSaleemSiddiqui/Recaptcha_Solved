"""Verify the hekt2 4x4 (local segmentation) reCAPTCHA path in isolation.

Why this exists: recaptcha.js loads its 3x3 per-label classifier from
https://hekt.akmal.dev, which is now NXDOMAIN. The fetch rejects, and because
there is no try/catch anywhere in A() or its driver loop, the bframe's solve
loop dies permanently on the first 3x3 challenge. The 4x4 branch instead loads
recaptcha-segmentation.ort / mask-yolov5-seg.ort / nms-yolov5-det.ort over
chrome-extension:// URLs and touches no network at all.

So the 4x4 path can only be observed on a page load where the *first* challenge
served is a 16-tile grid. Each attempt therefore reloads the page from scratch,
which re-injects the content script and gives us a live loop again.

Usage:  venv/bin/python verify_grid.py [attempts]
"""
import json
import os
import sys
import time

import undetected_chromedriver as webdriver

import Solve

TARGETS = {
    '2captcha': ('https://2captcha.com/demo/recaptcha-v2',
                 '6LfD3PIbAAAAAJs_eEHvoOl75_83eXSqpPSRFJ_u'),
    # Google's own v2 demo. Its public test key challenges far more readily than
    # the 2captcha demo, which waves a fresh profile straight through.
    'google': ('https://www.google.com/recaptcha/api2/demo',
               '6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-'),
}
URL, SITEKEY = TARGETS['2captcha']

# How long to watch a 4x4 grid before calling it a failure.
WATCH_4X4 = 90
# How long to wait for a challenge grid to render after the checkbox is clicked.
CHALLENGE_WAIT = 25

BFRAME = "iframe[src*='/recaptcha/api2/bframe'], iframe[src*='/recaptcha/enterprise/bframe']"

# Read the challenge state from inside the bframe document.
PROBE = """
const tiles = document.querySelectorAll('.rc-imageselect-tile');
const table = document.querySelector('.rc-imageselect-table-33, .rc-imageselect-table-44, .rc-imageselect-table-42');
const desc = document.querySelector('.rc-imageselect-desc-no-canonical, .rc-imageselect-desc');
return {
    tiles: tiles.length,
    table: table ? table.className : null,
    task: desc ? desc.innerText.replace(/\\s+/g, ' ').trim() : null,
    selected: document.querySelectorAll('.rc-imageselect-tileselected').length,
    dynamic: !!document.querySelector('.rc-imageselect-dynamic-selected'),
};
"""


def Launch(suspicious=False):
    """Same profile + browser-level CDP extension install as Solve.RunProfile,
    plus browser log capture so we can see the content script's exceptions.

    suspicious=True uses a throwaway profile and re-exposes navigator.webdriver,
    which pushes reCAPTCHA into serving image challenges instead of waving a
    clean residential IP straight through.
    """
    import os
    options = webdriver.ChromeOptions()
    profile = Solve.PROFILE if not suspicious else os.path.join(
        os.path.abspath(os.path.dirname(__file__)), 'chrome-profile-throwaway')
    options.add_argument(f'--user-data-dir={profile}')
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    if suspicious:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator,'webdriver',{get:()=>true});"
        })
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'hekt2')
    Solve.BrowserCdp(driver, 'Extensions.loadUnpacked', {'path': path})
    time.sleep(2)
    return driver


def ReadChallenge(driver):
    """Switch into the bframe, read challenge state, switch back."""
    driver.switch_to.default_content()
    frames = driver.find_elements('css selector', BFRAME)
    for frame in frames:
        try:
            if not frame.is_displayed():
                continue
            driver.switch_to.frame(frame)
            state = driver.execute_script(PROBE)
            driver.switch_to.default_content()
            if state and state.get('tiles'):
                return state
        except Exception:
            driver.switch_to.default_content()
    return None


def Token(driver):
    driver.switch_to.default_content()
    try:
        return driver.execute_script(
            "const e = document.getElementById('g-recaptcha-response'); return e ? e.value : '';"
        )
    except Exception:
        return ''


def Console(driver):
    try:
        return [e['message'] for e in driver.get_log('browser')]
    except Exception:
        return []


def Attempt(driver, n):
    """One fresh page load. Returns a record of what was served and observed."""
    record = {'attempt': n, 'grid': None, 'task': None, 'max_selected': 0,
              'token': False, 'verdict': None, 'errors': []}

    Solve.Log(f'--- attempt {n}: loading {URL} ---')
    driver.get(URL)

    found, detected = Solve.WaitForWidget(driver, '.g-recaptcha', SITEKEY, URL, timeout=30)
    if not found:
        record['verdict'] = f'widget not found (detected={detected})'
        return record

    # The extension opens the challenge itself (recaptcha_auto_open).
    state = None
    deadline = time.time() + CHALLENGE_WAIT
    while time.time() < deadline and not state:
        state = ReadChallenge(driver)
        if not state:
            time.sleep(1)

    if not state:
        record['verdict'] = 'no challenge grid appeared (checkbox-only pass?)'
        record['token'] = bool(Token(driver))
        return record

    grid = '4x4' if state['tiles'] == 16 else '3x3' if state['tiles'] == 9 else f"{state['tiles']}tiles"
    record['grid'] = grid
    record['task'] = state['task']
    Solve.Log(f"attempt {n}: served {grid} ({state['tiles']} tiles) - task: {state['task']!r}")

    if grid != '4x4':
        record['verdict'] = 'skipped - not a 4x4 (3x3 path is the known-dead remote one)'
        record['errors'] = [m for m in Console(driver) if 'hekt' in m or 'Failed to fetch' in m]
        return record

    # A 4x4: this is the local-segmentation path. Watch whether the extension
    # actually selects tiles and produces a token.
    Solve.Log(f'attempt {n}: 4x4 grid - watching local segmentation path for {WATCH_4X4}s')
    deadline = time.time() + WATCH_4X4
    while time.time() < deadline:
        cur = ReadChallenge(driver)
        if cur:
            record['max_selected'] = max(record['max_selected'], cur['selected'])
        tok = Token(driver)
        if tok:
            record['token'] = True
            break
        time.sleep(2)

    record['errors'] = [m for m in Console(driver) if 'hekt' in m or 'Failed to fetch' in m]
    if record['token']:
        record['verdict'] = 'PASS - 4x4 solved, token issued'
    elif record['max_selected'] > 0:
        record['verdict'] = f"PARTIAL - clicked {record['max_selected']} tiles but no token"
    else:
        record['verdict'] = 'FAIL - 4x4 shown but no tile was ever clicked'
    return record


ANCHOR = "iframe[src*='/recaptcha/api2/anchor'], iframe[src*='/recaptcha/enterprise/anchor']"


def ClickCheckbox(driver):
    driver.switch_to.default_content()
    for frame in driver.find_elements('css selector', ANCHOR):
        try:
            if not frame.is_displayed():
                continue
            driver.switch_to.frame(frame)
            driver.find_element('css selector', '#recaptcha-anchor').click()
            driver.switch_to.default_content()
            return True
        except Exception:
            driver.switch_to.default_content()
    return False


def NextChallenge(driver):
    """Click the bframe's reload button to pull a fresh challenge."""
    driver.switch_to.default_content()
    for frame in driver.find_elements('css selector', BFRAME):
        try:
            if not frame.is_displayed():
                continue
            driver.switch_to.frame(frame)
            driver.find_element('css selector', '#recaptcha-reload-button').click()
            driver.switch_to.default_content()
            return True
        except Exception:
            driver.switch_to.default_content()
    return False


def Burn(driver, cycles):
    """reCAPTCHA waves a clean IP straight through. Hammer reset+click until it
    starts serving image challenges, then sample which grid sizes it hands out.
    This only observes what Google serves - the extension is irrelevant here."""
    Solve.Log(f'=== phase 1: burning reputation to force challenges (max {cycles} cycles) ===')
    driver.get(URL)
    Solve.WaitForWidget(driver, '.g-recaptcha', SITEKEY, URL, timeout=30)

    samples = []
    for i in range(1, cycles + 1):
        driver.switch_to.default_content()
        try:
            driver.execute_script('grecaptcha.reset()')
        except Exception:
            pass
        time.sleep(1)
        ClickCheckbox(driver)

        state, deadline = None, time.time() + 12
        while time.time() < deadline and not state:
            state = ReadChallenge(driver)
            if not state:
                time.sleep(1)

        if not state:
            Solve.Log(f'  cycle {i}: no challenge (still trusted)')
            continue

        # Got a challenge - now sample many grids cheaply via the reload button.
        for _ in range(6):
            cur = ReadChallenge(driver)
            if cur and cur.get('tiles'):
                grid = {9: '3x3', 16: '4x4'}.get(cur['tiles'], f"{cur['tiles']}tiles")
                samples.append((grid, cur['task'], cur['dynamic']))
                Solve.Log(f"  sample: {grid:8} dynamic={cur['dynamic']!s:5} task={cur['task']!r}")
            if not NextChallenge(driver):
                break
            time.sleep(2.5)
        if samples:
            break

    return samples


def main():
    global URL, SITEKEY
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    if len(sys.argv) > 2:
        URL, SITEKEY = TARGETS[sys.argv[2]]
    Solve.Log(f'target: {URL}')
    driver = Launch(suspicious=os.environ.get("SUSPICIOUS") == "1")
    records = []
    try:
        if len(sys.argv) > 3 and sys.argv[3] == 'burn':
            samples = Burn(driver, cycles=attempts)
            print()
            print('=' * 70)
            print('PHASE 1 - grid types Google actually served')
            print('=' * 70)
            for g, t, d in samples:
                print(f'  {g:8} dynamic={d!s:5} {t!r}')
            print(f"  totals: 3x3={sum(1 for s in samples if s[0]=='3x3')} "
                  f"4x4={sum(1 for s in samples if s[0]=='4x4')}")
            if not samples:
                print('  none - IP still fully trusted, no challenge served')
            return
        for n in range(1, attempts + 1):
            try:
                records.append(Attempt(driver, n))
            except Exception as exc:
                records.append({'attempt': n, 'verdict': f'error: {exc}'})
            Solve.Log(f'attempt {n} result: {records[-1]}')
    finally:
        driver.quit()

    print()
    print('=' * 70)
    print('SUMMARY')
    print('=' * 70)
    for r in records:
        print(json.dumps(r))
    grids = [r.get('grid') for r in records]
    print()
    print('4x4 served :', grids.count('4x4'))
    print('3x3 served :', grids.count('3x3'))
    print('4x4 PASS   :', sum(1 for r in records if r.get('verdict', '').startswith('PASS')))


if __name__ == '__main__':
    main()
