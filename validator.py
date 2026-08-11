"""
Render quality control.

Pre-render: verify the composition inputs are complete and consistent
(state images exist/decode, manifest aligns with states, timeline is sane,
every element's final build state is actually reached) so the renderer fails
fast instead of silently producing an incomplete video.

Post-render: probe the finished MP4 (duration, resolution) and verify the
photoreal presenter really was composited into the frame. Results land in
out/render_report.json.
"""
import os, json, subprocess, shutil


def _issues_add(issues, level, msg):
    issues.append((level, msg))


def validate_pre(state_paths, manifest, timeline):
    """Returns [(level, message)] with level in {'fatal', 'warn'}."""
    import cv2
    issues = []

    # ---- state images: existence, decodability, uniform dimensions
    sizes = set()
    for si, lst in enumerate(state_paths):
        if not lst:
            _issues_add(issues, 'fatal', f'slide {si+1}: no state images')
            continue
        for p in lst:
            if not os.path.exists(p):
                _issues_add(issues, 'fatal',
                            f'slide {si+1}: missing state image '
                            f'{os.path.basename(p)}')
        for p in {lst[0], lst[-1]}:
            if os.path.exists(p):
                img = cv2.imread(p)
                if img is None:
                    _issues_add(issues, 'fatal',
                                f'slide {si+1}: unreadable state image '
                                f'{os.path.basename(p)}')
                else:
                    sizes.add(img.shape[:2])
    if len(sizes) > 1:
        _issues_add(issues, 'warn',
                    f'state images have mixed dimensions: {sorted(sizes)} — '
                    f'element highlights may be misplaced')

    # ---- manifest / states alignment
    if manifest:
        if len(manifest) != len(state_paths):
            _issues_add(issues, 'warn',
                        f'manifest covers {len(manifest)} slides but '
                        f'{len(state_paths)} slides have states')
        for si, (m, lst) in enumerate(zip(manifest, state_paths)):
            if m.get('n_states') and m['n_states'] != len(lst):
                _issues_add(issues, 'fatal',
                            f'slide {si+1}: manifest expects '
                            f"{m['n_states']} states, found {len(lst)} — "
                            f'build states are misaligned')
            for r in (m.get('regions') or []):
                # degenerate (zero-width/height) regions are legal: straight
                # connector lines have no extent on one axis
                if not (-0.05 <= r[0] <= r[2] <= 1.3 and
                        -0.05 <= r[1] <= r[3] <= 1.3):
                    _issues_add(issues, 'warn',
                                f'slide {si+1}: element region {r} outside '
                                f'the visible frame')

    # ---- timeline sanity
    for i, sl in enumerate(timeline.get('slides', [])):
        K = len(sl.get('states', [])) - 1
        revs = sl.get('reveals') or []
        for r in revs:
            if not (sl['t0'] - 0.01 <= r['t'] <= sl['t1'] + 0.01):
                _issues_add(issues, 'warn',
                            f"slide {i+1}: reveal at {r['t']:.2f}s is outside "
                            f"the slide's time range")
        if K > 0:
            if not revs:
                _issues_add(issues, 'warn',
                            f'slide {i+1}: has {K} build steps but no reveal '
                            f'times — content would stay hidden')
            else:
                last_state = max(r['state'] for r in revs)
                if last_state < K:
                    _issues_add(issues, 'fatal',
                                f'slide {i+1}: final build state {K} is never '
                                f'revealed — elements would be missing')
        for a in sl.get('actives', []):
            if a['t1'] <= a['t0']:
                _issues_add(issues, 'warn',
                            f'slide {i+1}: zero-length emphasis window')
    return issues


def _probe_mp4(path):
    import cv2
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    nf = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {'fps': fps, 'frames': nf, 'width': w, 'height': h,
            'duration': (nf / fps) if fps else 0.0}


def _has_audio_stream(path):
    ff = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    try:
        r = subprocess.run([ff, '-hide_banner', '-i', path],
                           capture_output=True, text=True, timeout=30)
        return 'Audio:' in (r.stderr or '')
    except Exception:
        return None


def validate_post(out_path, timeline, outdir):
    """Probe the finished video and write out/render_report.json."""
    report = {'ok': True, 'warnings': [], 'checks': {}}
    try:
        info = _probe_mp4(out_path)
        report['checks']['video'] = info
        expected = float(timeline.get('total') or 0)
        if info['duration'] <= 0:
            report['ok'] = False
            report['warnings'].append('rendered video has no readable frames')
        elif expected and abs(info['duration'] - expected) > 2.0:
            report['warnings'].append(
                f"video duration {info['duration']:.1f}s differs from "
                f"timeline {expected:.1f}s")
        if (info['width'], info['height']) != (timeline.get('width'),
                                               timeline.get('height')):
            report['warnings'].append(
                f"resolution {info['width']}x{info['height']} differs from "
                f"requested {timeline.get('width')}x{timeline.get('height')}")
        audio = _has_audio_stream(out_path)
        report['checks']['audio_stream'] = audio
        if audio is False:
            report['ok'] = False
            report['warnings'].append('no audio stream in rendered video')
    except Exception as e:
        report['ok'] = False
        report['warnings'].append(f'post-render probe failed: {e}')
    try:
        with open(os.path.join(outdir, 'render_report.json'), 'w') as f:
            json.dump(report, f, indent=1)
    except Exception:
        pass
    return report


def _grab_frame(path, t):
    import cv2
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def verify_presenter_composited(stage_mp4, out_mp4, timeline, av_cfg,
                                segments=None):
    """Did the presenter actually land in the final frame? Samples the middle
    of the video and diffs the presenter region against the bare stage
    render. Returns (ok, message)."""
    import numpy as np
    t = float(timeline.get('total') or 4) * 0.5
    a = _grab_frame(stage_mp4, t)
    b = _grab_frame(out_mp4, t)
    if a is None or b is None:
        return False, 'could not sample frames for the presenter check'
    if a.shape != b.shape:
        return True, 'stage/final resolutions differ — skipping region diff'
    H, W = a.shape[:2]
    d = int(float(av_cfg.get('size', 0.24)) * H)
    y = int(float(av_cfg.get('y', 0.80)) * H - d / 2)
    x = float(av_cfg.get('x', 0.855)) * W - d / 2
    if segments:
        for (ts, xs) in segments:
            if ts <= t:
                x = xs
    x = int(x)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + d), min(H, y + d)
    if x1 <= x0 or y1 <= y0:
        return False, 'presenter region is outside the frame'
    ra = a[y0:y1, x0:x1].astype(np.int16)
    rb = b[y0:y1, x0:x1].astype(np.int16)
    diff = float(np.mean(np.abs(ra - rb)))
    if diff < 2.0:
        return False, (f'presenter region looks unchanged '
                       f'(mean pixel diff {diff:.2f})')
    return True, f'presenter composited (mean pixel diff {diff:.2f})'
