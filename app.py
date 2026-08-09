"""
AI Avatar Training Video Studio — application server.

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import os, json, uuid, shutil, threading, traceback, subprocess
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import slides as slide_engine
import tts

def get_ffmpeg_cmd():
    f = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if f:
        return f
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return 'ffmpeg'

FFMPEG_CMD = get_ffmpeg_cmd()

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(BASE, 'projects')
PRESENTER_LIB = os.path.join(BASE, 'presenter_library')
os.makedirs(PROJECTS, exist_ok=True)
os.makedirs(PRESENTER_LIB, exist_ok=True)

app = FastAPI(title='AI Avatar Training Video Studio')

# ------------------------------------------------------------------ helpers

def pdir(pid):
    d = os.path.join(PROJECTS, pid)
    if not os.path.isdir(d):
        raise HTTPException(404, 'project not found')
    return d

def load_project(pid):
    with open(os.path.join(pdir(pid), 'project.json')) as f:
        return json.load(f)

def save_project(pid, data):
    with open(os.path.join(pdir(pid), 'project.json'), 'w') as f:
        json.dump(data, f, indent=1)

# ------------------------------------------------------------------- upload

@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.pptx', '.pdf'):
        raise HTTPException(400, 'Please upload a .pptx or .pdf presentation')
    pid = uuid.uuid4().hex[:10]
    d = os.path.join(PROJECTS, pid)
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, 'source' + ext)
    with open(src, 'wb') as f:
        shutil.copyfileobj(file.file, f)

    thumbs_dir = os.path.join(d, 'thumbs')
    manifest = None
    if ext == '.pptx':
        # full-fidelity previews + build states + text extraction
        thumbs = slide_engine.pptx_to_pngs(src, thumbs_dir, dpi=60)
        info = slide_engine.extract_slide_info(src)
        try:
            states, manifest = slide_engine.render_build_states(
                src, os.path.join(d, 'build'), dpi=110)
        except Exception:
            traceback.print_exc()
            full = slide_engine.pptx_to_pngs(src, os.path.join(d, 'build', 'states'),
                                             dpi=110, prefix='st')
            states = [[p] for p in full]
    else:
        full = slide_engine.pdf_to_pngs(src, os.path.join(d, 'build', 'states'),
                                        dpi=110, prefix='st')
        states = [[p] for p in full]
        thumbs = slide_engine.pdf_to_pngs(src, thumbs_dir, dpi=40)
        info = [{'index': i, 'title': '', 'paragraphs': [], 'notes': ''}
                for i in range(len(full))]

    n = len(states)
    proj = {
        'id': pid, 'name': os.path.splitext(file.filename)[0],
        'voice': 'sofia',
        'subtitleStyle': 'professional',
        # keyword hits on by default; full subtitles stay off
        'showSubtitles': False, 'showKeywords': True, 'showProgress': False,
        'cinematic': True, 'highlightSweeps': True,
        'avatar': {'id': 'maya', 'x': 0.855, 'y': 0.80, 'size': 0.24,
                   'visible': True},
        'avatarOpts': {'energy': 0.6, 'smile': 0.5, 'gesture': 0.5, 'eye': 0.75},
        'presenter': {'mode': 'animated', 'shape': 'circle', 'zoom': 1.0,
                      'offsetY': 0.0, 'hasFootage': False},
        'width': 1920, 'height': 1080, 'fps': 30, 'quality': 'balanced',
        'slides': [],
    }
    for i in range(n):
        inf = info[i] if i < len(info) else {'title': '', 'notes': '',
                                             'paragraphs': []}
        script = slide_engine.draft_script(inf) if inf else ''
        proj['slides'].append({
            'index': i, 'title': inf.get('title') or f'Slide {i+1}',
            'script': script,
            'voice': None, 'speed': 1.0, 'pause': 0.3,
            'transition': 'auto',
            'n_states': len(states[i]),
            'est': tts.estimate_duration(script),
        })
    # persist state paths + reveal-region manifest (drives the camera director)
    with open(os.path.join(d, 'states.json'), 'w') as f:
        json.dump(states, f)
    if manifest is not None:
        with open(os.path.join(d, 'manifest.json'), 'w') as f:
            json.dump(manifest, f)
    save_project(pid, proj)
    return proj

# ------------------------------------------------------------------ project

class ProjectUpdate(BaseModel):
    data: dict

@app.get('/api/project/{pid}')
def get_project(pid: str):
    return load_project(pid)

@app.post('/api/project/{pid}')
def update_project(pid: str, upd: ProjectUpdate):
    proj = load_project(pid)
    incoming = upd.data
    for k in ('name', 'voice', 'subtitleStyle', 'showSubtitles', 'showKeywords',
              'showProgress', 'cinematic', 'highlightSweeps', 'avatar',
              'avatarOpts', 'presenter', 'width', 'height', 'fps', 'quality'):
        if k in incoming:
            proj[k] = incoming[k]
    if 'slides' in incoming:
        for i, s in enumerate(incoming['slides']):
            if i < len(proj['slides']):
                proj['slides'][i].update({k: s[k] for k in
                    ('script', 'voice', 'speed', 'pause', 'transition')
                    if k in s})
                proj['slides'][i]['est'] = tts.estimate_duration(
                    proj['slides'][i]['script'],
                    float(proj['slides'][i].get('speed') or 1.0))
    save_project(pid, proj)
    return proj

@app.get('/api/project/{pid}/thumb/{n}')
def thumb(pid: str, n: int):
    d = pdir(pid)
    files = sorted(os.listdir(os.path.join(d, 'thumbs')), key=slide_engine._num_sort_key)
    if n >= len(files):
        raise HTTPException(404)
    return FileResponse(os.path.join(d, 'thumbs', files[n]))

@app.get('/api/project/{pid}/state/{s}/{k}')
def state_img(pid: str, s: int, k: int):
    d = pdir(pid)
    with open(os.path.join(d, 'states.json')) as f:
        states = json.load(f)
    try:
        return FileResponse(states[s][k])
    except IndexError:
        raise HTTPException(404)

# ------------------------------------------------- photo presenter library

def _lib_meta():
    p = os.path.join(PRESENTER_LIB, 'meta.json')
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return []

def _save_lib_meta(m):
    with open(os.path.join(PRESENTER_LIB, 'meta.json'), 'w') as f:
        json.dump(m, f, indent=1)

@app.get('/api/presenters')
def list_presenters():
    return _lib_meta()

@app.post('/api/presenters')
async def add_presenter(file: UploadFile = File(...),
                        name: str = Form('Presenter'),
                        role: str = Form('')):
    """Add a real-photo presenter to the library (portrait photo)."""
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise HTTPException(400, 'Upload a .jpg/.png/.webp portrait photo')
    aid = uuid.uuid4().hex[:8]
    dst = os.path.join(PRESENTER_LIB, aid + '.png')
    tmp = os.path.join(PRESENTER_LIB, aid + '_src' + ext)
    with open(tmp, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    # normalize to even-dimension png (max 1024px)
    subprocess.run([FFMPEG_CMD, '-y', '-loglevel', 'error', '-i', tmp,
                    '-vf', "scale='min(1024,iw)':-2", dst], check=True)
    os.remove(tmp)
    meta = _lib_meta()
    meta.append({'id': aid, 'name': name or 'Presenter', 'role': role})
    _save_lib_meta(meta)
    return {'id': aid, 'name': name, 'role': role}

@app.delete('/api/presenters/{aid}')
def del_presenter(aid: str):
    meta = [m for m in _lib_meta() if m['id'] != aid]
    _save_lib_meta(meta)
    p = os.path.join(PRESENTER_LIB, aid + '.png')
    if os.path.exists(p):
        os.remove(p)
    return {'ok': True}

@app.get('/api/presenters/{aid}/img')
def presenter_img(aid: str):
    p = os.path.join(PRESENTER_LIB, aid + '.png')
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type='image/png')

# --------------------------------------------------------- presenter footage

@app.post('/api/project/{pid}/presenter_footage')
async def upload_presenter(pid: str, file: UploadFile = File(...)):
    """Photoreal mode: a short front-facing video (or photo) of a real
    presenter. Lips are AI-synced to the narration at render time."""
    d = pdir(pid)
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.mp4', '.mov', '.webm', '.jpg', '.jpeg', '.png'):
        raise HTTPException(400, 'Upload .mp4/.mov/.webm footage or a portrait photo')
    dst = os.path.join(d, 'presenter_footage.mp4')
    if ext in ('.jpg', '.jpeg', '.png'):
        tmp = os.path.join(d, 'presenter_src' + ext)
        with open(tmp, 'wb') as f:
            shutil.copyfileobj(file.file, f)
        # turn the photo into 3s of footage
        import subprocess
        subprocess.run([FFMPEG_CMD, '-y', '-loglevel', 'error', '-loop', '1',
                        '-i', tmp, '-t', '3', '-r', '25',
                        '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', dst],
                       check=True)
    else:
        with open(dst, 'wb') as f:
            shutil.copyfileobj(file.file, f)
    proj = load_project(pid)
    proj.setdefault('presenter', {})
    proj['presenter'].update({'mode': 'footage', 'hasFootage': True})
    save_project(pid, proj)
    return {'ok': True, 'presenter': proj['presenter']}

# ------------------------------------------------------------- voice preview

@app.get('/api/voices')
def voices():
    return [{'id': k, **{kk: vv for kk, vv in v.items() if kk != 'model'}}
            for k, v in tts.VOICES.items()]

@app.get('/api/project/{pid}/preview_audio/{n}')
def preview_audio(pid: str, n: int):
    proj = load_project(pid)
    sc = proj['slides'][n]
    res = tts.synth_slide(sc['script'], voice_id=sc.get('voice') or proj['voice'],
                          speed=float(sc.get('speed') or 1.0))
    path = os.path.join(pdir(pid), f'preview_{n}.wav')
    tts.write_wav(path, res['samples'], res['sr'])
    return FileResponse(path, media_type='audio/wav')

# ------------------------------------------------------------------- render

RENDERS = {}

def _progress_writer(d):
    def cb(stage, frac, msg):
        with open(os.path.join(d, 'progress.json'), 'w') as f:
            json.dump({'stage': stage, 'frac': round(frac, 4), 'msg': msg}, f)
    return cb

def _render_job(pid):
    d = pdir(pid)
    cb = _progress_writer(d)
    try:
        import renderer
        proj = load_project(pid)
        mpath = os.path.join(d, 'manifest.json')
        # Motion Director: when the narration changed, rebuild the slide
        # build-states so elements reveal in the order the story tells them
        src = os.path.join(d, 'source.pptx')
        if os.path.exists(src):
            import hashlib
            scripts = [(s.get('script') or '') for s in proj.get('slides', [])]
            hsh = hashlib.md5(json.dumps(scripts).encode()).hexdigest()
            hpath = os.path.join(d, 'build', 'narration_order.md5')
            old = ''
            if os.path.exists(hpath):
                with open(hpath) as f:
                    old = f.read().strip()
            if hsh != old:
                try:
                    cb('slides', 0, 'Choreographing slides to the narration…')
                    states_n, manifest_n = slide_engine.render_build_states(
                        src, os.path.join(d, 'build'), dpi=110, scripts=scripts)
                    with open(os.path.join(d, 'states.json'), 'w') as f:
                        json.dump(states_n, f)
                    with open(mpath, 'w') as f:
                        json.dump(manifest_n, f)
                    with open(hpath, 'w') as f:
                        f.write(hsh)
                except Exception:
                    traceback.print_exc()   # keep previous states on failure
        with open(os.path.join(d, 'states.json')) as f:
            states = json.load(f)
        manifest = None
        if os.path.exists(mpath):
            with open(mpath) as f:
                manifest = json.load(f)
        footage = os.path.join(d, 'presenter_footage.mp4')
        pconf = proj.get('presenter') or {}
        if pconf.get('mode') == 'photo' and pconf.get('photoId'):
            # photo presenter: build gentle 3s base footage from the portrait
            photo = os.path.join(PRESENTER_LIB, pconf['photoId'] + '.png')
            if os.path.exists(photo):
                subprocess.run([FFMPEG_CMD, '-y', '-loglevel', 'error',
                                '-loop', '1', '-i', photo, '-t', '3', '-r', '25',
                                '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                                footage], check=True)
                proj = dict(proj, presenter=dict(pconf, mode='footage'))
        out, tl = renderer.render_video(
            proj, states, os.path.join(d, 'out'), progress_cb=cb,
            manifest=manifest,
            presenter_footage=footage if os.path.exists(footage) else None)
        cb('done', 1.0, 'Render complete')
    except Exception as e:
        traceback.print_exc()
        cb('error', 0, f'Render failed: {e}')
    finally:
        RENDERS.pop(pid, None)

@app.post('/api/project/{pid}/render')
def start_render(pid: str):
    if pid in RENDERS:
        return {'status': 'already_running'}
    d = pdir(pid)
    cb = _progress_writer(d)
    cb('queue', 0, 'Starting render…')
    th = threading.Thread(target=_render_job, args=(pid,), daemon=True)
    RENDERS[pid] = th
    th.start()
    return {'status': 'started'}

@app.get('/api/project/{pid}/progress')
def progress(pid: str):
    p = os.path.join(pdir(pid), 'progress.json')
    if not os.path.exists(p):
        return {'stage': 'idle', 'frac': 0, 'msg': ''}
    with open(p) as f:
        return json.load(f)

@app.get('/api/project/{pid}/video')
def video(pid: str):
    p = os.path.join(pdir(pid), 'out', 'video.mp4')
    if not os.path.exists(p):
        raise HTTPException(404, 'not rendered yet')
    proj = load_project(pid)
    return FileResponse(p, media_type='video/mp4',
                        filename=f"{proj['name']}_training_video.mp4")

@app.get('/api/project/{pid}/narration')
def narration(pid: str):
    p = os.path.join(pdir(pid), 'out', 'narration.wav')
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type='audio/wav')

@app.get('/api/project/{pid}/timeline')
def timeline(pid: str):
    p = os.path.join(pdir(pid), 'out', 'timeline.json')
    if not os.path.exists(p):
        raise HTTPException(404)
    with open(p) as f:
        return JSONResponse(json.load(f))

app.mount('/', StaticFiles(directory=os.path.join(BASE, 'static'), html=True),
          name='static')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

