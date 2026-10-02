#!/usr/bin/env python3
"""Surgical string patches for hekt2/recaptcha.js (1.2MB minified bundle).

Scope: anchor/bframe control flow, failure observability, and label
normalization. Models, model loading, segmentation/mask/NMS and the
tile-selection algorithm itself are untouched -- normalization only changes
which existing class the existing detector is asked to match.

Run from the repo root. Idempotent in the sense that it refuses to apply twice.
To regenerate from scratch:
    git show d6078b1:hekt2/recaptcha.js > hekt2/recaptcha.js && python3 patch_recaptcha.py
"""
import sys, shutil, os

PATH = "hekt2/recaptcha.js"

PATCHES = []


def patch(name, old, new):
    PATCHES.append((name, old, new))


# ---------------------------------------------------------------- 1. anchor loop
# S() had no image-challenge guard: while a grid was open, d() collapses to
# aria-checked==="true" (there is no #recaptcha-verify-button in the anchor
# document), so the else-branch clicked #recaptcha-anchor every iteration.
patch(
    "S() anchor guard",
    'async function S(){const t=undefined;!0===(await n.get({key:"recaptcha_widget_visible",tab_specific:!0})).value&&(d()?O||(O=!0):(O=!1,await e.sleep(500),c()))}',
    'async function S(){const t=undefined;'
    'if(!0!==(await n.get({key:"recaptcha_widget_visible",tab_specific:!0})).value)return;'
    'if(!0===(await n.get({key:"recaptcha_image_visible",tab_specific:!0})).value){'
    'HK_HELD||(HK_HELD=!0,console.log("[hektCaptcha][recaptcha][anchor] image challenge visible: suspending checkbox interaction until it closes"));'
    'return}'
    'HK_HELD&&(HK_HELD=!1,console.log("[hektCaptcha][recaptcha][anchor] image challenge no longer visible: checkbox interaction re-enabled"));'
    'd()?O||(O=!0):(O=!1,await e.sleep(500),c())}',
)

# ---------------------------------------------------------------- 2. state flags
patch(
    "module-scope flags",
    "let O=!1,I=!1,P=[];for(;;){",
    "let O=!1,I=!1,P=[],HK_HELD=!1,HK_CLS_DOWN=!1;for(;;){",
)

# ---------------------------------------------------------------- 3. driver loop
# Nothing wrapped the driver loop, so any rejection inside A()/S() escaped the
# for(;;) and permanently killed this frame's automation.
patch(
    "driver loop try/catch",
    "let t=await chrome.storage.local.get(null);u()&&t.recaptcha_auto_open?await S():l()&&t.recaptcha_auto_solve&&await A(t)}",
    "let t=await chrome.storage.local.get(null);"
    "try{u()&&t.recaptcha_auto_open?await S():l()&&t.recaptcha_auto_solve&&await A(t)}"
    "catch(HK_E){console.error(\"[hektCaptcha][recaptcha][loop] iteration failed; loop kept alive:\",HK_E&&HK_E.stack||String(HK_E))}}",
)

