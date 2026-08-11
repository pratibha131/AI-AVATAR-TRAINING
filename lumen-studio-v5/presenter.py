"""
Photoreal presenter engine.

Takes user-supplied footage (or a portrait photo) of a real presenter and the
generated narration, and produces a lip-synced presenter video using Wav2Lip,
then composites it onto the rendered stage video with a circular or card mask.

Pipeline:
  1. base track: loop the footage ping-pong style to narration length
     (no visible jump cuts, natural idle motion preserved)
  2. mel spectrogram of narration (Wav2Lip audio front-end parameters)
  3. face box: detected once with OpenCV Haar cascade (talking-head footage
     is framing-stable), slightly padded, then fixed for all frames
  4. batched Wav2Lip inference on CPU
  5. ffmpeg composite onto the stage render
"""
import os, math, subprocess, tempfile, shutil
import numpy as np
import cv2

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

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'models', 'wav2lip_gan.pth')

# ---- Wav2Lip audio front-end constants (must match training preprocessing)
SR = 16000
N_FFT = 800
HOP = 200
WIN = 800
N_MELS = 80
FMIN, FMAX = 55, 7600
PREEMPH = 0.97
MIN_DB = -100
REF_DB = 20
MEL_STEP = 16          # mel frames per video frame window
W2L_FPS = 25
IMG_SIZE = 96


def preflight(footage_path):
    """Can the photoreal pipeline actually run? Checked BEFORE the stage
    render so a failure can fall back to the animated presenter instead of
    shipping a video with no presenter at all. Returns (ok, reason)."""
    if not os.path.exists(MODEL_PATH):
        return False, ('Wav2Lip model not downloaded — '
                       'run: python download_models.py')
    try:
        import torch  # noqa: F401
    except Exception as e:
        return False, f'missing dependency: {e}'
    cap = cv2.VideoCapture(footage_path)
    ok, _ = cap.read()
    cap.release()
    if not ok:
        return False, 'presenter footage could not be decoded'
    return True, ''


def probe_video_size(video_path):
    """(width, height) via OpenCV — no ffprobe dependency."""
    cap = cv2.VideoCapture(video_path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if w <= 0 or h <= 0:
        raise RuntimeError(f'could not read video dimensions: {video_path}')
    return w, h


def loop_silent(footage_path, duration, out_path):
    """Fallback presenter track: ping-pong loop the raw footage to the target
    duration at 25fps, no lip-sync. Keeps the human presenter on screen even
    when Wav2Lip fails mid-render."""
    frames, src_fps = _read_frames(footage_path)
    if not frames:
        raise RuntimeError('could not read presenter footage')
    idxs = [min(len(frames) - 1, int(round(i * src_fps / W2L_FPS)))
            for i in range(int(len(frames) * W2L_FPS / src_fps) or 1)]
    frames25 = [frames[i] for i in idxs] or frames
    n = max(1, int(duration * W2L_FPS))
    frames25 = _pingpong(frames25, n)
    H, W = frames25[0].shape[:2]
    tmp = out_path + '.tmp.mp4'
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'mp4v'), W2L_FPS, (W, H))
    for f in frames25:
        vw.write(f)
    vw.release()
    subprocess.run([FFMPEG_CMD, '-y', '-loglevel', 'error', '-i', tmp,
                    '-c:v', 'libx264', '-crf', '20', '-preset', 'fast',
                    '-pix_fmt', 'yuv420p', '-an', out_path], check=True)
    os.remove(tmp)
    return out_path


def _load_wav_16k(path):
    """Mono float32 at 16 kHz from a PCM wav — no librosa/numba needed."""
    import wave
    with wave.open(path, 'rb') as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()),
                             dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        n_out = int(len(data) * SR / sr)
        data = np.interp(np.linspace(0, len(data) - 1, n_out),
                         np.arange(len(data)), data).astype(np.float32)
    return data


def _mel_filterbank():
    """Slaney-style mel filterbank matching librosa.filters.mel defaults
    (the front-end Wav2Lip was trained with)."""
    f_sp = 200.0 / 3.0
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = math.log(6.4) / 27.0

    def hz2mel(f):
        f = np.asarray(f, dtype=np.float64)
        return np.where(f >= min_log_hz,
                        min_log_mel + np.log(np.maximum(f, 1e-9) / min_log_hz) / logstep,
                        f / f_sp)

    def mel2hz(m):
        m = np.asarray(m, dtype=np.float64)
        return np.where(m >= min_log_mel,
                        min_log_hz * np.exp(logstep * (m - min_log_mel)),
                        m * f_sp)

    mels = np.linspace(hz2mel(FMIN), hz2mel(FMAX), N_MELS + 2)
    hz = mel2hz(mels)
    bins = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    fb = np.zeros((N_MELS, len(bins)))
    for i in range(N_MELS):
        lo, c, hi = hz[i], hz[i + 1], hz[i + 2]
        up = (bins - lo) / max(c - lo, 1e-9)
        dn = (hi - bins) / max(hi - c, 1e-9)
        fb[i] = np.clip(np.minimum(up, dn), 0, None) * (2.0 / (hi - lo))
    return fb


