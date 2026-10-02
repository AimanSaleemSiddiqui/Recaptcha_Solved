# ReCaptcha
import undetected_chromedriver as webdriver
import os, time, json
import requests
from websocket import create_connection

# Chrome 137+ ignores the --load-extension command line switch, so unpacked
# extensions have to be installed over the browser-level DevTools protocol
# instead. ChromeDriver's execute_cdp_cmd talks to the *page* target, where the
# Extensions domain is not available, so we open the browser websocket directly.

# Dedicated profile for automation. Pointing this at a live Chrome profile fails
# while Chrome is running; use --user-data-dir + --profile-directory if you do
# want a real profile (e.g. '.../Google/Chrome' plus profile_dir='Profile 10.
PROFILE = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'chrome-profile')

# How long to wait for the extension to produce a token before giving up.
SOLVE_TIMEOUT = 180

# The extension logs this once its 3x3 per-label classifier host turns out to be
# unreachable. A 3x3 challenge therefore cannot be solved at all, so the only
# useful move is to abandon the attempt and let reCAPTCHA pick a fresh challenge.
# The marker is emitted only after the fetch has actually failed, never while a
# challenge is merely slow or still loading.
UNSUPPORTED_MARKER = '3x3 classifier UNAVAILABLE'

# Never begin another reload cycle without at least this much budget remaining.
# Together with SOLVE_TIMEOUT this is what bounds the reload cycle: there is
# deliberately no cap on the number of unsupported challenges skipped, because a
# count-based cap gave up with budget still left and so denied a later 4x4 its
# chance purely because earlier challenges had been unsolvable.
RELOAD_MIN_BUDGET = 20

# A visible challenge grid with this many tiles is a 4x4, which the local
# segmentation path can handle.
GRID_4X4_TILES = 16

BFRAME_SELECTOR = ("iframe[src*='/recaptcha/api2/bframe'], "
                   "iframe[src*='/recaptcha/enterprise/bframe']")

TILE_COUNT = "return document.querySelectorAll('.rc-imageselect-tile').length;"

# Set to False to silence the step-by-step trace.
DEBUG = True

# reCAPTCHA renders the checkbox in an `anchor` iframe and the image/grid
# challenge in a separate `bframe` iframe. The bframe exists from the start but
# is kept collapsed/hidden until a challenge is actually served, so a visible,
# reasonably sized bframe is the evidence that a real grid challenge was shown.
CHALLENGE_PROBE = """
return Array.from(
    document.querySelectorAll("iframe[src*='/recaptcha/'][src*='bframe']")
).some(frame => {
    const box = frame.getBoundingClientRect();
    if (box.width < 100 || box.height < 100) return false;
    for (let node = frame; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity) === 0) return false;
    }
    return true;
});
"""


def Log(message):
    if DEBUG:
        print(f'[Solve] {message}', flush=True)


def BrowserCdp(driver, method, params):
    address = driver.caps['goog:chromeOptions']['debuggerAddress']
    endpoint = requests.get(f'http://{address}/json/version').json()['webSocketDebuggerUrl']
    ws = create_connection(endpoint, suppress_origin=True)
    try:
        ws.send(json.dumps({'id': 1, 'method': method, 'params': params}))
        while True:
            message = json.loads(ws.recv())
            if message.get('id') == 1:
                if 'error' in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get('result')
    finally:
        ws.close()


def RunProfile(type, profile_dir=None):
    options = webdriver.ChromeOptions()
    options.add_argument(f'--user-data-dir={PROFILE}')
    if profile_dir:
        options.add_argument(f'--profile-directory={profile_dir}')
    # Capture only; needed so the driver can see the extension reporting an
    # unsupported challenge instead of having to guess from the DOM.
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()

    # Must happen before navigating: content scripts are only injected into
    # pages loaded after the extension is installed.
    extension = 'hekt' if type == 'hcaptcha' else 'hekt2'
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)), extension)
    BrowserCdp(driver, 'Extensions.loadUnpacked', {'path': path})
    time.sleep(2)  # let the service worker write its default settings
    return driver


def FindSiteKeys(driver, selector):
    """Every sitekey currently declared by widgets matching `selector`."""
    try:
        return driver.execute_script(
            "return Array.from(document.querySelectorAll(arguments[0]))"
            "  .map(e => e.dataset['sitekey'] || e.getAttribute('data-sitekey'))"
            "  .filter(Boolean);",
            selector,
        ) or []
    except Exception:
        return []


