#!/usr/bin/env python3
"""ewai_record.py — record a screen-recording beat from a JSON shot plan.

Three capture modes (pick per shot with "mode"):
  browser  Frame-stepped capture of a signed-in Chrome window over CDP. Every frame is
           placed exactly (cursor, scroll, typing) and screenshotted, so motion is smooth
           and the result is deterministic. Best for any website / web app.
  mac      Real-time capture of a native app window (Finder, Terminal, an editor) with
           macOS `screencapture -v`, driven by AppleScript (osascript) and CoreGraphics mouse events.
           Needs Accessibility.
  screen   Real-time capture of a screen region holding the recording Chrome AND native apps side by
           side or one after the other (PowerPoint next to a web page; a claude.ai chat, then Numbers).
           Chrome is driven over CDP (drawn cursor), apps through their own AppleScript (no System
           Events), so it needs no Accessibility. Windows are placed by the plan.

Usage:
  python3 ewai_record.py --preflight [--apps "Numbers,Microsoft PowerPoint"] [--sites URL,URL] [plan.json …]
                                              # one checklist of everything Sam must do before recording
  python3 ewai_record.py --session start      # remember what is open before recording
  python3 ewai_record.py plan.json            # record
  python3 ewai_record.py plan.json --check    # resolve every target, record nothing
  python3 ewai_record.py --sheet clip.mp4 out.png   # contact sheet for review
  python3 ewai_record.py --promote <dir>/NN_name_take2_4k30.mp4   # make a take the clip; delete older takes
  python3 ewai_record.py --index <yt_screen_recordings_vN>        # write index.md (beat -> clip)
  python3 ewai_record.py --session end        # close what the recordings opened, delete helper files
  python3 ewai_record.py --sfx clip.events.json --clip-id ID --layout-start-ms N --duration-ms N [--in-point-ms N]
                                              # Tella add_sound_effect operations for apply_video_edits

Every recording also writes <output>.events.json next to the clip: the time (ms into the clip)
of each click, keystroke run, key press and page load. ewai-edit-video uses it to add matching UI
sounds in Tella, since the clips themselves are silent.

Exit codes: 0 ok · 2 bad plan · 3 sign-in required · 4 blocked action · 5 macOS permission missing
            6 an app didn't answer AppleScript (a permission prompt or first-run window is open in it)
See ../references/screen-recording.md for the plan format and rules.
"""
import asyncio, json, math, os, re, shutil, signal, subprocess, sys, time, urllib.request
from pathlib import Path

FPS = 30
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_PROFILE = str(Path.home() / ".cache/ewai-studio-capture-profile")
DEFAULT_PORT = 9333
# Clicking anything whose text/label matches this is refused: recordings never change data.
RISKY = re.compile(r"\b(save|publish|delete|remove|submit|upload|send|confirm|done|post|"
                   r"discard|apply|buy|pay|purchase|sign out|log out|make public|schedule)\b", re.I)

CURSOR_JS = r"""
(() => {
  if (window.__fakeCursor && document.documentElement.contains(window.__fakeCursor)) return;
  const c = document.createElement('div');
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', '26'); svg.setAttribute('height', '34'); svg.setAttribute('viewBox', '0 0 26 34');
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', 'M2 2 L2 27 L8.5 21 L13 31.5 L17.5 29.5 L13 19.5 L22 19.5 Z');
  path.setAttribute('fill', '#111'); path.setAttribute('stroke', '#fff');
  path.setAttribute('stroke-width', '2'); path.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(path); c.appendChild(svg);
  Object.assign(c.style, {position:'fixed', left:'0', top:'0', zIndex:'2147483647', pointerEvents:'none',
    transform:'translate(-200px,-200px)', filter:'drop-shadow(0 2px 3px rgba(0,0,0,.35))'});
  document.documentElement.appendChild(c);
  window.__fakeCursor = c;
  window.__setCursor = (x, y) => { c.style.transform = `translate(${x-2}px,${y-2}px)`; };
})();
"""

MASK_JS = r"""
([blur, hide]) => {
  let s = document.getElementById('__ewaiMask');
  if (!s) { s = document.createElement('style'); s.id = '__ewaiMask'; document.documentElement.appendChild(s); }
  s.textContent = blur.map(q => `${q}{filter:blur(14px)!important}`).join('\n') + '\n' +
                  hide.map(q => `${q}{visibility:hidden!important}`).join('\n');
}
"""

# Privacy defaults per site, applied without being asked. blur = unreadable, hide = invisible.
SITE_PRIVACY = {
    "claude.ai": {"hide": ["button[aria-label$=', Connected']"],         # connected computer's name
                  "collapse_sidebar": "button[aria-label='Hide sidebar']"},  # sidebar lists other chats
}

SESSION = Path.home() / ".cache/ewai-recorder/session.json"


def session_note(**kw):
    """Record, for `--session end`, what a recording opened or created. No session → no-op."""
    if not SESSION.exists():
        return
    s = json.loads(SESSION.read_text())
    for k, v in kw.items():
        lst = s.setdefault(k, [])
        for x in (v if isinstance(v, list) else [v]):
            if x not in lst:
                lst.append(x)
    SESSION.write_text(json.dumps(s, indent=1))


def main_display():
    """Main display size in points (the display with the menu bar)."""
    import ctypes
    cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")

    class R(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]
    cg.CGDisplayBounds.restype = R
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    r = cg.CGDisplayBounds(cg.CGMainDisplayID())
    return int(r.w), int(r.h)


def finish_capture(raw, out, start_s, length_s):
    """screencapture -v writes variable frame rate and stops at the last frame that changed, so a still
    ending comes out short. Clone the last frame out to the planned length."""
    # (-ss/-t on a VFR capture come out short; trim inside the filter graph is exact)
    vf = (f"fps=30,tpad=stop_mode=clone:stop_duration={length_s + start_s + 60:.1f},"
          f"trim=start={start_s:.2f}:duration={length_s:.2f},setpts=PTS-STARTPTS,scale=3840:2160:flags=lanczos")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-vf", vf,
                    "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
                    "-profile:v", "high", "-movflags", "+faststart", "-an", out], check=True)


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (t * 6 - 15) + 10)


def die(code, msg):
    print(f"ERROR[{code}]: {msg}", file=sys.stderr)
    sys.exit(code)


def ffmpeg_writer(out, src_size=None):
    vf = "scale=3840:2160:flags=lanczos:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2:color=white"
    return ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
            "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-movflags", "+faststart", "-an", "-r", str(FPS), out]


