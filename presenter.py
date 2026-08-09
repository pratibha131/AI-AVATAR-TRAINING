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


def _melspectrogram(wav):
    import librosa
    y = np.append(wav[0], wav[1:] - PREEMPH * wav[:-1])
    D = librosa.stft(y=y, n_fft=N_FFT, hop_length=HOP, win_length=WIN)
    mel_basis = librosa.filters.mel(sr=SR, n_fft=N_FFT, n_mels=N_MELS,
                                    fmin=FMIN, fmax=FMAX)
    S = np.dot(mel_basis, np.abs(D))
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
    import torch, librosa
    from wav2lip_model import load_wav2lip

    wav, _ = librosa.load(wav_path, sr=SR)
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
    import json as _json
    pr = subprocess.run(['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
                         '-show_entries', 'stream=width,height', '-of', 'json',
                         presenter_mp4], capture_output=True, text=True)
    st = _json.loads(pr.stdout)['streams'][0]
    pw, ph = st['width'], st['height']
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
