# Recording screen footage for Sam

Claude records the script's `Screen recording` beats, and B-roll beats that are screen captures, itself, so Sam doesn't have to. Every clip shows **real** UI and **real** results: Claude drives the actual website or app on Sam's Mac and captures it. Nothing is mocked up, re-typed or invented.

**Run it end to end without check-ins.** Sam's request ("record the screen recordings for video 15", "all of them need to be created") is the go-ahead for the whole pass. Ask him things **once**, at preflight (section 1), then work through every beat, build missing results, retake failed takes, clean up, and report once at the end. Don't stop between clips to confirm a plan, a take or a file name; pick the sensible default and list it in the report.

Recorder: `scripts/ewai_record.py`. It takes a JSON **shot plan** per clip and has three modes:

| Mode | Use for | How it captures |
|---|---|---|
| `browser` | Any website or web app: YouTube Studio, Tella, claude.ai, Cloudflare, GitHub, docs, a local HTML file | Frame-stepped. It sets the cursor, scroll and typing for each frame, then screenshots. The output is smooth, deterministic 30fps, and nothing is lost to lag. |
| `screen` | The recording Chrome **and** native apps in one shot: PowerPoint next to a web page; a claude.ai chat, then a Numbers cross-check | Real-time capture of a 1920×1080-point region. Chrome is driven over CDP with a drawn cursor; apps through their own AppleScript dictionary. Places the windows itself. **Needs no Accessibility.** |
| `mac` | Native apps driven by mouse and keyboard: Finder, Terminal, editors | Real-time capture of a window region with `screencapture -v`, driven by AppleScript and CoreGraphics mouse events. Needs Accessibility. |

Prefer `browser` whenever the thing to show is a web page; `screen` when an app has to be on screen but only needs placing, selecting or switching to; `mac` only when the app itself has to be clicked or typed into.

## The whole pass, in order

1. **Work out every beat** (section 2) and **build any missing results** (section 3).
2. `--session start`, then **preflight** (section 1): one checklist to Sam, wait for his "done", re-run preflight until it's clean.
3. For each beat: write the plan (section 7), `--check`, record, review the contact sheet, retake if needed (section 8).
4. `--promote` the chosen takes, `--index` the folder (section 9).
5. `--session end`: closes everything the pass opened and deletes helper files (section 9).
6. One report.

## 1. Preflight (the only time Sam is asked)

```bash
python3 ewai_record.py --session start
python3 ewai_record.py --preflight --apps "Numbers,Microsoft PowerPoint" --sites https://claude.ai/new plan1.json plan2.json …
```

It derives apps and sites from the plans and checks, in one go:

