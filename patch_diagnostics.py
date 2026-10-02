#!/usr/bin/env python3
"""TEMPORARY, OBSERVATION-ONLY instrumentation for hekt2/recaptcha.js.

Applied on top of patch_recaptcha.py's output. Adds logging ONLY -- no guard is
relaxed, no click is introduced or suppressed, and no solving behaviour is
touched. Specifically:

  * A()        -- logs entry and which early-return fired, with button state
  * y()        -- no longer instrumented here: the fixed y() in
                  patch_recaptcha.py carries its own block-reason logging
  * v() / _()  -- logs the button actually clicked, and its label
  * decide     -- logs the submit decision at the end of A()
  * window     -- an "unhandledrejection" listener, purely passive

NOT FOR COMMIT. Revert with:
    git show d6078b1:hekt2/recaptcha.js > hekt2/recaptcha.js && python3 patch_recaptcha.py
"""
import os
import shutil
import sys

PATH = "hekt2/recaptcha.js"
PATCHES = []


def patch(name, old, new):
    PATCHES.append((name, old, new))


# --------------------------------------------------------------- sequence counter
patch(
    "diag: module-scope counters",
    "let O=!1,I=!1,P=[],HK_HELD=!1,HK_CLS_DOWN=!1;for(;;){",
    "let O=!1,I=!1,P=[],HK_HELD=!1,HK_CLS_DOWN=!1,HK_SEQ=0;for(;;){",
)

# --------------------------------------------------------------- passive rejection probe
# Proves whether an async rejection is escaping into nowhere (which is exactly
# what happens when m() throws inside y()'s setInterval callback).
patch(
    "diag: unhandledrejection listener",
    '(async()=>{function u(){return null!==document.querySelector(".recaptcha-checkbox")}',
    '(async()=>{try{addEventListener("unhandledrejection",'
    'ev=>console.error("[hektCaptcha][recaptcha][unhandled] "'
    '+(ev.reason&&(ev.reason.stack||ev.reason.message)||String(ev.reason))))}catch(_e){}'
    'function u(){return null!==document.querySelector(".recaptcha-checkbox")}',
)

# --------------------------------------------------------------- A() flow trace
# Note: module-level `b` cannot be referenced here -- `cells:b` in the
# destructuring below puts `b` in TDZ for the whole function body.
patch(
    "diag: A() entry + early-return reasons",
    'async function A(u){const l=undefined;'
    'if(!0!==(await n.get({key:"recaptcha_image_visible",tab_specific:!0})).value)return;'
    'if(d()||f()||h())return;'
    'if(!I&&w()?(P=[],I=!0):I=!1,x())return P=[],_();'
    'const c=undefined;'
    'if(!await p())return;',
    'async function A(u){const l=undefined;'
    'const HKD=()=>{const q=document.querySelector("#recaptcha-verify-button");return{'
    'btn:q?(q.innerText||"").trim():null,btnDisabled:q?!!q.disabled:null,'
    'tiles:document.querySelectorAll(".rc-imageselect-tile").length,'
    'sel:document.querySelectorAll(".rc-imageselect-tileselected").length,'
    'dyn:document.querySelectorAll(".rc-imageselect-dynamic-selected").length,'
    'instrLines:(document.querySelector(".rc-imageselect-instructions")?.innerText??"@@MISSING@@").split("\\n").length,'
    'd:d(),doscaptcha:f(),anchorErr:h(),incorrect:w(),selectMore:x()}};'
    'const HKL=(s,x2)=>console.log("[hektCaptcha][recaptcha][flow] "+s+" "+JSON.stringify(Object.assign({seq:HK_SEQ},HKD(),x2||{})));'
    'if(!0!==(await n.get({key:"recaptcha_image_visible",tab_specific:!0})).value)return;'
    'HK_SEQ++;HKL("enter");'
    'if(d()||f()||h())return HKL("exit:verify_disabled_or_doscaptcha_or_anchor_error");'
    'if(!I&&w()?(P=[],I=!0):I=!1,x())return HKL("exit:select_more_error->reload"),P=[],_();'
    'const c=undefined;'
    'if(!await p())return HKL("exit:p()_timeout_tiles_never_settled");'
    'HKL("awaiting_y");',
)