def WaitForWidget(driver, selector, key, url, script=None, timeout=60):
    """Wait for the page's own captcha widget to declare the expected sitekey.

    Returns (found, detected_sitekeys).

    With `script=None` the target page is left completely untouched: if the
    expected widget never appears we say so rather than replacing the page with
    a widget of our own, because a token from an injected widget says nothing
    about the captcha that actually guards the target page.
    """
    deadline = time.time() + timeout
    injected = False
    detected = []
    while time.time() < deadline:
        detected = FindSiteKeys(driver, selector)
        if key in detected:
            return True, detected
        if script is not None and not injected:
            # Legacy fallback (hCaptcha only): no widget at all, or the page uses
            # a different sitekey than the one we were asked to solve - replace
            # the page with our own standalone widget.
            Log(f'{selector}: expected sitekey absent, injecting standalone widget')
            driver.execute_script(script)
            injected = True
            time.sleep(3)
        else:
            time.sleep(1)
    return False, detected


def ReadConsole(driver):
    """Drain the browser console buffer. Empty list if capture is unavailable."""
    try:
        return [entry['message'] for entry in driver.get_log('browser')]
    except Exception:
        return []


def TopDocument(driver):
    try:
        driver.switch_to.default_content()
    except Exception:
        pass


def VisibleGridSize(driver):
    """Tile count of the currently visible challenge grid, or None if no grid is
    showing.

    The tiles live inside the bframe, so this has to switch frames to count them
    and must always come back to the top document - both the token read and
    CHALLENGE_PROBE run there, and a leaked frame would silently make them fail.
    """
    TopDocument(driver)
    try:
        frames = driver.find_elements('css selector', BFRAME_SELECTOR)
    except Exception:
        return None
    try:
        for frame in frames:
            count = None
            try:
                if not frame.is_displayed():
                    continue
                driver.switch_to.frame(frame)
                count = driver.execute_script(TILE_COUNT)
            except Exception:
                count = None
            finally:
                TopDocument(driver)
            if count:
                return count
    finally:
        TopDocument(driver)
    return None


