# Lumen Studio — AI Avatar Training Video Platform

Turns a PowerPoint or PDF presentation into a narrated training video with an
AI avatar presenter — **without changing a pixel of your slides**. Everything
runs locally: no API keys, no per-minute costs.

## What it does

- **Exact-fidelity slides** — your deck is rendered through LibreOffice, so
  layouts, fonts, images and styling are preserved exactly.
- **Bullet-by-bullet reveals** — each slide is decomposed into true build
  states (later bullets made invisible inside the pptx itself), so bullets
  fade in *in your original styling* exactly when the narration reaches them.
- **Neural narration** — offline Piper TTS with 3 voices (US female, US male,
  UK female), per-slide speed & pause control, per-sentence exact timing.
- **Animated avatar presenter** — 8 professional characters in a circular
  frame with lip-sync (driven by the actual audio envelope), blinking, head
  motion, breathing, adjustable energy / smile / gestures / eye contact.
- **Karaoke subtitles** — word-level highlighting, 5 styles.
- **Smart keyword callouts** — animated chips for the key concept of each
  sentence.
- **AI Scene Director** — automatic per-slide transitions (fade / slide /
  zoom / cinematic wipe).
- **MP4 export** — 720p/1080p/1440p, 24/30/60 fps, three quality presets,
  with live progress + ETA.

## Setup (Linux / WSL / macOS)

```bash
# 1. system tools: LibreOffice, poppler (pdftoppm), ffmpeg
sudo apt install libreoffice poppler-utils ffmpeg      # (brew on macOS)

# 2. python deps
pip install -r requirements.txt
python -m playwright install chromium

# 3. voice models (~250 MB, one time)
python download_voices.py

# 4. (recommended) font for Canva-exported decks
sudo apt install fonts-inter fonts-crosextra-carlito
```

Fidelity tip: install the fonts your decks use. For Canva exports, map
`Canva Sans → Inter` via fontconfig (see `fonts.conf` in this repo).

## Run

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 — drop a `.pptx`, edit the per-slide scripts,
pick your avatar & voice, then **Generate video**. The MP4 appears in the
Export tab when rendering completes. Reopen a project later with
`http://localhost:8000/?p=<project-id>`.

## Architecture

| File | Role |
|---|---|
| `app.py` | FastAPI server: upload, project store, render jobs, progress |
| `slides.py` | pptx→PNG (PowerPoint COM or LibreOffice); build-state engine; slide layout/role analyzer |
| `tts.py` | Piper synthesis, sentence/word timing, mouth envelope |
| `renderer.py` | AI Video Director: timeline builder + Chromium frame capture → ffmpeg |
| `presenter.py` | Photoreal presenter: preflight, Wav2Lip lip-sync, compositing |
| `validator.py` | Pre/post-render QC: state consistency, timeline sanity, presenter checks |
| `static/stage.html` | Deterministic compositor (seek(t) is a pure function of time) |
| `static/avatar.js` | Parametric avatar library + facial rig with expression director |
| `static/index.html` | The editor UI |

### Intelligence & reliability (v3)

- **Slide analysis**: every slide is classified into a layout archetype
  (timeline / toolshow / process / grid / comparison / bullets / visual) and
  each narrative unit gets a semantic role (line, marker, tool, card, heading,
  bullet, KPI, image, container). Entrances, transitions, and emphasis styles
  are chosen from these — not from a fixed template.
- **Relationship-aware transitions**: morph between sibling slides, cinematic
  fades into section beats and showcases, directional pushes after process
  slides, a slow zoom close on the finale.
- **Speech-visual sync**: reveals and emphasis windows are matched to the
  narration sentence that mentions each element; the element lifts/glows while
  discussed and an emphasized element is held until its build state lands.
- **Avatar expression director**: per-sentence expressions (welcome, focused,
  positive, concern, question, confident) with eased gaze/gesture ramps.
- **Guaranteed presenter**: photoreal mode preflights (model, torch, footage);
  if unavailable the animated avatar renders instead; if lip-sync fails
  mid-render the raw footage loop is composited — a video is never produced
  without a presenter.
- **Render QC**: pre-render validation (states/manifest alignment, image
  decode, every element's final state reachable) fails fast instead of
  producing an incomplete video; a post-render report lands in
  `out/render_report.json` (also at `/api/project/{id}/report`).

## Upgrade path to photoreal avatars

The renderer treats the avatar as a circular video layer. To swap in a
photoreal talking head (HeyGen, D-ID, Synthesia API…), generate the head
video per slide from the same narration audio and composite it in
`stage.html` instead of the SVG rig — all timing data (sentence, word,
mouth envelope) is already produced per render in `out/timeline.json`.

## Photoreal presenter mode (v2)

Upload 15–30s of front-facing footage (or a portrait photo) of a real
presenter in the **Presenter** tab. At render time the platform:
1. loops your footage ping-pong style to the narration length (no jump cuts),
2. lip-syncs the mouth to the generated narration with Wav2Lip (CPU),
3. composites the presenter in a circle or rounded card over the video.

Setup: `python download_models.py` (~430 MB, one time). Requires torch,
librosa, opencv (in requirements.txt).

**License note:** the public Wav2Lip weights are released for
research/personal use. For commercial distribution, license the model from
its authors or plug a commercial avatar API into the same presenter layer.

## Cinematic mode (v2)

Subtitles and keyword callouts are now **off by default** for a clean,
premium look (toggles in Style). The AI camera director adds gentle
push-ins and focus moves toward newly revealed regions, with highlight
sweeps, morph/push/fade/wipe transitions, and a settle-wide ending per slide.
