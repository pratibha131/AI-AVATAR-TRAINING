"""
Voice engine: offline neural TTS (Piper) with sentence-level exact timing and
word-level estimated timing for karaoke subtitles and animation sync.
"""
import os, re, wave, io, json, math
import numpy as np
from piper import PiperVoice, SynthesisConfig

VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voices')

VOICES = {
    'sofia': {
        'label': 'Sofia — Warm Professional (Female, US)',
        'model': 'en-us-lessac-medium.onnx',
        'tags': ['Female', 'US English', 'Corporate Trainer', 'Warm'],
    },
    'ryan': {
        'label': 'Ryan — Confident Presenter (Male, US)',
        'model': 'en-us-ryan-high.onnx',
        'tags': ['Male', 'US English', 'Business Professional', 'Confident'],
    },
    'emily': {
        'label': 'Emily — Friendly Educator (Female, UK)',
        'model': 'en-gb-southern_english_female-low.onnx',
        'tags': ['Female', 'British English', 'University Professor', 'Friendly'],
    },
}

_loaded = {}

def get_voice(voice_id):
    v = VOICES.get(voice_id) or VOICES['sofia']
    path = os.path.join(VOICE_DIR, v['model'])
    if path not in _loaded:
        _loaded[path] = PiperVoice.load(path)
    return _loaded[path]


SENT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(])')

def split_sentences(text):
    text = re.sub(r'\s+', ' ', text.strip())
    if not text:
        return []
    parts = SENT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def synth_sentence(voice, text, speed=1.0):
    """Return (float32 mono samples, sample_rate)."""
    cfg = SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, speed)))
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        voice.synthesize_wav(text, w, syn_config=cfg)
    buf.seek(0)
    with wave.open(buf, 'rb') as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0, sr


def word_timings(sentence, t0, dur):
    """Distribute words across [t0, t0+dur] weighted by characters."""
    words = sentence.split()
    if not words:
        return []
    weights = np.array([len(w) + 1.5 for w in words], dtype=float)
    weights /= weights.sum()
    out, t = [], t0
    for w, frac in zip(words, weights):
        d = frac * dur
        out.append({'w': w, 't0': round(t, 3), 't1': round(t + d, 3)})
        t += d
    return out


def synth_slide(script, voice_id='sofia', speed=1.0, sentence_gap=0.28,
                lead_in=0.45, tail=0.6, sr_out=22050):
    """Synthesize one slide's narration.
    Returns dict: samples (float32 @ sr_out), duration, sentences:[{text,t0,t1,words}]
    """
    voice = get_voice(voice_id)
    sentences = split_sentences(script)
    chunks = [np.zeros(int(lead_in * sr_out), dtype=np.float32)]
    t = lead_in
    sent_meta = []
    for s in sentences:
        samples, sr = synth_sentence(voice, s, speed)
        if sr != sr_out:
            # linear resample
            n_out = int(len(samples) * sr_out / sr)
            samples = np.interp(np.linspace(0, len(samples) - 1, n_out),
                                np.arange(len(samples)), samples).astype(np.float32)
        dur = len(samples) / sr_out
        sent_meta.append({'text': s, 't0': round(t, 3), 't1': round(t + dur, 3),
                          'words': word_timings(s, t, dur)})
        chunks.append(samples)
        gap = np.zeros(int(sentence_gap * sr_out), dtype=np.float32)
        chunks.append(gap)
        t += dur + sentence_gap
    chunks.append(np.zeros(int(tail * sr_out), dtype=np.float32))
    t += tail
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    return {'samples': audio, 'sr': sr_out, 'duration': round(t, 3),
            'sentences': sent_meta}


def estimate_duration(script, speed=1.0):
    words = len(script.split())
    return round(words / (2.45 * speed) + 1.2, 1)


def mouth_envelope(samples, sr, fps):
    """Per-video-frame mouth openness 0..1 from audio RMS."""
    n_frames = max(1, int(math.ceil(len(samples) / sr * fps)))
    win = int(sr / fps)
    env = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = samples[i * win:(i + 1) * win]
        if len(seg):
            env[i] = np.sqrt(np.mean(seg ** 2))
    # normalize with soft knee
    p95 = np.percentile(env[env > 0], 95) if (env > 0).any() else 1.0
    env = np.clip(env / (p95 + 1e-6), 0, 1.0)
    env = np.power(env, 0.7)
    # slight smoothing
    k = np.array([0.2, 0.6, 0.2])
    env = np.convolve(env, k, mode='same')
    return np.clip(env, 0, 1).tolist()


def write_wav(path, samples, sr):
    data = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(data.tobytes())