def WaitForToken(driver, read_script, timeout=SOLVE_TIMEOUT, probe=None, stop=None):
    """Poll for a token. `stop` is an optional predicate; when it returns true the
    wait is abandoned early (a token found in the same poll still wins)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if probe is not None:
            probe()
        try:
            token = driver.execute_script(read_script)
            if token:
                return token
        except Exception:
            pass
        if stop is not None and stop():
            return None
        time.sleep(3)
    return None


def ReCaptcha(key, url):
    # No fallback injection script here on purpose. We only ever drive the
    # widget the target page itself renders, so that a returned token is
    # evidence about *that* captcha and nothing else.
    driver = RunProfile('recaptcha')
    challenge = {'shown': False}

    def WatchChallenge():
        try:
            if driver.execute_script(CHALLENGE_PROBE) and not challenge['shown']:
                challenge['shown'] = True
                Log('image/grid challenge iframe became visible')
        except Exception:
            pass

    READ_TOKEN = "const e = document.getElementById('g-recaptcha-response'); return e ? e.value : '';"
    unsupported = {'seen': False}
    reloads = 0

    def Unsupported():
        """True once the extension has reported the 3x3 classifier unavailable
        for the challenge currently on screen.

        A latched marker is ignored while a 4x4 grid is actually visible: the
        challenge may have rotated to a solvable one inside the poll window, and
        an in-progress 4x4 belongs to the existing 4x4 flow, not to us.
        """
        for message in ReadConsole(driver):
            if UNSUPPORTED_MARKER in message:
                unsupported['seen'] = True
        if unsupported['seen'] and VisibleGridSize(driver) == GRID_4X4_TILES:
            Log('4x4 challenge is on screen - ignoring the stale '
                'unsupported-3x3 marker and letting it proceed')
            unsupported['seen'] = False
        return unsupported['seen']

    try:
        Log(f'target url:        {url}')
        Log(f'expected sitekey:  {key}')
        deadline = time.time() + SOLVE_TIMEOUT
        detected = []

        while True:
            # The existing normal page-load/wait path, unchanged.
            driver.get(url)
            found, detected = WaitForWidget(driver, '.g-recaptcha', key, url)
            if not reloads:
                Log(f'detected sitekeys: {detected or "none"}')
                Log(f'original widget found: {found}')
            if not found:
                return {
                    'status': False,
                    'data': 'Target reCAPTCHA widget/sitekey not found on the original page',
                    'expected_sitekey': key,
                    'detected_sitekeys': detected,
                    'challenge_displayed': False,
                    'unsupported_reloads': reloads,
                }

            # Discard whatever the previous attempt logged, so a stale marker
            # cannot trigger an immediate reload of this fresh page.
            ReadConsole(driver)
            unsupported['seen'] = False

            remaining = deadline - time.time()
            if remaining <= 0:
                break
            Log(f'waiting up to {remaining:.0f}s for the solver to produce a token...')
            token = WaitForToken(driver, READ_TOKEN, timeout=remaining,
                                 probe=WatchChallenge, stop=Unsupported)
            if token:
                Log('token obtained: True')
                Log(f'image/grid challenge displayed: {challenge["shown"]}')
                data = {
                    'Solution': token,
                    'User-Agent': driver.execute_script('return navigator.userAgent'),
                }
                return {
                    'status': True,
                    'data': json.dumps(data),
                    'expected_sitekey': key,
                    'detected_sitekeys': detected,
                    # True only if a challenge iframe was actually visible while
                    # we were waiting. False means the token came from a
                    # checkbox-only pass, not from solving a grid.
                    'challenge_displayed': challenge['shown'],
                    'unsupported_reloads': reloads,
                }

            # Only an actually-reported unsupported classifier justifies a reload.
            if not unsupported['seen']:
                break
            if deadline - time.time() < RELOAD_MIN_BUDGET:
                Log('3x3 classifier unavailable; too little budget left to retry')
                break
            reloads += 1
            Log(f'3x3 classifier unavailable - unsupported challenge, abandoning it '
                f'and reloading for a fresh one (reload {reloads})')

        Log('token obtained: False')
        Log(f'image/grid challenge displayed: {challenge["shown"]}')
        Log(f'unsupported-challenge reloads: {reloads}')
        return {
            'status': False,
            'data': (f'not solved within {SOLVE_TIMEOUT}s'
                     + (f' ({reloads} unsupported 3x3 challenge(s) skipped)' if reloads else '')),
            'expected_sitekey': key,
            'detected_sitekeys': detected,
            'challenge_displayed': challenge['shown'],
            'unsupported_reloads': reloads,
        }
    finally:
        driver.quit()


def HCaptcha(key, url):
    script = """
    const hcaptchaSiteKey = '{}';
    const newBody = document.createElement('body');
    const hcaptchaDiv = document.createElement('div');
    hcaptchaDiv.classList.add('h-captcha');
    hcaptchaDiv.dataset.sitekey = hcaptchaSiteKey;
    const script = document.createElement('script');
    script.src = 'https://hcaptcha.com/1/api.js';
    newBody.appendChild(hcaptchaDiv);
    newBody.appendChild(script);
    document.documentElement.replaceChild(newBody, document.body);
    """.format(key)

    driver = RunProfile('hcaptcha')
    try:
        driver.get(url)
        # hCaptcha keeps the original injecting fallback; only the reCAPTCHA
        # path had to stop replacing the target page.
        found, _ = WaitForWidget(driver, '.h-captcha', key, url, script)
        if not found:
            return {'status': False, 'data': 'hCaptcha widget with that sitekey never appeared'}

        # hCaptcha writes its token to h-captcha-response and mirrors it into
        # g-recaptcha-response for drop-in compatibility; either may be missing.
        token = WaitForToken(
            driver,
            "for (const name of ['h-captcha-response', 'g-recaptcha-response']) {"
            "  const e = document.getElementsByName(name)[0];"
            "  if (e && e.value) return e.value;"
            "}"
            "return '';",
        )
        if not token:
            return {'status': False, 'data': f'not solved within {SOLVE_TIMEOUT}s'}

        data = {
            'Solution': token,
            'User-Agent': driver.execute_script('return navigator.userAgent'),
        }
        return {'status': True, 'data': json.dumps(data)}
    finally:
        driver.quit()