# --------------------------------------------------------------------------- browser
class Browser:
    def __init__(self, plan, check):
        self.plan, self.check = plan, check
        b = plan.get("browser", {})
        self.port = b.get("port", DEFAULT_PORT)
        self.profile = os.path.expanduser(b.get("profile", DEFAULT_PROFILE))
        self.vw, self.vh = b.get("viewport", [1600, 900])
        self.dsf = b.get("scale", 3840 / self.vw)
        self.cur = [self.vw * 0.62, self.vh * 0.62]
        self.frames = 0
        self.ff = None
        self.events = []
        self.blur, self.hide = list(plan.get("mask", [])), list(plan.get("hide", []))
        self.site = next((v for k, v in SITE_PRIVACY.items() if k in b.get("url", "")), {})
        self.hide += self.site.get("hide", [])

    def ev(self, kind, **kw):
        # time = the frame the result first appears in (actions land between frames)
        self.events.append({"t_ms": round(self.frames * 1000 / FPS), "kind": kind, **kw})

    def ensure_chrome(self):
        ensure_chrome(self.port, self.profile)

    # ---- targets
    def loc(self, t):
        pg = self.pg
        scope = pg.locator(t["within"]).first if t.get("within") else pg
        if "selector" in t:
            return scope.locator(t["selector"]).first
        if "text" in t:
            return scope.get_by_text(t["text"], exact=t.get("exact", True)).first
        if "role" in t:
            return scope.get_by_role(t["role"], name=t.get("name")).first
        if "label" in t:
            return scope.get_by_label(t["label"]).first
        die(2, f"target needs selector/text/role/label or x,y: {t}")

    async def point(self, t):
        if "x" in t and "y" in t:
            return [float(t["x"]), float(t["y"])]
        bb = await self.loc(t).bounding_box(timeout=15000)
        if not bb:
            die(2, f"target not visible: {t}")
        return [bb["x"] + bb["width"] * t.get("fx", 0.5) + t.get("dx", 0),
                bb["y"] + bb["height"] * t.get("fy", 0.5) + t.get("dy", 0)]

    async def scroller(self, value=None, sel=None, axis="y"):
        sel = sel or self.plan.get("browser", {}).get("scroller")
        prop = "scrollLeft" if axis == "x" else "scrollTop"
        js = """([sel, v, prop]) => { const m = (sel && document.querySelector(sel)) || document.scrollingElement;
                  if (v !== null) m[prop] = v; return m[prop]; }"""
        return await self.pg.evaluate(js, [sel, value, prop])

    # ---- frames
    async def frame(self):
        if self.check:
            return
        await self.pg.evaluate(CURSOR_JS)
        if self.blur or self.hide:
            await self.pg.evaluate(MASK_JS, [self.blur, self.hide])
        await self.pg.evaluate("([x,y]) => window.__setCursor(x,y)", self.cur)
        await self.pg.mouse.move(*self.cur)
        self.ff.stdin.write(await self.pg.screenshot(type="png"))
        await self.ff.stdin.drain()
        self.frames += 1

    async def frames_for(self, s):
        for _ in range(round(s * FPS)):
            await self.frame()

    # ---- steps
    async def step(self, st):
        do = st["do"]
        if do == "hold":
            await self.frames_for(st.get("s", 1.0))
        elif do == "move":
            for wp in st.get("via", []):
                await self.glide(await self.point(wp), st.get("via_s", 0.5))
            await self.glide(await self.point(st["to"]), st.get("s", 0.9))
        elif do == "scroll":
            ssel, axis = st.get("scroller"), st.get("axis", "y")
            if "to_px" in st:                       # absolute position, either axis, any scrolling element
                p0 = await self.scroller(None, ssel, axis)
                n = max(1, round(st.get("s", 1.6) * FPS))
                for i in range(1, n + 1):
                    await self.scroller(p0 + (st["to_px"] - p0) * smooth(i / n), ssel, axis)
                    await self.frame()
                return
            y0 = await self.scroller()
            if st.get("top"):
                dy = -y0
            elif "by" in st:
                dy = st["by"]
            else:
                bb = await self.loc(st["to"]).bounding_box(timeout=15000)
                dy = bb["y"] - st.get("offset", 200)
            n = max(1, round(st.get("s", 1.6) * FPS))
            for i in range(1, n + 1):
                await self.scroller(y0 + dy * smooth(i / n))
                await self.frame()
        elif do == "click":
            if "to" in st:
                await self.glide(await self.point(st["to"]), st.get("s", 0.8))
            label = await self.pg.evaluate(
                "([x,y]) => { const e = document.elementFromPoint(x,y); if (!e) return '';"
                " const b = e.closest('button,a,[role=button],[role=link],[role=tab],[role=menuitem],[role=radio],tp-yt-paper-radio-button') || e;"
                " return ((b.getAttribute('aria-label')||'') + ' ' + (b.innerText||'')).slice(0,200); }", self.cur)
            if RISKY.search(label) and not st.get("reviewed_safe"):
                die(4, f"refusing to click '{label.strip()[:80]}' — recordings never change data")
            # (clicks also run in --check so later targets, e.g. inside a dialog, can be resolved)
            await self.pg.mouse.click(*self.cur)
            self.ev("click", label=" ".join(label.split())[:60], sound=st.get("sound"))
            if st.get("wait_for"):
                await self.pg.locator(st["wait_for"]).first.wait_for(timeout=20000)
            await self.pg.wait_for_timeout(st.get("settle_ms", 2000))
        elif do == "type":
            if "to" in st:
                await self.glide(await self.point(st["to"]), st.get("s", 0.8))
                if not self.check:
                    await self.pg.mouse.click(*self.cur)
            per = max(1, round(FPS / st.get("cps", 14)))
            self.ev("type", duration_ms=round(len(st["text"]) * per * 1000 / FPS), chars=len(st["text"]),
                    sound=st.get("sound"))
            for ch in st["text"]:
                if not self.check:
                    await self.pg.keyboard.type(ch)
                for _ in range(per):
                    await self.frame()
        elif do == "key":
            await self.pg.keyboard.press(st["key"])
            self.ev("key", key=st["key"], sound=st.get("sound"))
            await self.pg.wait_for_timeout(st.get("settle_ms", 800))
        elif do == "goto":
            await self.goto(st["url"], st.get("wait_for"), st.get("settle_ms", 4000))
            self.ev("page_load", url=st["url"][:120], sound=st.get("sound"))
        elif do == "select":                         # <select> dropdown: glide to it, pick a value
            await self.glide(await self.point(st["to"]), st.get("s", 0.8))
            if not self.check:                       # "value": "s01" | {"index": 3} | {"label": "Season 1"}
                v = st["value"]
                await self.loc(st["to"]).select_option(**(v if isinstance(v, dict) else {"value": v}))
            self.ev("click", label="select " + str(st["value"]), sound=st.get("sound"))
            await self.pg.wait_for_timeout(st.get("settle_ms", 300))
        elif do == "offline":                        # show a page still working with no network
            await self.pg.context.set_offline(bool(st.get("on", True)))
        elif do == "upload":                         # attach a local file (claude.ai, upload forms)
            if not self.plan.get("allow_send"):
                die(4, "upload needs \"allow_send\": true in the plan (only for results Claude builds itself)")
            if "to" in st:
                await self.glide(await self.point(st["to"]), st.get("s", 0.8))
            if not self.check:
                await self.pg.locator(st.get("input", "input[type=file]")).first.set_input_files(st["files"])
            self.ev("click", label="attach", sound=st.get("sound"))
            await self.frames_for(st.get("settle_s", 2.5))
        elif do == "send_prompt":                    # type a prompt into a chat box, send it, wait for the answer
            if not self.plan.get("allow_send"):
                die(4, "send_prompt needs \"allow_send\": true in the plan (only for results Claude builds itself)")
            box = st.get("box", {"selector": "div[contenteditable=true]"})
            await self.glide(await self.point(box), st.get("s", 0.8))
            if not self.check:
                await self.pg.mouse.click(*self.cur)
            await self.step({"do": "type", "text": st["text"], "cps": st.get("cps", 40), "sound": st.get("sound")})
            if self.check:
                return
            await self.pg.keyboard.press(st.get("submit_key", "Enter"))
            self.ev("key", key="send", sound=st.get("sound"))
            await self.frames_for(st.get("show_s", 2.0))   # the answer starting
            await self.wait_answer(st)                    # not filmed: a cut to the finished answer
            await self.frames_for(0.3)
        elif do == "wait_answer":
            await self.wait_answer(st)
        else:
            die(2, f"unknown browser step: {do}")

    async def wait_answer(self, st):
        """Wait (without recording frames) until a streaming answer is finished: no stop button and the
        text unchanged for stable_s."""
        if self.check:
            return
        busy = st.get("busy", "button[aria-label*='Stop' i]")
        end, last, same = time.time() + st.get("timeout_s", 600), -1, 0.0
        while time.time() < end:
            await self.pg.wait_for_timeout(1000)
            n = await self.pg.evaluate("document.body.innerText.length")
            same = same + 1 if n == last else 0
            last = n
            if not await self.pg.locator(busy).count() and same >= st.get("stable_s", 4):
                return
        die(2, "the answer did not finish in time")

    async def glide(self, target, s):
        x0, y0 = self.cur
        tx, ty = target
        n = max(1, round(s * FPS))
        for i in range(1, n + 1):
            u = smooth(i / n)
            arc = math.sin(math.pi * u) * min(16, 0.08 * math.hypot(tx - x0, ty - y0))
            self.cur = [x0 + (tx - x0) * u, y0 + (ty - y0) * u - arc]
            await self.frame()
        self.cur = [tx, ty]

    async def goto(self, url, wait_for=None, settle_ms=4000):
        await self.pg.goto(url, wait_until="domcontentloaded")
        await self.pg.wait_for_timeout(1500)
        if "accounts.google.com" in self.pg.url or "/signin" in self.pg.url or "login" in self.pg.url.lower():
            die(3, f"sign-in required: ask Sam to sign in in the recording Chrome window ({self.pg.url[:80]})")
        if wait_for:
            await self.pg.locator(wait_for).first.wait_for(timeout=30000)
        await self.pg.wait_for_timeout(settle_ms)
        await self.scroller(0)

    async def run(self):
        from playwright.async_api import async_playwright
        self.ensure_chrome()
        async with async_playwright() as p:
            br = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
            ctx = br.contexts[0]
            # Each recording works in its own tab and closes it afterwards ("keep_tab": true to leave it).
            self.pg = await ctx.new_page()
            await self.pg.bring_to_front()
            cdp = await ctx.new_cdp_session(self.pg)
            await cdp.send("Emulation.setDeviceMetricsOverride",
                           {"width": self.vw, "height": self.vh, "deviceScaleFactor": self.dsf, "mobile": False})
            b = self.plan["browser"]
            await self.goto(b["url"], b.get("wait_for"), b.get("settle_ms", 5000))
            sb = self.site.get("collapse_sidebar")
            if sb and await self.pg.locator(sb).count():
                await self.pg.locator(sb).first.click()
                await self.pg.wait_for_timeout(600)
            if not self.check:
                self.ff = await asyncio.create_subprocess_exec(*ffmpeg_writer(self.plan["output"]),
                                                               stdin=asyncio.subprocess.PIPE)
            try:
                for st in self.plan["steps"]:
                    await self.step(st)
            finally:
                if self.ff:
                    self.ff.stdin.close()
                    await self.ff.wait()
                # leave the page as found: close dialogs, remove overrides
                try:
                    await self.pg.keyboard.press("Escape")
                    await self.pg.evaluate("() => { const c = window.__fakeCursor; if (c) c.remove();"
                                           " const m = document.getElementById('__ewaiMask'); if (m) m.remove(); }")
                    for chk in self.plan.get("after_check", []):
                        txt = await self.loc(chk["target"]).inner_text(timeout=5000)
                        ok = chk["expect"].lower() in txt.lower()
                        print(f"after-check {'OK' if ok else 'FAILED'}: expected '{chk['expect']}' in '{txt.strip()[:80]}'")
                except Exception as e:
                    print("after-check skipped:", str(e)[:120])
                try:
                    await self.pg.context.set_offline(False)
                    await cdp.send("Emulation.clearDeviceMetricsOverride")
                except Exception:
                    pass
                if self.plan.get("keep_tab"):
                    session_note(tabs=[self.pg.url])
                else:
                    await self.pg.close()
        if not self.check:
            write_events(self.plan, self.events, self.frames * 1000 / FPS)
        print(f"{'checked' if self.check else 'recorded'} {self.frames} frames ({self.frames / FPS:.1f}s)"
              + ("" if self.check else f" -> {self.plan['output']}"))