def _melspectrogram(wav):
    """Pure-NumPy STFT + slaney mel, Wav2Lip preprocessing parameters."""
    y = np.append(wav[0], wav[1:] - PREEMPH * wav[:-1]).astype(np.float32)
    pad = N_FFT // 2
    y = np.pad(y, pad, mode='reflect')
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(WIN) / WIN)).astype(np.float32)
    n_frames = 1 + (len(y) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    frames = y[idx] * win
    D = np.abs(np.fft.rfft(frames, n=N_FFT, axis=1)).T
    S = _mel_filterbank() @ D
    S = 20 * np.log10(np.maximum(1e-5, S)) - REF_DB
    S = np.clip((2 * 4.) * ((S - MIN_DB) / (-MIN_DB)) - 4., -4., 4.)
    return S


def detect_face_box(frame):
    """One-shot face box with generous padding; returns (x1,y1,x2,y2)."""
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
    H, W = frame.shape[:2]
    if len(faces) == 0:
        # fallback: center crop
        s = min(H, W) // 2
        return (W // 2 - s // 2, H // 4, W // 2 + s // 2, H // 4 + s)
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    padx, pady_top, pady_bot = int(w * 0.12), int(h * 0.12), int(h * 0.22)
    return (max(0, x - padx), max(0, y - pady_top),
            min(W, x + w + padx), min(H, y + h + pady_bot))


def _read_frames(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames, fps


def _pingpong(frames, n):
    """Loop frames forward-backward to reach n frames without jump cuts."""
    if len(frames) >= n:
        return frames[:n]
    seq = []
    fwd = True
    while len(seq) < n:
        seq.extend(frames if fwd else frames[::-1])
        fwd = not fwd
    return seq[:n]


def lipsync(footage_path, wav_path, out_path, progress_cb=None, device='cpu',
            max_seconds=None):
    """Produce a W2L_FPS lip-synced presenter video (with narration audio)."""
    import torch
    from wav2lip_model import load_wav2lip

    wav = _load_wav_16k(wav_path)
    if max_seconds:
        wav = wav[:int(max_seconds * SR)]
    mel = _melspectrogram(wav)
    n_frames = int(len(wav) / SR * W2L_FPS)

    frames, src_fps = _read_frames(footage_path)
    if not frames:
        raise RuntimeError('could not read presenter footage')
    # resample footage to 25fps timeline
    idxs = [min(len(frames) - 1, int(round(i * src_fps / W2L_FPS)))
            for i in range(int(len(frames) * W2L_FPS / src_fps) or 1)]
    frames25 = [frames[i] for i in idxs] or frames
    frames25 = _pingpong(frames25, n_frames)

    box = detect_face_box(frames25[0])
    x1, y1, x2, y2 = box

    # mel chunks per frame
    mel_chunks = []
    mel_idx_mult = 80. / W2L_FPS
    for i in range(n_frames):
        start = int(i * mel_idx_mult)
        if start + MEL_STEP > mel.shape[1]:
            mel_chunks.append(mel[:, -MEL_STEP:])
        else:
            mel_chunks.append(mel[:, start:start + MEL_STEP])

    model = load_wav2lip(MODEL_PATH, device)
    H, W = frames25[0].shape[:2]
    tmpdir = tempfile.mkdtemp()
    silent_path = os.path.join(tmpdir, 'silent.mp4')
    vw = cv2.VideoWriter(silent_path, cv2.VideoWriter_fourcc(*'mp4v'),
                         W2L_FPS, (W, H))
    B = 64
    total_b = math.ceil(n_frames / B)
    for bi in range(total_b):
        lo, hi = bi * B, min(n_frames, (bi + 1) * B)
        img_batch, mel_batch = [], []
        for i in range(lo, hi):
            face = cv2.resize(frames25[i][y1:y2, x1:x2], (IMG_SIZE, IMG_SIZE))
            masked = face.copy()
            masked[IMG_SIZE // 2:] = 0
            img_batch.append(np.concatenate((masked, face), axis=2) / 255.)
            mel_batch.append(mel_chunks[i])
        img_t = torch.FloatTensor(np.transpose(np.asarray(img_batch),
                                               (0, 3, 1, 2))).to(device)
        mel_t = torch.FloatTensor(np.asarray(mel_batch)[:, None]).to(device)
        with torch.no_grad():
            pred = model(mel_t, img_t)
        pred = (pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.).astype(np.uint8)
        for k, i in enumerate(range(lo, hi)):
            frame = frames25[i].copy()
            patch = cv2.resize(pred[k], (x2 - x1, y2 - y1))
            # soft-blend edges to avoid a visible seam
            mask = np.ones(patch.shape[:2], np.float32)
            e = max(4, (y2 - y1) // 12)
            mask[:e] = np.linspace(0, 1, e)[:, None]
            mask[-e:] = np.linspace(1, 0, e)[:, None]
            mask[:, :e] = np.minimum(mask[:, :e], np.linspace(0, 1, e)[None, :])
            mask[:, -e:] = np.minimum(mask[:, -e:], np.linspace(1, 0, e)[None, :])
            mask = mask[..., None]
            region = frame[y1:y2, x1:x2].astype(np.float32)
            frame[y1:y2, x1:x2] = (patch * mask + region * (1 - mask)).astype(np.uint8)
            vw.write(frame)
        if progress_cb:
            progress_cb('lipsync', (bi + 1) / total_b,
                        f'Lip-sync {bi + 1}/{total_b} batches')
    vw.release()
    # mux with (possibly trimmed) audio
    trim = ['-t', str(len(wav) / SR)]
    subprocess.run([FFMPEG_CMD, '-y', '-loglevel', 'error', '-i', silent_path,
                    '-i', wav_path, *trim, '-c:v', 'libx264', '-crf', '18',
                    '-preset', 'fast', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                    '-shortest', out_path], check=True)
    return out_path


def make_circle_mask(d, feather=3):
    """White circle on black, PNG bytes -> path."""
    m = np.zeros((d, d), np.uint8)
    cv2.circle(m, (d // 2, d // 2), d // 2 - feather, 255, -1)
    m = cv2.GaussianBlur(m, (feather * 2 + 1, feather * 2 + 1), 0)
    return m


def composite_presenter(stage_mp4, presenter_mp4, out_mp4, frame_w, frame_h,
                        pos_x=0.855, pos_y=0.80, size=0.24, shape='circle',
                        zoom=1.0, offset_y=0.0, segments=None):
    """Overlay presenter (cropped to face-centered square) on stage video.
    size = diameter as fraction of frame height. Audio comes from stage.
    segments: optional [(t, x_px)] — smart positioning; the presenter slides
    smoothly (0.7s ease) to a new side at each segment boundary."""
    d = int(size * frame_h)
    x = int(pos_x * frame_w - d / 2)
    y = int(pos_y * frame_h - d / 2)
    x_expr = str(x)
    if segments and len(segments) >= 1:
        x_expr = f'{segments[0][1]:.0f}'
        for (t_i, x_i), (t_j, x_j) in zip(segments, segments[1:]):
            x_expr = (f'({x_expr})+({x_j - x_i:.0f})*'
                      f'clip((t-{t_j:.2f})/0.7,0,1)')

    # probe presenter dims for a centered square crop around the face
    # (via OpenCV — ffprobe is not guaranteed to exist alongside bundled ffmpeg)
    pw, ph = probe_video_size(presenter_mp4)
    side = int(min(pw, ph) / max(0.4, zoom))
    cx = (pw - side) // 2
    cy = max(0, int((ph - side) // 2 + offset_y * ph))
    cy = min(cy, ph - side)

    tmp_mask = os.path.join(tempfile.mkdtemp(), 'mask.png')
    if shape == 'circle':
        cv2.imwrite(tmp_mask, make_circle_mask(d))
    else:  # rounded card
        m = np.zeros((d, d), np.uint8)
        r = d // 9
        cv2.rectangle(m, (r, 0), (d - r, d), 255, -1)
        cv2.rectangle(m, (0, r), (d, d - r), 255, -1)
        for cx2, cy2 in [(r, r), (d - r, r), (r, d - r), (d - r, d - r)]:
            cv2.circle(m, (cx2, cy2), r, 255, -1)
        cv2.imwrite(tmp_mask, m)

    # gentle floating drift sells "live camera" even on a static portrait
    cx = max(4, min(cx, pw - side - 4))
    cy = max(4, min(cy, ph - side - 4))
    drift_x = f"{cx}+3*sin(2*PI*t/6.3)"
    drift_y = f"{cy}+2*sin(2*PI*t/8.1)"
    fc = (f"[1:v]crop={side}:{side}:{drift_x}:{drift_y},scale={d}:{d}[pv];"
          f"[2:v]format=gray,scale={d}:{d}[msk];"
          f"[pv][msk]alphamerge[pva];"
          f"[0:v][pva]overlay=x='{x_expr}':y={y}[out]")
    subprocess.run([FFMPEG_CMD, '-y', '-loglevel', 'error',
                    '-i', stage_mp4, '-i', presenter_mp4,
                    '-loop', '1', '-i', tmp_mask,
                    '-filter_complex', fc, '-map', '[out]', '-map', '0:a?',
                    '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                    '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-shortest',
                    '-movflags', '+faststart', out_mp4], check=True)
    return out_mp4