- **Main display** is big enough for a 1920×1080-point region. Sam sometimes switches between the laptop and the external display: the recorder reads the current main display, never assume a size.
- **Screen Recording** permission.
- **Accessibility**, only if a `mac`-mode plan needs it.
- **Each app answers AppleScript.** A timeout means a macOS "Claude wants to control *App*" prompt or a first-run window (e.g. Microsoft 365's "Welcome to Premium") is open in it. Running preflight raises every Automation prompt at once instead of one hanging mid-recording (PowerPoint looked "frozen" for this reason). Approving it is Sam's call; never click it.
- **Each site is signed in** in the recording Chrome (the profile keeps sign-ins between sessions). A site that doesn't load (e.g. the datasette demo returning Heroku errors) gets flagged so you can pick another real view of the same data (datahub.io, the raw GitHub file).
- **Do Not Disturb** (always listed: it can't be checked).

Send Sam the "Sam, please" list as **one** message (plus anything from section 2 that only he can supply), wait for "done", and re-run preflight. Exit code 0 = ready.

## 2. Work out what to record

For each beat whose coverage is `Screen recording: <description>`, or ``B-roll `<file>.mp4` `` with no file, check in order:

1. **Footage already exists?** Check the Tella recording (storyboard over the beat), Sam's separate Tella recordings, and the project folder (`yt_screen_recordings_v*/` and its `index.md`, `screen_studio_recording/`, `b-roll/`). If it's usable, don't re-record.
2. **Read the capture brief.** This is the matching entry in `recording_notes_vN.md` or `screen_recording_requirements_vN.md` (the cue line links to its anchor), or in `b_roll_requirements_vN.md` for B-roll. A B-roll that isn't a screen (camera, phone, stock footage) can't be recorded: report it. Read **Open** (where), **Prepare**, **Record** (what the viewer must see, in order), **Stop when**, **Narration window** and **Missing**.
3. **Resolve the target.** Use, in this order:
   - a link or path Sam gave in his message;
   - a link or path named in the brief;
   - project facts the brief points at:
     - a YouTube Studio upload: `/Users/sam/Claude/yt_uploader/state/uploads.json`, keyed by the project folder path, gives `video_id` → `https://studio.youtube.com/video/<id>/edit`. Use the project the brief names. When the current video has no upload yet, the brief usually says to use an earlier completed project;
     - local folders and files: the project folder itself (`claude_design_exports/`, `powerpoint_baseline/`, `analysis/`);
     - Artifacts built for this video: their claude.ai links, from the project's results/handoff notes;
     - commands: the exact command in the brief (see the safety rules);
   - only then **ask Sam**, folded into the single preflight message.
4. **"Missing" → build it if Claude can** (section 3). Only a result Claude can't produce (a real upload, a successful production run, camera footage) is reported as a gap.

## 3. Build missing results before recording

When a brief's **Missing** line (or a missing file) names a result Claude can make itself, make it, from the project's own inputs, then record it. Don't ask first: Sam asking for the recordings covers this. The source is always the project's checked data (`analysis/*_results_*.md`) and the exact prompt in `recording_notes_vN.md` → "Prompts to paste".

| Result the brief needs | How Claude builds it |
|---|---|
| A Claude Design deck or interactive page | Artifacts tool, from the Slides / Design types, using the prompt to paste and the checked numbers. Save a standalone copy to `<project>/claude_design_exports/`. |
| A plain PowerPoint baseline slide | `anthropic-skills:pptx` (pptxgenjs, structured, native chart), saved to `<project>/powerpoint_baseline/`. Deliberately plain; same scope and numbers as the other builds. |
| A claude.ai analysis chat (attachment + prompt + answer) | Record it live with a `browser` plan: `upload` the file, `send_prompt` the prompt (it waits for the full answer, off camera), then scroll the answer. Needs `"allow_send": true`. |
| An independent spreadsheet cross-check (COUNTIF/COUNTIFS) | `openpyxl` workbook in `<project>/analysis/`: a "Cross-check" sheet (formula, Claude's number, ✓ match), a source-row lookup with the brief's row highlighted, and the raw data. Large fonts (22–30 pt) so it reads at 4K. Open it in Numbers, which recalculates; selecting a formula cell shows the formula in Numbers' formula bar. |

**Check before filming:** every number the built result shows must equal the analysis results (verify the answer/workbook values programmatically). If they disagree, fix the build; never record a wrong number.

Record what was created in Sam's accounts so the end report lists it: `python3 ewai_record.py --session created "claude.ai chat: <title>" "Artifact: <title> <url>"`.

## 4. Safety rules (non-negotiable)

- **Look, don't change.** Recordings may hover, scroll, open menus and dialogs, switch tabs, pick filters and follow navigation links. They never edit fields, save, publish, delete, change visibility, or accept terms. The recorder refuses to click anything labelled Save, Publish, Done, Delete, Upload, Send, Submit, Confirm and similar (exit code 4). Don't work around the refusal.
- **The one exception is building a result Claude makes itself** (section 3): `upload` and `send_prompt` work only in a plan with `"allow_send": true`, only in Sam's own claude.ai, only with the project's file and prompt.
- **Commands:** in `mac` mode, only run commands the brief names that are read-only or a dry run (`ls`, `cat`, `--dry-run`, previews, status). Anything that uploads, publishes, deletes, spends money or changes an account needs Sam's explicit yes in chat first. Never use `--force`, and never re-run a finished job just to get clean output.
- **Never record a sign-in screen, password, 2FA code or account picker.** Exit code 3 means sign-in required: add it to the preflight list.
- **Never answer a macOS permission prompt for Sam**, and never click a dialog in an app with System Events (it needs Accessibility, and it isn't Claude's call).
- **Real results only.** Never type fake output or edit what the page says. The only page changes allowed are the drawn cursor, privacy blurs/hides, and collapsing a sidebar.

## 5. Privacy

- **Browser and screen modes** use the recording Chrome (its own profile, `~/.cache/ewai-studio-capture-profile`, port 9333), never Sam's own Chrome, which has his tabs (bank, email, other projects). Each recording opens its own tab and closes it afterwards.
- **Automatic site defaults** (`SITE_PRIVACY` in the script; add sites as you find them): on claude.ai the sidebar (lists Sam's other chats) is collapsed and the connected-computer label (`sam_mbp, Connected`) is hidden.
- Blur anything else private with `"mask": [selectors]`, or hide it with `"hide": [selectors]`: personal emails, account IDs, API keys, other people's names.
- **Screen mode:** Chrome's toolbar (URL with `/Users/sam/…` paths, profile icon) sits above the region, so it's never filmed. Every pixel of the region must be covered by a window the plan places; look at the `--check` still for anything else (desktop icons, Sam's windows).
- **Mac:** `screencapture -R` records **whatever is inside the rectangle**. The target window is sized exactly to the region; nothing else may overlap it. Never take a test capture of the whole screen: it records Sam's other apps.
- Review the contact sheet for leaks before delivering, and report anything borderline.

## 6. One-time setup on Sam's Mac

The recorder runs **on Sam's Mac**: with `Bash` in a local session, or with `device_bash` from a cloud session. From a cloud session, first copy `scripts/ewai_record.py` to `~/.cache/ewai-recorder/ewai_record.py` on the Mac (heredoc with a quoted delimiter).

- Python Playwright, `ffmpeg`, Google Chrome, `openpyxl` (`python3 -m pip install --user openpyxl` if missing). Run Python with `python3 -E` (`-I` hides the user site-packages where Playwright lives).
- **macOS permissions** (Sam grants these, never Claude), for the app that runs Claude:
  - **Screen Recording** (all modes except `browser`);
  - **Automation** for each app a plan controls (preflight raises the prompts);
  - **Accessibility**, only for `mac` mode.

  **Which app needs it:** in the Claude desktop app, commands run under Claude Code's own bundled app, not `/Applications/Claude.app`. Find it with `ps -axo ppid=,comm= | grep claude-code`: it's `~/Library/Application Support/Claude/claude-code/<version>/<id>/claude.app`. Reveal it with `open -R <path>`; the folder changes when Claude Code updates, so exit code 5 after an update means adding the new copy.

## 7. Write the shot plan

Write it to scratch space (`--session note <dir>` so it's cleaned up), then save the final copy next to the clip as `<NN>_<name>.plan.json`.

Every plan gets **`"beat"`** (the edit-map / recording-notes id, e.g. `"recording-03"` or `"B-roll 01_claude_design_exports"`) and **`"covers"`** (one line: what it shows). `--index` builds `index.md` from them.

- **Pace it to the narration window.** Speech runs about 2.4 words per second. Plan the actions in the order the narration names things, holding on each one while it's spoken. Then add a 4–6 s still hold at the end so the editor has room to trim. A typical beat runs 15–40 s.
- **Point at what's being talked about.** Every narrated item gets a cursor move to it and a hold of 1.2–2.5 s. Scroll only as far as the brief asks.
- **Avoid hover pop-ups.** Route around them with `via` waypoints in an empty gutter, and aim at the exact text (`"text": "Private", "within": "<card selector>"`).
- **Start from a known state.** Interactive pages: reset filters first (or load the page fresh) so the clip starts where the narration does. Editors with view modes (Claude Design's deck editor has an overview grid): make sure the plan returns to the single-slide view, and check the end frame.

### Browser plan

```json
{
  "mode": "browser",
  "beat": "recording-02", "covers": "FiveThirtyEight CSV and its schema",
  "output": "<project>/yt_screen_recordings_vN/04_fivethirtyeight_csv_schema_4k30.mp4",
  "browser": {"url": "https://…", "wait_for": "<selector that means the page is ready>",
              "viewport": [1600, 900], "scroller": "#main"},
  "mask": [], "hide": [],
  "steps": [
    {"do": "hold", "s": 1.2},
    {"do": "move", "to": {"selector": "#title-textarea", "fx": 0.4, "fy": 0.38}, "s": 1.0},
    {"do": "scroll", "to": {"text": "Thumbnail"}, "offset": 230, "s": 2.0},
    {"do": "scroll", "to_px": 1400, "axis": "x", "scroller": ".table-wrap", "s": 2.5},
    {"do": "select", "to": {"selector": "#season"}, "value": {"label": "Season 1"}},
    {"do": "click", "to": {"text": "Mountain"}, "settle_ms": 600},
    {"do": "offline", "on": true},
    {"do": "key", "key": "Escape"},
    {"do": "goto", "url": "https://…", "wait_for": "…"},
    {"do": "hold", "s": 5.0}
  ],
  "after_check": [{"target": {"selector": "ytcp-video-metadata-visibility"}, "expect": "Private"}]
}
```

**Browser steps:** `hold {s}` · `move {to, via?, s}` · `scroll {by | to+offset | top:true | to_px (+ axis "x"/"y", scroller), s}` · `click {to?, wait_for?, settle_ms?}` · `type {to?, text, cps}` (search/filter boxes) · `key {key}` · `goto {url, wait_for?}` · `select {to, value | {index} | {label}}` · `offline {on}` (proves a page works with no network; the recorder always turns it back off) · `upload {files, input?}` and `send_prompt {text, box?, cps?}` / `wait_answer {}` (only with `"allow_send": true`; the wait for the answer is cut out of the clip).

**Browser targets:** `selector` | `text` (with `exact`, default true) | `role` + `name` | `label` | `x`,`y` (CSS px in the viewport). Optional `within` scopes the search. `fx`/`fy` set the point inside the box (0–1) and `dx`/`dy` offset it in px. Playwright selectors pierce shadow DOM.

**Viewport:** 1600×900 suits dense web apps; it's upscaled to 3840×2160. Use 1920×1080 for wide pages and slide decks. `scroller` is the element that scrolls (`#main` in YouTube Studio); omit it for normal pages.

**Local files** (Claude Design exports, the standalone deck) open with `file:///…` URLs; arrow keys (`key`) step through a deck.

### Screen plan (Chrome + apps)

```json
{
  "mode": "screen",
  "beat": "recording-03", "covers": "claude.ai analysis chat, then the Numbers COUNTIFS cross-check",
  "output": "<project>/yt_screen_recordings_vN/03_claude_analysis_chat_4k30.mp4",
  "region": "auto",
  "windows": [
    {"app": "Numbers", "open": "<project>/analysis/<name>_crosscheck.xlsx", "rect": [0, 0, 1920, 1080]},
    {"chrome": {"url": "https://claude.ai/chat/<id>"}, "rect": [0, 0, 1920, 1080]}
  ],
  "steps": [
    {"do": "hold", "s": 3.5},
    {"do": "chrome_scroll", "to": {"text": "Structure"}, "offset": 90, "ms": 2500},
    {"do": "hold", "s": 3.0},
    {"do": "chrome_click", "to": {"text": "Mountain"}},
    {"do": "front", "window": "Numbers"},
    {"do": "select_cells", "range": "C12"},
    {"do": "hold", "s": 4.0}
  ],
  "length_s": 40
}
```

- `region`: `"auto"` picks a 1920×1080-point area on the current main display (3840×2160 px). `rect`s are relative to it. A Chrome `rect` is the **page area** (its toolbar sits above the region); an app `rect` is the whole window (its own toolbar is fine on camera). Side by side: e.g. PowerPoint `[0,0,960,1080]`, Chrome `[960,0,960,1080]`. The last window listed starts in front.
- Steps: `hold` · `front {window: "chrome" | app}` (the recording Chrome is raised by its PID, so Sam's own Chrome never comes forward) · `chrome_move {to, s}` · `chrome_click {to}` (same refusal list as browser mode) · `chrome_select {to, value}` · `chrome_scroll {to_px | to+offset, ms, scroller?}` · `select_cells {range, app?, table?}` (Numbers) · `osascript {script}` (the app's own dictionary only, e.g. PowerPoint `run slide show`; never System Events).
- `length_s` sets the clip length. The macOS capture stops saving frames once the screen stops changing, so the recorder clones the last frame out to `length_s`. Default: the steps plus a 4 s hold.
- **PowerPoint:** fine as a window in Normal view. Use its own AppleScript for slide-show settings (`set show type of slide show settings of active presentation to slide show type window`, then `run slide show`). A first-run "Welcome" modal blocks all scripting; preflight catches it.

### Mac plan

```json
{
  "mode": "mac",
  "beat": "recording-05", "covers": "the export folder in Finder",
  "output": "<project>/yt_screen_recordings_vN/03_finder_project_folder_4k30.mp4",
  "mac": {"app": "Finder", "region": [0, 25, 1920, 1080]},
  "setup": [
    {"do": "osascript", "script": "tell application \"Finder\" to make new Finder window to (POSIX file \"/Users/sam/…/fcp_export\")"},
    {"do": "osascript", "script": "tell application \"Finder\" to set current view of front window to list view"}
  ],
  "steps": [
    {"do": "hold", "s": 1.2},
    {"do": "move", "to": {"x": 420, "y": 180}, "s": 1.0},
    {"do": "click", "to": {"x": 420, "y": 180}},
    {"do": "hold", "s": 5.0}
  ],
  "teardown": [{"do": "osascript", "script": "tell application \"Finder\" to close front window"}]
}
```

**Finder:** open the folder with `make new Finder window to (POSIX file "…")`, not `open POSIX file`. **Timing:** `screencapture` only saves the file when its own timer runs out, so the recorder sizes the timer from the steps plus `mac.tail_margin` (default 3 s); raise it if it warns "the end is cut". **Coordinates:** `--check` saves `<output>.check.png` of exactly the region; divide its pixels by 2 for step `x`/`y`. **teardown:** close what setup opened; `--session end` catches anything left. Steps: `hold` · `move` · `click` · `type {text, cps, enter?}` · `key {key}` · `osascript {script}` · `wait_for_text {text, timeout, then_hold}` (Terminal).

**Sounds:** every `click`, `key`, `type`, `goto`, `select`, `chrome_click`, `select_cells` and `wait_for_text` step can take `"sound"`: a Tella preset id (`"success"`, `"ui-reveal"`), or `"none"`. See SKILL.md step 7.

## 8. Record, review, retake

1. `python3 ewai_record.py plan.json --check` resolves every target without recording. Fix any that don't resolve.
2. `python3 ewai_record.py plan.json` records.
3. `python3 ewai_record.py --sheet clip.mp4 sheet.png` and **look at the sheet**. Pass only if:
   - the right page and item, starting from the state the narration starts from;
   - the cursor is visible and on each narrated thing;
   - no pop-up covers the subject, and the view is right (e.g. single slide, not an overview grid);
   - every number on screen matches the analysis;
   - no private data;
   - the end frame shows the beat's "Stop when" state.
4. **Failed? Retake without asking.** Fix the plan and record `…_take2_4k30.mp4` (then `take3`). Ask Sam only if take 3 still fails, or the failure is something only he can fix.
5. `ffprobe`: 3840×2160, 30/1, h264, yuv420p, no audio, length ≥ the narration window + 4 s. Check `<clip>.events.json` lists the clicks you expect.

## 9. Save, index, clean up, report

1. **Names:** `<project>/yt_screen_recordings_vN/<NN>_<short_name>_4k30.mp4`, NN = script section number (letter suffix for a second clip in a section: `07b_…`), highest existing `vN`. Never overwrite a clip: retakes are `…_take2_4k30.mp4`.
2. **Promote** the passing take: `python3 ewai_record.py --promote <dir>/<NN>_<name>_take2_4k30.mp4`. It becomes `<NN>_<name>_4k30.mp4` with its events and plan, and the other takes are deleted, so the folder holds exactly one clip per beat.
3. **Index:** `python3 ewai_record.py --index <dir>` writes `index.md` (beat → clip → length → what it shows). The Tella edit reads it to place clips; it replaces hand-made mapping tables.
4. **Clean up:** `python3 ewai_record.py --session end`. It:
   - closes the recording Chrome's tabs opened during the session (or quits that Chrome if the session started it; sign-ins stay in its profile);
   - quits apps the session launched (without saving) and closes the documents it opened in apps that were already running; Sam's own apps, windows and documents are never touched;
   - deletes registered helper paths (scratch plans, test files, contact sheets, staged uploads) plus `*.raw.mov`, `*.check.png` and Office `~$` lock files beside the outputs;
   - lists what was left in Sam's accounts on purpose (claude.ai chats, Artifacts).

   Register helper files as you make them: `--session note <path>…`. Also delete any `/tmp` files you created. Keep only: the clips, their `.events.json`, their `.plan.json`, `index.md`, and the built results in the project folder (exports, baseline slide, cross-check workbook).
5. **Report once:**
   - each clip: beat, length, what it shows;
   - results Claude built (where they're saved; what was created in Sam's accounts);
   - retakes and why;
   - gaps not recorded and why (missing real result, permission, sign-in);
   - the `after_check` result and the cleanup summary;
   - that clips were reviewed as contact sheets, not watched in motion.

Example plans that produced real clips: `references/examples/`.