def write_events(plan, events, length_ms):
    out = Path(plan["output"]).with_suffix(".events.json")
    out.write_text(json.dumps({"clip": Path(plan["output"]).name, "length_ms": int(length_ms),
                               "events": events}, indent=1))
    session_note(outputs=[str(Path(plan["output"]).resolve())])
    print(f"events: {len(events)} -> {out}")


# --------------------------------------------------------------------------- mac
def ensure_chrome(port=DEFAULT_PORT, profile=DEFAULT_PROFILE):
    """Start the recording Chrome if needed. CDP refuses to attach to a Chrome with no window open
    ("Browser context management is not supported"), so make sure there is at least one tab."""
    url = f"http://127.0.0.1:{port}"
    try:
        urllib.request.urlopen(url + "/json/version", timeout=2)
    except Exception:
        if not Path(CHROME).exists():
            die(2, "Google Chrome is not installed")
        subprocess.Popen([CHROME, f"--user-data-dir={os.path.expanduser(profile)}", f"--remote-debugging-port={port}",
                          "--no-first-run", "--no-default-browser-check", "--window-size=1920,1180", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        session_note(launched=["recording-chrome"])
        for _ in range(40):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(url + "/json/version", timeout=2)
                break
            except Exception:
                pass
        else:
            die(2, "Chrome did not open its debugging port")
    pages = [t for t in json.loads(urllib.request.urlopen(url + "/json/list", timeout=3).read()) if t["type"] == "page"]
    if not pages:
        urllib.request.urlopen(urllib.request.Request(url + "/json/new?about:blank", method="PUT"), timeout=5)


def chrome_targets(port=DEFAULT_PORT):
    try:
        return [t for t in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3).read())
                if t["type"] == "page"]
    except Exception:
        return None