# ---------------------------------------------------------------- 4. label normalization
# Four compounding defects in the original one-liner:
#   1. it underscored BEFORE consulting the alias map,
#   2. so every multi-word alias key ("fire hydrants") was unreachable,
#   3. alias values are space-separated while the class list is underscored,
#   4. .replace(" ","_") substitutes only the FIRST space.
# All four fall out of doing the steps in the right order and using a global
# regex, which is what this patch does.
patch(
    "label normalization fix + diagnostics",
    'let R=g.replace("Select all squares with","").replace("Select all images with","").trim().replace(/^(a|an)\\s+/i,"").toLowerCase().replace(" ","_");R=M[R]||R;',
    # Correct order: extract -> lowercase -> alias (while spaces are still
    # spaces) -> underscore EVERY space -> exact class-list lookup.
    'const HK_Z0=g.replace("Select all squares with","").replace("Select all images with","").trim().replace(/^(a|an)\\s+/i,"").toLowerCase(),'
    'HK_HAS=t=>Object.prototype.hasOwnProperty.call(M,t),'
    'HK_HIT=HK_HAS(HK_Z0),'
    'HK_A=HK_HIT?M[HK_Z0]:HK_Z0;'
    'let R=HK_A.replace(/ /g,"_");'
    'const HK_IN=j.includes(R),HK_WHY=[];'
    'if(!HK_IN){'
    'if(HK_HIT)HK_WHY.push("alias map resolved "+JSON.stringify(HK_Z0)+" to "+JSON.stringify(HK_A)+" but "+JSON.stringify(R)+" is not a class-list entry");'
    'else if(HK_Z0.indexOf(" ")>=0)HK_WHY.push("multi-word label with no alias-map entry; add a "+JSON.stringify(HK_Z0)+" key mapping to the singular phrase");'
    'else HK_WHY.push("label is absent from the class list and has no alias-map entry");}'
    'console.log("[hektCaptcha][recaptcha][label] grid="+k+"x"+k'
    '+" original="+JSON.stringify(g)'
    '+" extracted="+JSON.stringify(HK_Z0)'
    '+" aliased="+JSON.stringify(HK_A)'
    '+" alias_hit="+HK_HIT'
    '+" normalized="+JSON.stringify(R)'
    '+" in_class_list="+HK_IN'
    '+(HK_IN?"":" NOMATCH reasons="+JSON.stringify(HK_WHY)+" class_list="+JSON.stringify(j)));',
)

# The alias map had no key for two of the multi-word prompts reCAPTCHA serves, so
# reordering alone cannot reach `parking_meter` / `mountain_or_hill`. Values stay
# space-separated to match the rest of the map; the underscoring step above
# converts them.
patch(
    "alias map: add the two missing multi-word keys",
    'mountains:"mountain or hill","palm trees":"palm tree",',
    'mountains:"mountain or hill","mountains or hills":"mountain or hill",'
    '"parking meters":"parking meter","palm trees":"palm tree",',
)

# ---------------------------------------------------------------- 5. 3x3 classifier
# hekt.akmal.dev is NXDOMAIN, so fetch() REJECTS -- the `200!==n.status` guard
# assumed the request always completes. Catch it, report it, abort this attempt.
patch(
    "3x3 classifier failure handling",
    'if(3===k){const e=`https://hekt.akmal.dev/${R}-rc.ort`,n=await fetch(e,{method:"HEAD"});'
    'if(200!==n.status)return console.log("error getting model",n,R),_();'
    'const[i,a]=await Promise.all([r.InferenceSession.create(chrome.runtime.getURL("models/mobilenetv3.ort")),r.InferenceSession.create(e)]),s={};',
    'if(3===k){const e=`https://hekt.akmal.dev/${R}-rc.ort`;let n;'
    'try{n=await fetch(e,{method:"HEAD"})}'
    'catch(HK_E){'
    'console.error("[hektCaptcha][recaptcha][classifier] 3x3 classifier UNAVAILABLE: remote head-model host is unreachable. Aborting this challenge attempt.",'
    '{url:e,label:R,first_occurrence:!HK_CLS_DOWN,error:HK_E&&HK_E.message||String(HK_E)});'
    'HK_CLS_DOWN=!0;return}'
    'if(200!==n.status)return console.log("error getting model",n,R),_();'
    'let i,a;'
    'try{[i,a]=await Promise.all([r.InferenceSession.create(chrome.runtime.getURL("models/mobilenetv3.ort")),r.InferenceSession.create(e)])}'
    'catch(HK_E){'
    'console.error("[hektCaptcha][recaptcha][classifier] 3x3 classifier UNAVAILABLE: head model could not be loaded. Aborting this challenge attempt.",'
    '{url:e,label:R,first_occurrence:!HK_CLS_DOWN,error:HK_E&&HK_E.message||String(HK_E)});'
    'HK_CLS_DOWN=!0;return}'
    'const s={};',
)