# --------------------------------------------------- per-candidate detection trace
# Logs each detection the existing code already produced, and the per-cell
# mask-coverage ratios it already computed, plus which cells its existing
# `>.1` test accepted. The comparison itself is untouched -- `q>.1&&(D[t]=!0)`
# is the original `S[...]/y>.1&&(D[t]=!0)`.
patch(
    "diag: per-candidate keep/discard",
    "const HK_CLS=j[l.indexOf(c)];HK_SEEN.push(HK_CLS);if(HK_CLS!==R)continue;HK_PASS++;",
    'const HK_CLS=j[l.indexOf(c)];HK_SEEN.push(HK_CLS);'
    'if(HK_CLS!==R){console.log("[hektCaptcha][recaptcha][cand] #"+n+" class="+HK_CLS'
    '+" score="+c.toFixed(3)+" DISCARDED reason=class_mismatch target="+R);continue}'
    'HK_PASS++;'
    'console.log("[hektCaptcha][recaptcha][cand] #"+n+" class="+HK_CLS'
    '+" score="+c.toFixed(3)+" KEPT target="+R);',
)

patch(
    "diag: per-cell mask coverage",
    "for(let t=0;t<16;t++){const e=undefined;S[Math.floor(t/4)][t%4]/y>.1&&(D[t]=!0)}",
    "const HK_RAT=[];for(let t=0;t<16;t++){const e=undefined;"
    "const q=S[Math.floor(t/4)][t%4]/y;HK_RAT.push(+q.toFixed(4));q>.1&&(D[t]=!0)}"
    'console.log("[hektCaptcha][recaptcha][cells] #"+n+" class="+HK_CLS'
    '+" ratios="+JSON.stringify(HK_RAT)'
    '+" accepted="+JSON.stringify(HK_RAT.map((z,i2)=>z>.1?i2:-1).filter(z=>z>=0))'
    '+" discarded_below_threshold="+JSON.stringify(HK_RAT.map((z,i2)=>(z>0&&z<=.1)?(i2+"@"+z):null).filter(Boolean)));',
)

# --------------------------------------------------------------- click trace
patch(
    "diag: log the button actually clicked",
    'function v(){a(document.querySelector("#recaptcha-verify-button"))}'
    'function _(){a(document.querySelector("#recaptcha-reload-button"))}',
    'function v(){const q=document.querySelector("#recaptcha-verify-button");'
    'const im=document.querySelector("table tr td img");'
    'const cid=((im&&im.src)||"").match(/[?&]p=([^&]{0,12})/);'
    'console.log("[hektCaptcha][recaptcha][click] submit button label="+JSON.stringify(q?(q.innerText||"").trim():null)'
    '+" disabled="+(q?!!q.disabled:null)'
    '+" tiles="+document.querySelectorAll(".rc-imageselect-tile").length'
    '+" sel="+document.querySelectorAll(".rc-imageselect-tileselected").length'
    '+" challenge="+JSON.stringify(cid?cid[1]:null)'
    '+" wall="+Date.now());a(q)}'
    'function _(){console.log("[hektCaptcha][recaptcha][click] reload button");'
    'a(document.querySelector("#recaptcha-reload-button"))}',
)

# --------------------------------------------------------------- submit decision
patch(
    "diag: submit decision at end of A()",
    "return await e.sleep(u.recaptcha_solve_delay_time),3===k&&m&&0===$&&await p()||3===k&&!m||4===k?(await e.sleep(200),v()):void 0",
    'return await e.sleep(u.recaptcha_solve_delay_time),'
    'console.log("[hektCaptcha][recaptcha][flow] decide_submit "+JSON.stringify({grid:k+"x"+k,is_hard:m,tiles_clicked:$})),'
    "3===k&&m&&0===$&&await p()||3===k&&!m||4===k?(await e.sleep(200),v()):void 0",
)


def main():
    check = "--check" in sys.argv
    src = open(PATH, encoding="utf-8").read()
    print(f"{PATH}: {len(src)} chars")
    out = src
    for name, old, new in PATCHES:
        c = out.count(old)
        if c != 1:
            print(f"  FAIL  {name}: expected 1 occurrence, found {c}")
            sys.exit(1)
        out = out.replace(old, new, 1)
        print(f"  ok    {name}")
    if check:
        print("check-only")
        return
    bak = PATH + ".nodiag.bak"
    if not os.path.exists(bak):
        shutil.copyfile(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"written: {len(src)} -> {len(out)} (+{len(out)-len(src)})")


main()