def osa(script, timeout=20, fatal=True):
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        app = re.search(r'application "([^"]+)"', script)
        if not fatal:
            return None
        die(6, f"{app.group(1) if app else 'the app'} didn't answer AppleScript: a macOS 'wants to control' "
               "prompt or a first-run/welcome window is open. Ask Sam to answer it, then retry")
    if r.returncode != 0:
        if not fatal:
            return None
        if "-1743" in r.stderr or "Not authorized" in r.stderr:
            die(5, "Automation permission denied for this app (System Settings → Privacy & Security → Automation)")
        if "not allowed" in r.stderr or "1002" in r.stderr or "assistive" in r.stderr:
            die(5, "Accessibility permission missing for the app running Claude "
                   "(System Settings → Privacy & Security → Accessibility)")
        die(2, f"osascript failed: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def app_running(app):
    return subprocess.run(["pgrep", "-xq", app], capture_output=True).returncode == 0 or \
        (osa(f'application "{app}" is running', timeout=5, fatal=False) == "true")


def app_documents(app):
    out = osa(f'tell application "{app}" to get name of every document', timeout=8, fatal=False)
    return [d.strip() for d in out.split(",")] if out else []


MAC_LEAD = 0.1


class Mac:
    def __init__(self, plan, check):
        self.plan, self.check = plan, check
        m = plan.get("mac", {})
        self.app = m.get("app", "Terminal")
        self.region = m.get("region", [0, 25, 1920, 1080])      # points; 1920x1080 pt = 3840x2160 px on Retina
        self.cur = None
        self.t0 = None
        self.events = []

    def ev(self, kind, **kw):
        if self.t0 is None:              # setup/teardown: not in the clip
            return
        # output starts ~0.1 s before t0 (1.2 s spin-up, 1.0 s trimmed, minus screencapture start latency;
        # measured against the visible change in Finder: within ±70 ms)
        self.events.append({"t_ms": round((time.time() - self.t0 + MAC_LEAD) * 1000), "kind": kind, **kw})

    # Mouse via CoreGraphics (ctypes, no install). cliclick costs ~100 ms per move: too slow for smooth glides.
    _cg = None

    @classmethod
    def cg(cls):
        if cls._cg is None:
            import ctypes
            cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")

            class P(ctypes.Structure):
                _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
            cg.P = P
            cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
            cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, P, ctypes.c_uint32]
            cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
            cg.CFRelease.argtypes = [ctypes.c_void_p]
            cg.AXIsProcessTrusted.restype = ctypes.c_bool
            cls._cg = cg
        return cls._cg

    def mouse(self, kind, x, y):
        cg = self.cg()                       # kind: 5 move, 1 left down, 2 left up
        e = cg.CGEventCreateMouseEvent(None, kind, cg.P(x, y), 0)
        cg.CGEventPost(0, e)
        cg.CFRelease(e)

    def to_screen(self, t):
        x, y, _, _ = self.region
        if t.get("abs"):
            return [t["x"], t["y"]]
        return [x + t["x"], y + t["y"]]

    def glide(self, target, s):
        if self.cur is None:
            self.cur = [self.region[0] + self.region[2] * 0.6, self.region[1] + self.region[3] * 0.6]
            self.mouse(5, *self.cur)
        x0, y0 = self.cur
        tx, ty = target
        n = max(1, round(s * 60))
        t0 = time.time()
        for i in range(1, n + 1):
            u = smooth(i / n)
            self.mouse(5, x0 + (tx - x0) * u, y0 + (ty - y0) * u)
            time.sleep(max(0, t0 + s * i / n - time.time()))      # deadline-paced: total stays s
        self.cur = [tx, ty]

    def step(self, st):
        do = st["do"]
        if do == "hold":
            time.sleep(st.get("s", 1.0))
        elif do == "move":
            self.glide(self.to_screen(st["to"]), st.get("s", 0.9))
        elif do == "click":
            if "to" in st:
                self.glide(self.to_screen(st["to"]), st.get("s", 0.8))
            if self.cur is None:
                die(2, "mac click needs a 'to' (or a move before it)")
            self.mouse(1, *self.cur); self.ev("click", sound=st.get("sound")); time.sleep(0.05); self.mouse(2, *self.cur)
            time.sleep(st.get("settle_ms", 800) / 1000)
        elif do == "type":
            delay = 1.0 / st.get("cps", 14)
            t_type = time.time()
            for ch in st["text"]:
                esc = ch.replace("\\", "\\\\").replace('"', '\\"')
                osa(f'tell application "System Events" to keystroke "{esc}"')
                time.sleep(delay)
            if self.t0 is not None:
                self.events.append({"t_ms": round((t_type - self.t0 + MAC_LEAD) * 1000), "kind": "type",
                                    "duration_ms": round((time.time() - t_type) * 1000), "chars": len(st["text"]),
                                    "sound": st.get("sound")})
            if st.get("enter"):
                osa('tell application "System Events" to key code 36')
                self.ev("key", key="return", sound=st.get("sound"))
        elif do == "key":
            osa(f'tell application "System Events" to {st["key"]}')   # e.g. key code 36 / keystroke "k" using command down
            self.ev("key", key=st["key"][:40], sound=st.get("sound"))
        elif do == "osascript":
            osa(st["script"])
        elif do == "wait_for_text":
            # Terminal only: wait until the front window's contents contain text (real command output)
            end = time.time() + st.get("timeout", 60)
            while time.time() < end:
                txt = osa('tell application "Terminal" to get contents of selected tab of front window')
                if st["text"] in txt:
                    self.ev("output", text=st["text"][:60], sound=st.get("sound"))
                    break
                time.sleep(0.25)
            time.sleep(st.get("then_hold", 0))
        else:
            die(2, f"unknown mac step: {do}")

    @staticmethod
    def estimate(st):
        do = st["do"]
        if do in ("hold", "move"):
            return st.get("s", 1.0 if do == "hold" else 0.9)
        if do == "click":
            return (st.get("s", 0.8) if "to" in st else 0) + st.get("settle_ms", 800) / 1000 + 0.1
        if do == "type":
            return len(st["text"]) * (1.0 / st.get("cps", 14) + 0.08) + (0.2 if st.get("enter") else 0)
        if do == "wait_for_text":
            return st.get("expect_s", 3.0) + st.get("then_hold", 0)
        return 0.3

    def frame_window(self):
        x, y, w, h = self.region
        session_note(apps=[self.app])
        osa(f'tell application "{self.app}" to activate')
        osa(f'tell application "{self.app}" to set bounds of front window to {{{x}, {y}, {x + w}, {y + h}}}')
        time.sleep(0.8)

    def run(self):
        if not self.cg().AXIsProcessTrusted():
            die(5, "Accessibility permission missing for the process running Claude. In the desktop app that is "
                   "Claude Code's own claude.app (~/Library/Application Support/Claude/claude-code/<version>/<id>/"
                   "claude.app), not /Applications/Claude.app: add it in System Settings → Privacy & Security → "
                   "Accessibility, then retry")
        for st in self.plan.get("setup", []):          # unrecorded prep (open folder, cd, clear, etc.)
            self.step(st)
        self.frame_window()
        if self.check:
            x, y, w, h = self.region
            still = str(Path(self.plan["output"]).with_suffix(".check.png"))
            subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", still])
            session_note(paths=[still])
            print("mac setup ok; region", self.region, "| still of the region:", still,
                  "| step x/y in points = still pixels / 2 (Retina)")
            return
        x, y, w, h = self.region
        raw = str(Path(self.plan["output"]).with_suffix(".raw.mov"))
        # screencapture only writes the file when its -V timer runs out (SIGINT/SIGTERM discard it),
        # so size the timer from the plan and let it finish on its own.
        est = sum(self.estimate(st) for st in self.plan["steps"])
        total = math.ceil(1.2 + est + self.plan.get("mac", {}).get("tail_margin", 3.0))
        cap = subprocess.Popen(["screencapture", "-x", "-v", "-V", str(total), "-R", f"{x},{y},{w},{h}", raw])
        time.sleep(1.2)                                  # capture spin-up; trimmed below
        t_start = self.t0 = time.time()
        try:
            for st in self.plan["steps"]:
                self.step(st)
        finally:
            dur = time.time() - t_start
            cap.wait(timeout=total + 30)
            self.t0 = None
            for st in self.plan.get("teardown", []):     # close what setup opened; never fatal
                try:
                    self.step(st)
                except SystemExit:
                    print("warning: teardown step failed:", st)
        if 1.2 + dur > total:
            print(f"warning: steps ran {dur:.1f}s, longer than the {total - 1.2:.1f}s capture; the end is cut. "
                  "Raise mac.tail_margin (e.g. for slow wait_for_text).")
        if not Path(raw).exists():
            die(5, "screencapture produced no file: grant Screen Recording to the app running Claude")
        finish_capture(raw, self.plan["output"], 1.0, dur + 0.2)
        os.remove(raw)
        write_events(self.plan, self.events, (dur + 0.2) * 1000)
        print(f"recorded {dur:.1f}s -> {self.plan['output']}")