# ---------------------------------------------------------------- 6. 4x4 match diagnostics
patch(
    "4x4 detected-class collector",
    "b=e/4,y=b**2;for(let n=0;n<g.data.length;n++){",
    "b=e/4,y=b**2;const HK_SEEN=[];let HK_PASS=0;for(let n=0;n<g.data.length;n++){",
)

patch(
    "4x4 exact-match gate instrumentation",
    "if(j[l.indexOf(c)]!==R)continue;",
    "const HK_CLS=j[l.indexOf(c)];HK_SEEN.push(HK_CLS);if(HK_CLS!==R)continue;HK_PASS++;",
)

patch(
    "4x4 match summary log",
    "S[Math.floor(t/4)][t%4]/y>.1&&(D[t]=!0)}}}let $=0;",
    "S[Math.floor(t/4)][t%4]/y>.1&&(D[t]=!0)}}"
    'console.log("[hektCaptcha][recaptcha][match] grid=4x4 target="+JSON.stringify(R)'
    '+" detections="+g.data.length'
    '+" detected_classes="+JSON.stringify(HK_SEEN)'
    '+" matched_detections="+HK_PASS'
    '+" tiles_selected="+D.filter(Boolean).length'
    '+(HK_SEEN.length&&!HK_PASS?" NOMATCH: no detection argmax class equals the target":'
    'HK_PASS&&!D.some(Boolean)?" MATCHED the target but no tile cleared the mask-coverage threshold":""));'
    "}let $=0;",
)