# --------------------------------------------------------------------------- screen (Chrome + apps, real time)
def chrome_pid(port=DEFAULT_PORT):
    r = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)
    return int(r.stdout.split()[0]) if r.stdout.strip() else None


def activate_pid(pid):
    """Bring one app instance to the front by PID. JXA/AppKit needs no Accessibility, and it picks the
    recording Chrome even when Sam's own Chrome (same bundle id) is running."""
    subprocess.run(["osascript", "-l", "JavaScript", "-e",
                    f"ObjC.import('AppKit'); $.NSRunningApplication.runningApplicationWithProcessIdentifier({pid})"
                    ".activateWithOptions(2)"], capture_output=True, timeout=10)


def auto_region():
    w, h = main_display()
    if w < 1920 or h < 1110:
        die(2, f"main display is {w}x{h} points; a 1920x1080 region needs a larger main display")
    return [0 if w < 2100 else 100, min(150, h - 1085), 1920, 1080]


class Screen:
    """Real-time capture of a fixed region holding the recording Chrome and/or native app windows.

    Plan:
      "region": [x, y, 1920, 1080] | "auto"
      "windows": [ {"chrome": {"url": …, "wait_for": …}, "rect": [rx, ry, rw, rh]},
                   {"app": "Numbers", "open": "/path/file.xlsx", "rect": [rx, ry, rw, rh]} ]
         rect is relative to the region. For Chrome it is the page area: the toolbar sits above the
         region, so the URL bar and profile icon are never filmed. For an app it is the whole window.
         Windows are placed in order; the last one ends up in front.
      "steps": hold · front {window} · chrome_move {to, s} · chrome_click {to, s} · chrome_scroll
               {to_px | to + offset, ms, scroller?} · chrome_select {to, value} · osascript {script} ·
               select_cells {app, range, table?}
      "length_s": total clip length (default: steps + 4 s still hold)
    """

    def __init__(self, plan, check):
        self.plan, self.check = plan, check
        r = plan.get("region", "auto")
        self.region = auto_region() if r == "auto" else r
        self.events, self.t0, self.pg, self.cur = [], None, None, None

    def ev(self, kind, **kw):
        if self.t0 is not None:
            self.events.append({"t_ms": round((time.time() - self.t0 + MAC_LEAD) * 1000), "kind": kind, **kw})

    # ---- setup
    def place(self, p):
        x, y, _, _ = self.region
        for w in self.plan.get("windows", []):
            rx, ry, rw, rh = w["rect"]
            if "chrome" in w:
                c = w["chrome"]
                ensure_chrome()
                self.pg = p.chromium.connect_over_cdp(f"http://127.0.0.1:{DEFAULT_PORT}").contexts[0].new_page()
                self.pg.goto(c["url"], wait_until="domcontentloaded")
                if c.get("wait_for"):
                    self.pg.locator(c["wait_for"]).first.wait_for(timeout=30000)
                self.pg.wait_for_timeout(c.get("settle_ms", 3000))
                url = self.pg.url
                if "accounts.google.com" in url or "/signin" in url or "login" in url.lower():
                    die(3, f"sign-in required: ask Sam to sign in in the recording Chrome window ({url[:80]})")
                site = next((v for k, v in SITE_PRIVACY.items() if k in url), {})
                hide = c.get("hide", []) + site.get("hide", [])
                if hide or c.get("mask"):
                    self.pg.evaluate(MASK_JS, [c.get("mask", []), hide])
                sb = site.get("collapse_sidebar")
                if sb and self.pg.locator(sb).count():
                    self.pg.locator(sb).first.click()
                    self.pg.wait_for_timeout(600)
                cdp = self.pg.context.new_cdp_session(self.pg)
                wid = cdp.send("Browser.getWindowForTarget")["windowId"]
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {
                    "left": x + rx, "top": y + ry - 90, "width": rw, "height": rh + 90}})
                self.pg.wait_for_timeout(500)
                bar = self.pg.evaluate("outerHeight - innerHeight")      # real toolbar height
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {
                    "left": x + rx, "top": y + ry - bar, "width": rw, "height": rh + bar}})
                self.pg.bring_to_front()
                activate_pid(chrome_pid())
                self.pg.evaluate(CURSOR_JS)
            else:
                app = w["app"]
                session_note(apps=[app])
                if w.get("open"):
                    subprocess.run(["open", "-a", app, w["open"]], check=True)
                    name = Path(w["open"]).stem
                    for _ in range(30):
                        if any(name in d for d in app_documents(app)):
                            break
                        time.sleep(1)
                    else:
                        die(6, f"{app} did not open {w['open']} (a prompt or welcome window may be in the way)")
                osa(f'tell application "{app}" to activate')
                osa(f'tell application "{app}" to set bounds of front window to '
                    f'{{{x + rx}, {y + ry}, {x + rx + rw}, {y + ry + rh}}}')
            time.sleep(0.8)

    # ---- steps
    def chrome_point(self, t):
        if "x" in t:
            return [float(t["x"]), float(t["y"])]
        loc = (self.pg.locator(t["selector"]) if "selector" in t else
               self.pg.get_by_text(t["text"], exact=t.get("exact", True))).first
        bb = loc.bounding_box(timeout=15000)
        return [bb["x"] + bb["width"] * t.get("fx", 0.5) + t.get("dx", 0),
                bb["y"] + bb["height"] * t.get("fy", 0.5) + t.get("dy", 0)]

    def glide(self, target, s):
        if self.cur is None:
            vw, vh = self.pg.evaluate("[innerWidth, innerHeight]")
            self.cur = [vw * 0.6, vh * 0.75]
        (x0, y0), (tx, ty) = self.cur, target
        n, t0 = max(1, round(s * 60)), time.time()
        for i in range(1, n + 1):
            u = smooth(i / n)
            self.pg.evaluate("([x,y]) => window.__setCursor(x,y)", [x0 + (tx - x0) * u, y0 + (ty - y0) * u])
            time.sleep(max(0, t0 + s * i / n - time.time()))
        self.cur = [tx, ty]

    def step(self, st):
        do = st["do"]
        if do == "hold":
            time.sleep(st.get("s", 1.0))
        elif do == "front":
            if st["window"] == "chrome":
                self.pg.bring_to_front()
                activate_pid(chrome_pid())
            else:
                osa(f'tell application "{st["window"]}" to activate')
            time.sleep(st.get("settle_s", 0.6))
        elif do in ("chrome_move", "chrome_click", "chrome_select"):
            self.glide(self.chrome_point(st["to"]), st.get("s", 1.0))
            if do == "chrome_click":
                label = self.pg.evaluate("([x,y]) => { const e = document.elementFromPoint(x,y); return e ? "
                                         "((e.closest('button,a,[role=button]')||e).innerText||'').slice(0,200) : ''; }",
                                         self.cur)
                if RISKY.search(label) and not st.get("reviewed_safe"):
                    die(4, f"refusing to click '{label.strip()[:80]}' — recordings never change data")
                self.pg.evaluate("window.__fakeCursor.style.scale='.85'")
                self.ev("click", label=" ".join(label.split())[:60], sound=st.get("sound"))
                if not self.check:
                    self.pg.mouse.click(*self.cur)
                time.sleep(0.12)
                self.pg.evaluate("window.__fakeCursor.style.scale='1'")
            elif do == "chrome_select":
                v = st["value"]
                self.pg.locator(st["to"]["selector"]).first.select_option(**(v if isinstance(v, dict) else {"value": v}))
                self.ev("click", label="select " + str(st["value"]), sound=st.get("sound"))
            time.sleep(st.get("settle_ms", 400) / 1000)
        elif do == "chrome_scroll":
            js = """([sel, to, text, off, ms]) => new Promise(r => {
              const sc = (sel && document.querySelector(sel)) || [...document.querySelectorAll('*')]
                .filter(e => e.scrollHeight > e.clientHeight + 200 && /(auto|scroll)/.test(getComputedStyle(e).overflowY))
                .sort((a, b) => b.scrollHeight - a.scrollHeight)[0] || document.scrollingElement;
              if (to === null) { const el = [...document.querySelectorAll('h1,h2,h3,h4,p,td,th,li,strong,span')]
                .find(e => e.textContent.trim().startsWith(text));
                to = el ? sc.scrollTop + el.getBoundingClientRect().top - off : sc.scrollTop; }
              const a = sc.scrollTop, t0 = performance.now();
              const f = n => { let k = Math.min(1, (n - t0) / ms); k = k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2;
                sc.scrollTop = a + (to - a) * k; k < 1 ? requestAnimationFrame(f) : r(); };
              requestAnimationFrame(f); })"""
            self.pg.evaluate(js, [st.get("scroller"), st.get("to_px"), (st.get("to") or {}).get("text"),
                                  st.get("offset", 90), st.get("ms", 2000)])
        elif do == "osascript":
            osa(st["script"])
        elif do == "select_cells":                  # Numbers: select a cell/range (shows its formula)
            app, tb = st.get("app", "Numbers"), st.get("table", 1)
            t = f'table {tb} of active sheet of front document'
            osa(f'tell application "{app}" to set selection range of {t} to range "{st["range"]}" of {t}')
            self.ev("click", label="select " + st["range"], sound=st.get("sound"))
        else:
            die(2, f"unknown screen step: {do}")

    @staticmethod
    def estimate(st):
        return {"hold": st.get("s", 1.0), "front": st.get("settle_s", 0.6) + 0.3,
                "chrome_scroll": st.get("ms", 2000) / 1000}.get(
            st["do"], st.get("s", 1.0) + st.get("settle_ms", 400) / 1000 + 0.3)

    def run(self):
        from playwright.sync_api import sync_playwright
        x, y, w, h = self.region
        with sync_playwright() as p:
            self.place(p)
            if self.check:
                still = str(Path(self.plan["output"]).with_suffix(".check.png"))
                subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", still])
                session_note(paths=[still])
                for st in self.plan["steps"]:          # resolve chrome targets without filming
                    if st["do"] in ("chrome_move", "chrome_click", "chrome_select"):
                        self.chrome_point(st["to"])
                print("screen setup ok; region", self.region, "| still:", still)
                return self.close()
            est = sum(self.estimate(st) for st in self.plan["steps"])
            length = self.plan.get("length_s", est + 4.0)
            total = math.ceil(1.2 + max(est, length) + 2)
            raw = str(Path(self.plan["output"]).with_suffix(".raw.mov"))
            cap = subprocess.Popen(["screencapture", "-x", "-v", "-V", str(total), "-R", f"{x},{y},{w},{h}", raw])
            time.sleep(1.2)
            self.t0 = time.time()
            try:
                for st in self.plan["steps"]:
                    self.step(st)
            finally:
                cap.wait(timeout=total + 30)
                self.t0 = None
                self.close()
            if not Path(raw).exists():
                die(5, "screencapture produced no file: grant Screen Recording to the app running Claude")
            finish_capture(raw, self.plan["output"], 1.0, length)
            os.remove(raw)
            write_events(self.plan, self.events, length * 1000)
            print(f"recorded {length:.1f}s -> {self.plan['output']}")

    def close(self):
        if self.pg is not None:
            try:
                self.pg.evaluate("() => { const c = window.__fakeCursor; if (c) c.remove(); }")
                if not self.plan.get("keep_tab"):
                    self.pg.close()
            except Exception:
                pass


# --------------------------------------------------------------------------- preflight, session, takes, index
def plan_needs(plans):
    apps, sites, mac = set(), set(), False
    for pth in plans:
        pl = json.loads(Path(pth).read_text())
        m = pl.get("mode", "browser")
        if m == "browser":
            sites.add(pl["browser"]["url"])
        elif m == "mac":
            mac = True
            apps.add(pl.get("mac", {}).get("app", "Terminal"))
        else:
            for w in pl.get("windows", []):
                if "chrome" in w:
                    sites.add(w["chrome"]["url"])
                else:
                    apps.add(w["app"])
    return apps, sites, mac


def preflight(argv):
    a = {"--apps": "", "--sites": ""}
    plans = []
    it = iter(argv)
    for x in it:
        if x in a:
            a[x] = next(it, "")
        else:
            plans.append(x)
    apps, sites, mac = plan_needs(plans)
    apps |= {s.strip() for s in a["--apps"].split(",") if s.strip()}
    sites |= {s.strip() for s in a["--sites"].split(",") if s.strip()}
    todo, ok = [], []
    w, h = main_display()
    (ok if w >= 1920 and h >= 1110 else todo).append(f"main display {w}x{h} points"
                                                     + ("" if w >= 1920 and h >= 1110 else
                                                        " — too small for a 1920x1080 region: use the bigger display as main"))
    probe = Path("/tmp/ewai_probe.png")
    subprocess.run(["screencapture", "-x", "-R0,0,8,8", str(probe)], capture_output=True)
    (ok if probe.exists() and probe.stat().st_size > 0 else todo).append("Screen Recording permission")
    probe.unlink(missing_ok=True)
    if mac and not Mac.cg().AXIsProcessTrusted():
        todo.append("Accessibility for Claude Code's claude.app (needed by mac-mode plans)")
    for app in sorted(apps):
        if osa(f'tell application "{app}" to get name', timeout=15, fatal=False) is None:
            todo.append(f"{app}: answer the 'wants to control {app}' prompt, and close any welcome/sign-in window in it")
        else:
            ok.append(f"{app} answers AppleScript")
            session_note(apps=[app])
    if sites:
        ensure_chrome()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = p.chromium.connect_over_cdp(f"http://127.0.0.1:{DEFAULT_PORT}").contexts[0]
            for s in sorted(sites):
                if s.startswith("file:"):
                    continue
                pg = ctx.new_page()
                try:
                    pg.goto(s, wait_until="domcontentloaded", timeout=30000)
                    pg.wait_for_timeout(3500)
                    u = pg.url
                    signed_out = ("accounts.google.com" in u or "/signin" in u or "login" in u.lower() or
                                  pg.get_by_role("button", name=re.compile(r"^(log in|sign in)$", re.I)).count() > 0)
                    (todo if signed_out else ok).append(
                        f"{s[:60]}: " + ("sign in in the recording Chrome window" if signed_out else "signed in"))
                except Exception as e:
                    todo.append(f"{s[:60]}: didn't load ({str(e)[:60]}) — the site may be down; find another real view")
                finally:
                    pg.close()
    todo.append("Do Not Disturb on (notifications would be filmed)")
    print("PREFLIGHT\n  ready:\n" + "".join(f"    ✓ {x}\n" for x in ok) +
          "  Sam, please:\n" + "".join(f"    ☐ {x}\n" for x in todo))
    sys.exit(0 if len(todo) == 1 else 1)