# ---------------------------------------------------------------- 7. y() lifecycle
# Three composing control-flow defects, all in the challenge-signature waiter:
#
#   FIX 1 - y() had no timeout and resolved ONLY when the signature changed, so
#           any A() return that did not advance the on-screen challenge parked
#           the whole for(;;) driver loop (measured: 119s and 116s frozen).
#           It now mirrors p()'s deadline pattern and resolves null instead.
#   FIX 2 - the reentrancy guard `n` was set before `await m(t)` and only reset
#           on non-throwing paths. m() throws whenever the instructions element
#           is missing or single-line (its else branch is literally
#           `e.join("\n")` with e===null), which left n stuck true forever and
#           the interval a permanent no-op. `n` is now released in a finally.
#   FIX 3 - a grid sampled mid-decode has every naturalWidth at 0, so neither
#           the >=300 nor the ==100 branch fires, yet [null,[null...]] still
#           differed from `b` and RESOLVED -- handing the 4x4 path an empty L
#           and throwing "Cannot read properties of undefined (reading
#           'resize')". Such samples are now discarded and polling continues.
#
# The signature itself, the guards that define a valid challenge, the parsing in
# m(), and every resolve payload are unchanged.
#
# Note on shadowing: inside `new Promise((e=>...))` the resolve callback shadows
# the Utils class `e`, so the deadline helper is captured in y()'s own scope
# where `e` is still Utils -- the same reason p() names its resolve param `n`.
patch(
    "y(): timeout, guard release, malformed-sample rejection",
    'function y(t=500){return new Promise((e=>{let n=!1;const r=setInterval((async()=>{'
    'if(n)return;n=!0;'
    'const t=document.querySelector(".rc-imageselect-instructions")?.innerText?.split("\\n");'
    'let i=await m(t);if(!i)return void(n=!1);'
    'const o=3===t.length,a=document.querySelectorAll("table tr td");'
    'if(9!==a.length&&16!==a.length)return void(n=!1);'
    'const s=[],u=Array(a.length).fill(null);let l=null,c=!1,h=0;'
    'for(const t of a){const e=t?.querySelector("img");if(!e)return void(n=!1);'
    'const r=g(e);if(!r||""===r)return void(n=!1);'
    'e.naturalWidth>=300?l=r:100==e.naturalWidth&&(u[h]=r,c=!0),s.push(t),h++}'
    'c&&(l=null);const f=JSON.stringify([l,u]);'
    'if(b!==f)return b=f,clearInterval(r),n=!1,e({task:i,is_hard:o,cells:s,background_url:l,urls:u});'
    'n=!1}),t)}))}',

    'function y(t=500,HK_TO=15e3){'
    'const HKnow=()=>e.time(),HKdl=HKnow()+HK_TO;'
    'return new Promise((e=>{let n=!1,HKr="(none)";const r=setInterval((async()=>{'
    'if(n)return;'
    'n=!0;'
    'try{'
    # FIX 1: deadline, mirroring p()'s e.time()-based pattern. Resolves null.
    'if(HKnow()>HKdl)return clearInterval(r),'
    'console.log("[hektCaptcha][recaptcha][y] no new challenge within "+HK_TO+"ms; yielding null. last block reason: "+HKr),'
    'e(null);'
    'const t=document.querySelector(".rc-imageselect-instructions")?.innerText?.split("\\n");'
    'let i=await m(t);if(!i)return void(HKr="task text empty");'
    'const o=3===t.length,a=document.querySelectorAll("table tr td");'
    'if(9!==a.length&&16!==a.length)return void(HKr="cell count "+a.length+", expected 9 or 16");'
    'const s=[],u=Array(a.length).fill(null);let l=null,c=!1,h=0;'
    'for(const t of a){const e=t?.querySelector("img");if(!e)return void(HKr="a cell has no <img> yet");'
    'const r=g(e);if(!r||""===r)return void(HKr="a cell <img> has an empty src");'
    'e.naturalWidth>=300?l=r:100==e.naturalWidth&&(u[h]=r,c=!0),s.push(t),h++}'
    'c&&(l=null);'
    # FIX 3: require a real background url or at least one real tile url.
    'if(null===l&&!c)return void(HKr="malformed all-null sample: no background url and no tile urls (images not decoded yet)");'
    'const f=JSON.stringify([l,u]);'
    'if(b!==f)return b=f,clearInterval(r),e({task:i,is_hard:o,cells:s,background_url:l,urls:u});'
    'HKr="signature identical to the last resolved challenge"'
    '}catch(HK_E){'
    'HKr="poll threw: "+(HK_E&&HK_E.message||String(HK_E));'
    'console.error("[hektCaptcha][recaptcha][y] poll threw; guard released in finally so polling continues:",HK_E&&HK_E.stack||String(HK_E))'
    # FIX 2: the guard is released no matter how the poll exits.
    '}finally{n=!1}'
    '}),t)}))}',
)

# A() must treat a null y() as "no new challenge" and return, so the driver loop
# gets control back and retries on its next tick.
patch(
    "A(): handle a null y() result",
    "const{task:g,is_hard:m,cells:b,background_url:S,urls:A}=await y(),O=[],k=9==b.length?3:4;",
    'const HKy=await y();'
    'if(null===HKy)return void console.log("[hektCaptcha][recaptcha][flow] y() returned no new challenge; returning so the driver loop can retry");'
    "const{task:g,is_hard:m,cells:b,background_url:S,urls:A}=HKy,O=[],k=9==b.length?3:4;",
)


def main():
    check_only = "--check" in sys.argv
    src = open(PATH, encoding="utf-8").read()
    print(f"{PATH}: {len(src)} chars")

    out = src
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            print(f"  FAIL  {name}: expected exactly 1 occurrence, found {n}")
            if src.count(new) == 1:
                print(f"        (replacement already present -- already patched?)")
            sys.exit(1)
        out = out.replace(old, new, 1)
        print(f"  ok    {name}  ({len(old)} -> {len(new)} chars)")

    if check_only:
        print("check-only: not writing")
        return

    bak = PATH + ".prepatch.bak"
    if not os.path.exists(bak):
        shutil.copyfile(PATH, bak)
        print(f"backup -> {bak}")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"written: {len(src)} -> {len(out)} chars (+{len(out)-len(src)})")


main()