DOC_APPS = ["Numbers", "Keynote", "Pages", "Microsoft PowerPoint", "Microsoft Excel", "Microsoft Word",
            "Preview", "TextEdit"]


def session(argv):
    cmd = argv[0] if argv else ""
    if cmd == "start":
        SESSION.parent.mkdir(parents=True, exist_ok=True)
        snap = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "chrome": chrome_targets(), "apps_at_start": {},
                "apps": [], "paths": [], "outputs": [], "created": [], "launched": []}
        for app in DOC_APPS + ["Finder", "Terminal"]:
            if app_running(app):
                snap["apps_at_start"][app] = app_documents(app) if app in DOC_APPS else []
        SESSION.write_text(json.dumps(snap, indent=1))
        print("session started; open at start:", ", ".join(snap["apps_at_start"]) or "none",
              "| recording Chrome:", "running" if snap["chrome"] is not None else "not running")
    elif cmd == "note":                  # --session note path … | --session created "claude.ai chat: …"
        session_note(paths=[str(Path(p).resolve()) for p in argv[1:]])
    elif cmd == "created":
        session_note(created=argv[1:])
    elif cmd == "end":
        if not SESSION.exists():
            die(2, "no session: run --session start first")
        s = json.loads(SESSION.read_text())
        report = []
        # 1. recording Chrome: quit it if the session started it, else close only the tabs added since
        before = {t["id"] for t in (s.get("chrome") or [])}
        now = chrome_targets()
        if now is not None:
            if s.get("chrome") is None or "recording-chrome" in s.get("launched", []):
                pid = chrome_pid()
                if pid:
                    os.kill(pid, signal.SIGTERM)          # Chrome closes cleanly on SIGTERM
                report.append("quit the recording Chrome (sign-ins stay in its profile)")
            else:
                for t in now:
                    if t["id"] not in before:
                        urllib.request.urlopen(f"http://127.0.0.1:{DEFAULT_PORT}/json/close/{t['id']}", timeout=3)
                        report.append(f"closed tab {t['url'][:60]}")
        # 2. apps: quit the ones the session launched, close the documents it opened in the others
        for app in s.get("apps", []):
            if not app_running(app):
                continue
            if app not in s["apps_at_start"]:
                if osa(f'tell application "{app}" to quit saving no', timeout=20, fatal=False) is not None:
                    report.append(f"quit {app}")
                else:
                    report.append(f"could not quit {app} (it didn't answer) — close it by hand")
            elif app in DOC_APPS:
                for d in app_documents(app):
                    if d not in s["apps_at_start"][app]:
                        osa(f'tell application "{app}" to close document "{d}" saving no', timeout=15, fatal=False)
                        report.append(f"closed {d} in {app}")
        # 3. helper files: registered paths, raw/check files and Office lock files beside the outputs
        dirs = {str(Path(o).parent) for o in s.get("outputs", [])}
        for p in s.get("paths", []):
            pp = Path(p)
            if pp.is_dir():
                shutil.rmtree(pp, ignore_errors=True)
            elif pp.exists():
                pp.unlink()
            else:
                continue
            report.append(f"deleted {p}")
        for d in dirs:
            for pat in ("*.raw.mov", "*.check.png", "~$*"):
                for f in Path(d).glob(pat):
                    f.unlink()
                    report.append(f"deleted {f}")
        SESSION.unlink()
        print("SESSION END\n" + "".join(f"  - {r}\n" for r in report or ["nothing to close"]))
        if s.get("created"):
            print("Left in Sam's accounts (on purpose; listed so he can remove them):\n" +
                  "".join(f"  - {c}\n" for c in s["created"]))
    else:
        die(2, "--session start | note <path>… | created <text>… | end")


def promote(take):
    """NN_name_take2_4k30.mp4 becomes NN_name_4k30.mp4 (with its events and plan); other takes are deleted."""
    t = Path(take)
    m = re.match(r"(.+?)_take\d+_4k30\.mp4$", t.name)
    if not m or not t.exists():
        die(2, "pass an existing …_takeN_4k30.mp4")
    stem, d = m.group(1), t.parent
    final = d / f"{stem}_4k30.mp4"
    tkey = t.name[:-len("_4k30.mp4")]                         # NN_name_takeN
    keep = {t, t.with_name(f"{tkey}_4k30.events.json"), d / f"{tkey}.plan.json"}
    for f in list(d.glob(f"{stem}_4k30.*")) + list(d.glob(f"{stem}.plan.json")) + \
            list(d.glob(f"{stem}_take*_4k30.*")) + list(d.glob(f"{stem}_take*.plan.json")):
        if f not in keep:
            f.unlink()
            print("deleted", f.name)
    t.rename(final)
    ev = t.with_name(f"{tkey}_4k30.events.json")
    if ev.exists():
        e = json.loads(ev.read_text()); e["clip"] = final.name
        (d / f"{stem}_4k30.events.json").write_text(json.dumps(e, indent=1)); ev.unlink()
    pl = d / f"{tkey}.plan.json"
    if pl.exists():
        p = json.loads(pl.read_text()); p["output"] = str(final)
        (d / f"{stem}.plan.json").write_text(json.dumps(p, indent=1)); pl.unlink()
    print("promoted ->", final.name)


def index(folder):
    """index.md: which clip covers which script beat. Reads "beat"/"covers" from each clip's plan."""
    d = Path(folder)
    rows = []
    for clip in sorted(d.glob("*_4k30.mp4")):
        stem = clip.name[:-len("_4k30.mp4")]
        pl = d / f"{stem}.plan.json"
        p = json.loads(pl.read_text()) if pl.exists() else {}
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                             capture_output=True, text=True).stdout.strip()
        rows.append((p.get("beat", "?"), clip.name, f"{float(dur or 0):.0f}s", p.get("covers", "")))
    rows.sort(key=lambda r: (r[0] == "?", r[0]))
    md = ["# Screen recordings", "", "Which clip fills which beat of the edit map. Silent 4K/30fps; each clip's "
          "`.events.json` drives the UI sounds and its `.plan.json` re-records it.", "",
          "| Beat | Clip | Length | Shows |", "| --- | --- | --- | --- |"]
    md += [f"| {b} | `{c}` | {l} | {s} |" for b, c, l, s in rows]
    (d / "index.md").write_text("\n".join(md) + "\n")
    print("wrote", d / "index.md", f"({len(rows)} clips)")


# --------------------------------------------------------------------------- review
def sheet(clip, out, n=8):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip],
                               capture_output=True, text=True).stdout)
    tmp = Path(out).with_suffix("")
    tmp.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    tiles = []
    for i in range(n):
        t = min(dur - 0.05, (i + 0.5) * dur / n)
        f = tmp / f"{i}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1",
                        "-vf", "scale=640:360", str(f)], check=True)
        tiles.append(Image.open(f))
    c = Image.new("RGB", (1280, 360 * math.ceil(n / 2)), "white")
    for i, im in enumerate(tiles):
        c.paste(im, ((i % 2) * 640, (i // 2) * 360))
    c.save(out)
    shutil.rmtree(tmp)
    print("sheet", out, "times:", [round((i + 0.5) * dur / n, 1) for i in range(n)])


# --------------------------------------------------------------------------- UI sounds for Tella
# Tella curated presets (list_library scope "default"). onset = ms of silence before the sound starts,
# so the audible hit lands on the frame of the action. Volumes sit under Sam's voice.
SFX = {
    "click":     {"presetId": "mouse-click",     "onset": 36,  "durationMs": 300,  "volume": 0.35},
    "key":       {"presetId": "press",           "onset": 6,   "durationMs": 200,  "volume": 0.3},
    "type":      {"presetId": "keyboard-typing", "onset": 12,  "durationMs": None, "volume": 0.22},
    "page_load": None,      # opt in per step with "sound": "ui-reveal" (onset 157 ms)
    "output":    None,      # opt in per step with "sound": "success"
}
ONSET = {"mouse-click": 36, "press": 6, "tick": 58, "toggle": 29, "keyboard-typing": 12,
         "ui-reveal": 157, "success": 8, "notification-chime": 0, "button-click": 0}
PRESET_DUR = {"ui-reveal": 1150, "success": 1000, "notification-chime": 1000, "tick": 144, "toggle": 192}
TYPING_MAX_MS = 2600        # keyboard-typing is continuous for its first 2.6 s; longer runs repeat it


def sfx_ops(events_path, clip_id, layout_start, duration, in_point=0):
    ev = json.loads(Path(events_path).read_text())["events"]
    ops, last_click = [], -1e9
    for i, e in enumerate(ev):
        rel = e["t_ms"] - in_point
        if rel < 0 or rel >= duration - 150:
            continue                                     # outside the part of the clip that's shown
        spec = SFX.get(e["kind"])
        want = e.get("sound")
        if want == "none" or (spec is None and not want):
            continue
        preset = want or spec["presetId"]
        vol = (spec or {}).get("volume", 0.3)
        if e["kind"] == "click":
            if rel - last_click < 120:
                continue                                 # double-click: one sound
            last_click = rel
        start = layout_start + rel - ONSET.get(preset, 0)
        if e["kind"] == "type" and preset == "keyboard-typing":
            left = min(e.get("duration_ms", 1000), duration - rel)
            k = 0
            while left > 150:
                d = min(left, TYPING_MAX_MS)
                ops.append({"type": "add_sound_effect", "operationId": f"sfx{i}_{k}", "clipId": clip_id,
                            "presetId": preset, "name": "typing", "startTimeMs": max(0, int(start)),
                            "durationMs": int(d), "volume": vol})
                start += d; left -= d; k += 1
            continue
        dur = (spec or {}).get("durationMs") if not want or want == (spec or {}).get("presetId") else None
        dur = dur or PRESET_DUR.get(preset, 600)
        dur = min(dur, max(100, duration - rel))
        ops.append({"type": "add_sound_effect", "operationId": f"sfx{i}", "clipId": clip_id, "presetId": preset,
                    "name": e["kind"], "startTimeMs": max(0, int(start)), "durationMs": int(dur), "volume": vol})
    return ops


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--sheet":
        session_note(paths=[str(Path(sys.argv[3]).resolve())])
        return sheet(sys.argv[2], sys.argv[3])
    if len(sys.argv) >= 2 and sys.argv[1] == "--preflight":
        return preflight(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "--session":
        return session(sys.argv[2:])
    if len(sys.argv) >= 3 and sys.argv[1] == "--promote":
        return promote(sys.argv[2])
    if len(sys.argv) >= 3 and sys.argv[1] == "--index":
        return index(sys.argv[2])
    if len(sys.argv) >= 3 and sys.argv[1] == "--sfx":
        a = dict(zip(sys.argv[3::2], sys.argv[4::2]))
        try:
            ops = sfx_ops(sys.argv[2], a["--clip-id"], int(a["--layout-start-ms"]), int(a["--duration-ms"]),
                          int(a.get("--in-point-ms", 0)))
        except KeyError as k:
            die(2, f"--sfx needs {k}")
        print(json.dumps(ops, indent=1))
        return
    if len(sys.argv) < 2:
        die(2, __doc__)
    plan = json.loads(Path(sys.argv[1]).read_text())
    check = "--check" in sys.argv
    if not check:
        Path(plan["output"]).parent.mkdir(parents=True, exist_ok=True)
    mode = plan.get("mode", "browser")
    if mode == "browser":
        asyncio.run(Browser(plan, check).run())
    elif mode == "screen":
        Screen(plan, check).run()
    else:
        Mac(plan, check).run()


if __name__ == "__main__":
    main()
