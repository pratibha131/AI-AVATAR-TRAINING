"""
AI Scene Director + rendering engine.

Builds a deterministic timeline (narration, reveals, transitions, subtitles,
keyword callouts, avatar behavior), then composites every frame through the
HTML stage in headless Chromium and encodes MP4 with ffmpeg.
"""
import os, re, json, math, subprocess, time, shutil
import numpy as np
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
STAGE = os.path.join(BASE, 'static', 'stage.html')

STOPWORDS = set('''a an the and or but if then than so of to in on for with at by from as is are was
were be been being it its this that these those we you they he she i our your their my me us him her
will would can could should may might must do does did done have has had having not no nor also very
just about into over under out up down again more most other some such only own same too let lets
today well look looks see now here there when what which who whom how why all each both few many
'''.split())

def pick_keyword(sentence):
    """Choose the most important phrase in a sentence for a callout chip."""
    # prefer multi-word capitalized phrases (proper concepts)
    caps = re.findall(r'\b([A-Z][A-Za-z0-9+&-]*(?:\s+[A-Z][A-Za-z0-9+&-]*){0,3})\b',
                      sentence)
    caps = [c.strip() for c in caps
            if c.lower() not in STOPWORDS and len(c) > 2]
    caps = [c for c in caps if not re.match(r"^(The|A|An|It|We|You|They|This|That|But|And|So|If|In|On|At|For|Instead|Let)\b", c) or ' ' in c]
    best = ''
    for c in caps:
        words = [w for w in c.split() if w.lower() not in STOPWORDS]
        if not words:
            continue
        cand = ' '.join(words[:3])
        if len(cand) > len(best):
            best = cand
    if best and len(best) >= 3:
        return best[:34]
    # fallback: longest non-stopword content word
    words = [w.strip('.,:;!?()"\'') for w in sentence.split()]
    cands = [w for w in words if w.lower() not in STOPWORDS and len(w) > 4]
    return (max(cands, key=len)[:30].capitalize() if cands else '')

# Brand palette: when the narration says a tool's name, the keyword hit glows
# in that tool's own colors (c1 -> c2 gradient).
BRANDS = {
    'chatgpt':          ('#10a37f', '#6ee7c8'),
    'chat gpt':         ('#10a37f', '#6ee7c8'),
    'google gemini':    ('#4285f4', '#d96570'),
    'github copilot':   ('#8b5cf6', '#38bdf8'),
    'microsoft copilot': ('#8b5cf6', '#38bdf8'),
    'meta llama':       ('#0668e1', '#a78bfa'),
    'notion ai':        ('#f8fafc', '#94a3b8'),
    'gpt':              ('#10a37f', '#6ee7c8'),
    'openai':           ('#10a37f', '#6ee7c8'),
    'sora':             ('#10a37f', '#93c5fd'),
    'gemini':           ('#4285f4', '#d96570'),
    'bard':             ('#4285f4', '#9b72cb'),
    'google':           ('#4285f4', '#34a853'),
    'claude':           ('#d97757', '#f6d9c9'),
    'anthropic':        ('#d97757', '#f6d9c9'),
    'copilot':          ('#8b5cf6', '#38bdf8'),
    'microsoft':        ('#00a4ef', '#7fba00'),
    'midjourney':       ('#7c3aed', '#c4b5fd'),
    'dall-e':           ('#10a37f', '#facc15'),
    'dalle':            ('#10a37f', '#facc15'),
    'perplexity':       ('#22b8cd', '#a7f3d0'),
    'llama':            ('#0668e1', '#a78bfa'),
    'meta':             ('#0668e1', '#a78bfa'),
    'grok':             ('#f8fafc', '#94a3b8'),
    'mistral':          ('#f54e42', '#fbbf24'),
    'deepseek':         ('#4d6bfe', '#93c5fd'),
    'stable diffusion': ('#a855f7', '#f0abfc'),
    'canva':            ('#00c4cc', '#7d2ae8'),
    'figma':            ('#f24e1e', '#a259ff'),
    'notion':           ('#f8fafc', '#94a3b8'),
    'python':           ('#3776ab', '#ffd43b'),
}
DEFAULT_GLOW = ('#38bdf8', '#818cf8')

# canonical on-screen casing for brand hits
BRAND_NAMES = {
    'chat gpt': 'ChatGPT', 'chatgpt': 'ChatGPT', 'gpt': 'GPT',
    'openai': 'OpenAI', 'sora': 'Sora',
    'google gemini': 'Gemini', 'gemini': 'Gemini', 'bard': 'Bard',
    'google': 'Google', 'claude': 'Claude', 'anthropic': 'Anthropic',
    'copilot': 'Copilot', 'github copilot': 'GitHub Copilot',
    'microsoft copilot': 'Copilot', 'microsoft': 'Microsoft',
    'midjourney': 'Midjourney', 'dall-e': 'DALL·E', 'dalle': 'DALL·E',
    'perplexity': 'Perplexity', 'llama': 'Llama', 'meta llama': 'Llama',
    'meta': 'Meta', 'grok': 'Grok', 'mistral': 'Mistral',
    'deepseek': 'DeepSeek', 'stable diffusion': 'Stable Diffusion',
    'canva': 'Canva', 'figma': 'Figma', 'notion': 'Notion',
    'notion ai': 'Notion AI', 'python': 'Python',
}

TRANSITION_CYCLE = ['morph', 'push', 'fade', 'wipe']

def auto_transition(i, n, groups=0):
    """Fallback Scene Director (no manifest — e.g. PDF decks)."""
    if i == 0:
        return 'none'
    if i == n - 1:
        return 'zoom'          # visual-focus close for the conclusion
    if groups >= 4:
        return 'wipe'          # dense multi-box slides sweep in
    if groups == 0:
        return 'morph' if i % 2 else 'fade'   # flat slides breathe in softly
    return TRANSITION_CYCLE[(i - 1) % len(TRANSITION_CYCLE)]


def plan_transition(i, n, manifest):
    """Relationship-aware Scene Director: the cut between two slides is
    chosen from what the two slides ARE, not from a rotation.
    Same layout family -> morph (visual continuity). Sparse section slide ->
    cinematic fade. After a process slide -> directional push that continues
    the flow. Dense slide -> sweep. Finale -> slow zoom close."""
    if i == 0:
        return 'none'
    m = manifest[i] if manifest and i < len(manifest) else {}
    pm = manifest[i - 1] if manifest and i - 1 < len(manifest) else {}
    lay, play = m.get('layout', ''), pm.get('layout', '')
    groups = len(m.get('regions') or [])
    if i == n - 1:
        return 'zoom'
    if groups <= 2:
        return 'cinema'                 # section/title beat: cinematic breath
    if lay and lay == play:
        return 'morph'                  # continuity between sibling slides
    if play == 'process':
        return 'push'                   # keep travelling in the flow direction
    if lay in ('timeline', 'toolshow', 'visual'):
        return 'cinema'                 # showcase slides open cinematically
    if groups >= 6:
        return 'wipe'
    return 'morph' if i % 2 else 'fade'


def _brand_mentioned(text):
    """Exact word/bigram brand match — substring tests misfire ('gpt' in
    'egypt', 'meta' in 'metadata')."""
    words = [re.sub(r'[^a-z0-9+-]', '', w) for w in (text or '').lower().split()]
    for k, w in enumerate(words):
        if w in BRANDS:
            return True
        if k + 1 < len(words) and w + ' ' + words[k + 1] in BRANDS:
            return True
    return False


def entrance_plan(regions, gsizes, gtexts=None, roles=None, layout=None):
    """Motion Director: each element's entrance comes from its semantic role
    and the slide's layout archetype. Lines draw; timeline markers rise;
    tools run the dot->line->card->logo showcase; KPIs pop; images breathe
    in; comparison sides enter from their own side; grid cards stagger
    directionally; bullets rise one by one.
    Pre-upgrade manifests carry no roles/layout — geometry inference keeps
    their tool pops and directional staggers alive."""
    n = len(regions or [])
    if not n:
        return []
    roles = roles or [''] * n

    def dims(r):
        return r[2] - r[0], r[3] - r[1]

    line_like = set()
    for i, r in enumerate(regions):
        w, h = dims(r)
        gt = (gtexts[i] if gtexts and i < len(gtexts) else '').lower()
        role = roles[i] if i < len(roles) else ''
        if role == 'line' or (w > 0.35 and w / max(h, 1e-3) > 6) \
                or 'timeline_line' in gt:
            line_like.add(i)
    others = [i for i in range(n) if i not in line_like]
    band = gridlike = False
    if others:
        cys = [(regions[i][1] + regions[i][3]) / 2 for i in others]
        band = (max(cys) - min(cys)) < 0.22
        areas = [max(1e-4, dims(regions[i])[0] * dims(regions[i])[1])
                 for i in others]
        gridlike = len(others) >= 4 and max(areas) / min(areas) < 4

    fx = []
    for i, r in enumerate(regions):
        w, h = dims(r)
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        role = roles[i] if i < len(roles) else ''
        gt = (gtexts[i] if gtexts and i < len(gtexts) else '').lower()
        big = i < len(gsizes or []) and gsizes[i] > 1
        if i in line_like:
            fx.append('draw')
        elif role in ('tool', 'marker', 'kpi') or (
                role in ('', 'card', 'item') and _brand_mentioned(gt)):
            # tools & timeline markers POP: springy scale + ripple ring,
            # no rectangular outline (the element itself is the animation)
            fx.append('pop')
        elif role == 'container' or w * h > 0.30:
            fx.append('fade')
        elif role == 'image':
            fx.append('image')
        elif layout == 'comparison':
            fx.append('slide-l' if cx < 0.5 else 'slide-r')
        elif layout == 'process' or (not layout and big and band):
            fx.append('slide-l')
        elif role == 'card':
            fx.append('flip')          # chip+bubble cards flip in (3D)
        elif layout == 'grid' or (not layout and gridlike):
            fx.append('slide-l' if cx < 0.42 else
                      'slide-r' if cx > 0.58 else
                      'drop' if cy < 0.5 else 'rise')
        else:
            fx.append('rise')
    return fx


# ---------------------------------------------------- avatar expression AI

_EXPR_CONCERN = ('warning', 'risk', 'problem', 'challenge', 'careful',
                 'danger', 'threat', 'concern', 'avoid', 'mistake', 'error',
                 'fail', 'difficult', 'limitation', 'caution')
_EXPR_POSITIVE = ('increase', 'improve', 'grow', 'benefit', 'advantage',
                  'great', 'faster', 'better', 'success', 'save', 'boost',
                  'achiev', 'win', 'easier', 'smart', 'powerful', 'help')
_EXPR_FOCUS = ('important', 'key', 'critical', 'must', 'remember',
               'note that', 'focus', 'essential', 'core', 'main')
_EXPR_WELCOME = ('welcome', 'hello', 'today we', "let's talk", 'introduc',
                 'this session', 'in this video')

def sentence_expression(text, is_first, is_last):
    """Rule-based expression director: what face should the presenter make
    while saying this sentence? Subtle, professional, context-aware."""
    tl = text.lower().strip()
    if tl.endswith('?'):
        return 'question'
    if is_first or any(w in tl for w in _EXPR_WELCOME):
        return 'welcome'
    if any(w in tl for w in _EXPR_CONCERN):
        return 'concern'
    if is_last or any(w in tl for w in ('in summary', 'to conclude',
                                        'in conclusion', 'thank you')):
        return 'confident'
    if any(w in tl for w in _EXPR_POSITIVE):
        return 'positive'
    if any(w in tl for w in _EXPR_FOCUS):
        return 'focused'
    return 'neutral'


def camera_track(t0, t1, reveals, regions, cinematic):
    """AI cinematography: keyframes {t, cx, cy, s} — slow establishing drift,
    gentle focus moves toward newly revealed regions, settle wide at the end."""
    cams = [{'t': t0, 'cx': .5, 'cy': .5, 's': 1.0}]
    if not cinematic:
        return cams
    settle = max(t0 + 1.0, t1 - 2.2)
    focusables = []
    for r in reveals:
        reg = regions[r['state'] - 1] if regions and 0 < r['state'] <= len(regions) else None
        if reg and r['t'] < settle - 1.2:
            focusables.append((r['t'], reg))
    if not focusables:
        # simple establishing push-in and settle
        cams.append({'t': t0 + 1.2, 'cx': .5, 'cy': .5, 's': 1.008})
        cams.append({'t': settle, 'cx': .5, 'cy': .5, 's': 1.035})
        cams.append({'t': t1, 'cx': .5, 'cy': .5, 's': 1.0})
        return cams
    for (tr, reg) in focusables:
        x0, y0, x1, y1 = reg
        cx = min(.68, max(.32, (x0 + x1) / 2))
        cy = min(.68, max(.32, (y0 + y1) / 2))
        span = max(x1 - x0, (y1 - y0) * 16 / 9)
        s = 1.035 if span < .5 else 1.02
        # blend focus point strongly toward center so branding never crops hard
        cx = .5 + (cx - .5) * .3
        cy = .5 + (cy - .5) * .3
        cams.append({'t': max(t0 + .4, tr - .1), 'cx': cx, 'cy': cy, 's': s})
    cams.append({'t': settle, 'cx': .5, 'cy': .5, 's': 1.012})
    cams.append({'t': t1, 'cx': .5, 'cy': .5, 's': 1.0})
    # keep keyframes ordered and >=0.8s apart
    out = [cams[0]]
    for k in cams[1:]:
        if k['t'] - out[-1]['t'] >= 0.8:
            out.append(k)
    return out


def build_timeline(project, state_urls, fps, width, height, progress_cb=None,
                   manifest=None):
    """Synthesize all audio + assemble timeline JSON.
    Returns (timeline_dict, master_samples, sr)."""
    slides_cfg = project['slides']
    n = len(slides_cfg)
    all_audio = []
    sr = 22050
    t_cursor = 0.0
    tl_slides = []
    for i, sc in enumerate(slides_cfg):
        if progress_cb:
            progress_cb('voice', i / max(1, n), f'Synthesizing narration {i+1}/{n}')
        script = (sc.get('script') or '').strip() or f"Slide {i+1}."
        voice = sc.get('voice') or project.get('voice', 'sofia')
        speed = float(sc.get('speed', 1.0))
        gap = float(sc.get('pause', 0.3))
        res = tts.synth_slide(script, voice_id=voice, speed=speed,
                              sentence_gap=0.24 + gap * 0.4,
                              lead_in=0.5 if i == 0 else 0.55,
                              tail=0.55 + gap)
        states = state_urls[i]
        K = len(states) - 1
        sents = res['sentences']
        N = len(sents)
        gtexts = (manifest[i].get('texts') if manifest and i < len(manifest)
                  else None) or [''] * K
        reveals = []
        if K > 0 and N > 0:
            # narration-driven timing over a FIXED reading order: each element
            # takes the globally best-matching sentence; silent units (dots,
            # containers, lines) never consume a sentence; monotonic reveal
            # times come from a cascade clamp, so a script that mentions
            # things out of reading order degrades to a smooth cascade
            # instead of bunching everything at the slide end.
            sent_t = []                     # matched sentence start or None
            for g in range(K):
                toks = [w for w in re.findall(r'[a-z0-9]{4,}',
                                              (gtexts[g] if g < len(gtexts) else '').lower())
                        if w not in STOPWORDS][:12]
                idx = None
                if toks:
                    scores = [sum(1 for tok in toks if tok in s['text'].lower())
                              for s in sents]
                    if max(scores) > 0:
                        thr = max(1.0, max(scores) * 0.5)
                        idx = next(j for j, sc_ in enumerate(scores)
                                   if sc_ >= thr)
                sent_t.append(sents[idx]['t0'] if idx is not None else None)
            t_rev = []
            for g, st_ in enumerate(sent_t):
                tt = (t_cursor + max(0.0, st_ - 0.12)) if st_ is not None \
                    else (t_rev[-1] + 0.55 if t_rev else t_cursor + 0.6)
                if not t_rev:
                    tt = min(tt, t_cursor + 2.0)   # never open on an empty slide
                elif tt < t_rev[-1] + 0.55:
                    tt = t_rev[-1] + 0.55
                t_rev.append(tt)
            # end clamp + backward de-collision: when the cascade would pile
            # up at the slide end, spread reveals backward with an adaptive
            # gap so they stay strictly increasing (no jump-cut pile-ups)
            t_end = t_cursor + res['duration'] - 0.9
            min_gap = min(0.55, max(0.18,
                                    (t_end - t_cursor - 0.6) / max(1, K)))
            t_rev = [min(tt, t_end) for tt in t_rev]
            for g in range(len(t_rev) - 2, -1, -1):
                if t_rev[g] > t_rev[g + 1] - min_gap:
                    t_rev[g] = max(t_cursor + 0.3, t_rev[g + 1] - min_gap)
            reveals = [{'t': round(tt, 3), 'state': g + 1}
                       for g, tt in enumerate(t_rev)]
        sentences = []
        used_kw = set()
        hits = []                 # cinematic keyword pops, word-accurate
        recent_hit = {}           # brand -> last time shown (de-dupe repeats)
        for j, sn in enumerate(sents):
            kw = pick_keyword(sn['text'])
            if kw.lower() in used_kw or len(sn['text'].split()) < 4:
                kw = ''
            if kw:
                used_kw.add(kw.lower())
            words = sn['words']
            wnorm = [re.sub(r'[^a-z0-9+-]', '', w['w'].lower()) for w in words]
            # brand mentions fire a hit at the exact moment the word is spoken
            brand_in_sentence = False
            k = 0
            while k < len(words):
                name = None
                span = 1
                if k + 1 < len(words):
                    two = wnorm[k] + ' ' + wnorm[k + 1]
                    if two in BRANDS:
                        name, span = two, 2
                if name is None and wnorm[k] in BRANDS:
                    name = wnorm[k]
                if name:
                    brand_in_sentence = True
                    t_h = t_cursor + words[k]['t0']
                    if t_h - recent_hit.get(name, -9.0) > 5.0:
                        recent_hit[name] = t_h
                        label = BRAND_NAMES.get(name) or ' '.join(
                            w['w'].strip('.,:;!?()"\'') for w in words[k:k + span])
                        c1, c2 = BRANDS[name]
                        hits.append({'t': round(t_h, 3), 'text': label,
                                     'c1': c1, 'c2': c2, 'brand': True})
                    k += span
                else:
                    k += 1
            # otherwise the sentence's key concept pops with the default glow
            if not brand_in_sentence and kw:
                first = re.sub(r'[^a-z0-9+-]', '', kw.split()[0].lower())
                t_h = None
                for wi, wt in enumerate(wnorm):
                    if wt == first:
                        t_h = t_cursor + words[wi]['t0']
                        break
                if t_h is None:
                    t_h = t_cursor + sn['t0'] + 0.25
                hits.append({'t': round(t_h, 3), 'text': kw,
                             'c1': DEFAULT_GLOW[0], 'c2': DEFAULT_GLOW[1],
                             'brand': False})
            sentences.append({
                'text': sn['text'],
                't0': round(t_cursor + sn['t0'], 3),
                't1': round(t_cursor + sn['t1'], 3),
                'words': [{'w': w['w'], 't0': round(t_cursor + w['t0'], 3),
                           't1': round(t_cursor + w['t1'], 3)} for w in sn['words']],
                'keyword': kw,
                'expr': sentence_expression(sn['text'],
                                            is_first=(i == 0 and j == 0),
                                            is_last=(i == n - 1 and
                                                     j == len(sents) - 1)),
            })
        # each hit holds until shortly before the next one (or ~2.6s max)
        hits.sort(key=lambda h: h['t'])
        for hi, h in enumerate(hits):
            nxt = hits[hi + 1]['t'] - 0.15 if hi + 1 < len(hits) else 1e9
            h['t1'] = round(min(h['t'] + 2.6, max(nxt, h['t'] + 1.1)), 3)
        dur = res['duration']
        trans = sc.get('transition', 'auto')
        if trans == 'auto':
            trans = (plan_transition(i, n, manifest) if manifest
                     else auto_transition(i, n, K))
        regions = None
        if manifest and i < len(manifest):
            regions = manifest[i].get('regions')
        cinematic = project.get('cinematic', True)
        cams = camera_track(t_cursor, t_cursor + dur, reveals, regions, cinematic)
        # active element system: sentence-driven speech-visual synchronization
        actives = []
        mi = manifest[i] if manifest and i < len(manifest) else {}
        gsizes = mi.get('gsizes') or []
        gtexts = mi.get('texts') or []
        roles = mi.get('roles') or []
        layout = mi.get('layout') or ''
        fxs = entrance_plan(regions or [], gsizes, gtexts=gtexts,
                            roles=roles, layout=layout)
        for r_ in reveals:
            gi = r_['state'] - 1
            if 0 <= gi < len(fxs):
                r_['fx'] = fxs[gi]
        if project.get('highlightSweeps', True) and regions:
            slide_end = t_cursor + dur
            for sn in sentences:
                stext = sn['text'].lower()
                best_gi = None
                best_score = 0
                for gi, gt in enumerate(gtexts):
                    if not gt.strip(): continue
                    toks = [w for w in re.findall(r'[a-z0-9]{4,}', gt.lower()) if w not in STOPWORDS]
                    if not toks: continue
                    score = sum(1 for tok in toks if tok in stext)
                    if score > best_score:
                        best_score = score
                        best_gi = gi

                if best_gi is not None and best_gi < len(regions):
                    reg = regions[best_gi]
                    gt = gtexts[best_gi].lower()
                    w, h = reg[2] - reg[0], reg[3] - reg[1]
                    if w * h > 0.45:
                        continue          # containers/backdrops don't lift
                    role = roles[best_gi] if best_gi < len(roles) else 'card'
                    subTarget = {
                        'marker': 'marker', 'tool': 'tool', 'kpi': 'tool',
                        'bullet': 'bullet', 'heading': 'heading',
                    }.get(role, 'card')
                    if role in ('line', 'container'):
                        continue          # backbones/backdrops never lift
                    if subTarget == 'card' and _brand_mentioned(gt):
                        subTarget = 'tool'   # brand items: clean borderless pop
                    if subTarget == 'card' and len(sn['text'].split()) <= 6:
                        subTarget = 'heading'   # short intro line: light touch

                    a0 = max(t_cursor, sn['t0'] - 0.05)
                    a1 = min(slide_end - 0.1, sn['t1'] + 0.15)
                    if a1 - a0 < 0.5:
                        a1 = a0 + 0.5
                    cx = (reg[0] + reg[2]) / 2
                    cy = (reg[1] + reg[3]) / 2
                    gaze = 'right' if cx <= 0.5 else 'left'
                    actives.append({
                        't0': round(a0, 3), 't1': round(a1, 3),
                        'bbox': reg, 'state': best_gi + 1,
                        'subTarget': subTarget,
                        'cx': round(cx, 3), 'cy': round(cy, 3),
                        'gazeDir': gaze
                    })

            if not actives:
                for gi, r in enumerate(reveals):
                    reg = regions[r['state'] - 1] if 0 < r['state'] <= len(regions) else None
                    if not reg or (reg[2] - reg[0]) * (reg[3] - reg[1]) > 0.45:
                        continue
                    a0 = r['t'] + 0.1
                    a1 = (reveals[gi + 1]['t'] - 0.35) if gi + 1 < len(reveals) \
                         else slide_end - 1.1
                    if a1 - a0 < 1.0:
                        a1 = a0 + 1.0
                    cx = (reg[0] + reg[2]) / 2
                    cy = (reg[1] + reg[3]) / 2
                    gaze = 'right' if cx <= 0.5 else 'left'
                    actives.append({
                        't0': round(a0, 3), 't1': round(min(a1, slide_end - 0.6), 3),
                        'bbox': reg, 'state': r['state'], 'subTarget': 'card',
                        'cx': round(cx, 3), 'cy': round(cy, 3),
                        'gazeDir': gaze})
        # reading order is sacred: an element is never shown (even as an
        # emphasis crop) before its reveal. If the narration mentions it
        # early, the emphasis simply starts when the element lands.
        rev_t = {r['state']: r['t'] for r in reveals}
        kept = []
        for a in actives:
            rt = rev_t.get(a['state'])
            if rt is not None and a['t0'] < rt + 0.85:
                a['t0'] = round(rt + 0.85, 3)     # after the entrance settles
            if a['t1'] < a['t0'] + 0.5:
                a['t1'] = round(a['t0'] + 0.5, 3)
            if a['t0'] < t_cursor + dur - 0.6:
                kept.append(a)
        actives = kept
        tl_slides.append({
            't0': round(t_cursor, 3), 't1': round(t_cursor + dur, 3),
            'transition': trans, 'states': states,
            'reveals': reveals, 'sentences': sentences,
            'cams': cams, 'sweeps': [], 'actives': actives,
            'hits': hits, 'regions': regions or [],
            'gsizes': gsizes, 'layout': layout, 'roles': roles,
        })
        all_audio.append(res['samples'])
        t_cursor += dur
    master = np.concatenate(all_audio) if all_audio else np.zeros(sr, dtype=np.float32)
    aspect = None
    if manifest:
        for m in manifest:
            if m.get('aspect'):
                aspect = m['aspect']
                break
    timeline = {
        'width': width, 'height': height, 'fps': fps,
        'slideAspect': aspect,
        'total': round(t_cursor, 3),
        'subtitleStyle': project.get('subtitleStyle', 'professional'),
        'showSubtitles': project.get('showSubtitles', False),
        'showKeywords': project.get('showKeywords', True),
        'showProgress': project.get('showProgress', False),
        'cinematic': project.get('cinematic', True),
        'avatar': project.get('avatar', {'id': 'maya', 'x': 0.855, 'y': 0.80,
                                         'size': 0.24, 'visible': True}),
        'avatarOpts': project.get('avatarOpts',
                                  {'energy': .6, 'smile': .5, 'gesture': .5, 'eye': .75}),
        'slides': tl_slides,
    }
    return timeline, master, sr


# ------------------------------------------------------------- audio design

def _lowpass(x, sr, cutoff):
    from scipy.signal import butter, lfilter
    b, a = butter(2, cutoff / (sr / 2), btype='low')
    return lfilter(b, a, x).astype(np.float32)


def music_bed(duration, sr):
    """Very subtle corporate/technology pad: slow soft chords, heavily
    low-passed, sits far below the narration."""
    CHORDS = [  # frequencies (Hz)
        [130.81, 196.00, 246.94, 329.63],   # Cmaj7-ish
        [110.00, 164.81, 220.00, 261.63],   # Am7
        [ 87.31, 174.61, 220.00, 261.63],   # Fmaj7
        [ 98.00, 146.83, 196.00, 293.66],   # G
    ]
    seg = 9.0
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float32)
    t_all = np.arange(n) / sr
    for ci in range(int(math.ceil(duration / seg))):
        s0 = int(ci * seg * sr); s1 = min(n, int((ci + 1) * seg * sr))
        if s0 >= n:
            break
        t = t_all[s0:s1] - ci * seg
        env = np.minimum(1, t / 2.5) * np.minimum(1, (seg - t) / 2.5)
        env = np.clip(env, 0, 1)
        chord = CHORDS[ci % len(CHORDS)]
        segw = np.zeros(s1 - s0, dtype=np.float32)
        for k, f in enumerate(chord):
            vib = 1 + 0.002 * np.sin(2 * np.pi * 0.13 * t + k)
            segw += (0.5 ** k) * np.sin(2 * np.pi * f * vib * t).astype(np.float32)
        out[s0:s1] += (segw * env).astype(np.float32)
    out = _lowpass(out, sr, 900)
    peak = np.max(np.abs(out)) + 1e-6
    return out / peak


def sfx_track(duration, sr, transitions, activations):
    """Extremely subtle UI/motion sounds: soft whoosh on section changes,
    gentle pop when an element activates."""
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float32)
    rng = np.random.RandomState(7)
    # soft whoosh: band-limited noise swell, 0.55s
    wl = int(0.55 * sr)
    tw = np.arange(wl) / sr
    wenv = np.sin(np.pi * tw / 0.55) ** 2
    whoosh = _lowpass(rng.randn(wl).astype(np.float32), sr, 1400) * wenv
    whoosh /= (np.max(np.abs(whoosh)) + 1e-6)
    # gentle pop: tiny descending blip, 90ms
    pl = int(0.09 * sr)
    tp = np.arange(pl) / sr
    pop = np.sin(2 * np.pi * (720 - 260 * tp / 0.09) * tp) * np.exp(-tp * 38)
    pop = _lowpass(pop.astype(np.float32), sr, 2500)
    pop /= (np.max(np.abs(pop)) + 1e-6)
    for t in transitions:
        i = int((t - 0.2) * sr)
        if 0 <= i < n - wl:
            out[i:i + wl] += whoosh * 0.55
    for t in activations:
        i = int(t * sr)
        if 0 <= i < n - pl:
            out[i:i + pl] += pop * 0.5
    return out


def presenter_segments(timeline, manifest, width, height, default_x=0.855,
                       size=0.24):
    """Smart positioning: presenter sits opposite the slide's content focus,
    sliding smoothly at slide boundaries. Returns [(t, x_px), ...]."""
    d = size * height
    segs = []
    for i, sl in enumerate(timeline['slides']):
        regions = (manifest[i].get('regions') if manifest and i < len(manifest)
                   else None) or []
        frac = default_x
        if regions:
            # occlusion-aware: pick the bottom corner overlapping the least
            # content; content shifted to one side pushes the presenter to
            # the other
            def overlap(fx):
                cx0, cx1 = fx - size / 2 * height / width, fx + size / 2 * height / width
                cy0, cy1 = 0.80 - size / 2, 0.80 + size / 2
                a = 0.0
                for r in regions:
                    ix = max(0, min(cx1, r[2]) - max(cx0, r[0]))
                    iy = max(0, min(cy1, r[3]) - max(cy0, r[1]))
                    a += ix * iy
                return a
            lo, ro = overlap(0.145), overlap(0.855)
            if abs(lo - ro) < 1e-4:
                cx = sum((r[0] + r[2]) / 2 for r in regions) / len(regions)
                frac = 0.145 if cx > 0.5 else 0.855
            else:
                frac = 0.145 if lo < ro else 0.855
        segs.append((sl['t0'], frac * width - d / 2))
    # merge consecutive identical positions
    merged = [segs[0]]
    for t, x in segs[1:]:
        if abs(x - merged[-1][1]) > 2:
            merged.append((t, x))
    return merged


QUALITY = {
    'fast':     {'crf': 23, 'preset': 'veryfast', 'jpeg': 80},
    'balanced': {'crf': 20, 'preset': 'medium',   'jpeg': 88},
    'studio':   {'crf': 17, 'preset': 'slow',     'jpeg': 92},
}


def render_video(project, state_paths, outdir, progress_cb=None, manifest=None,
                 presenter_footage=None):
    """Full render. state_paths: per-slide list of absolute png paths.
    If presenter_footage is set (photoreal mode), the stage is rendered
    without the animated avatar and the lip-synced human presenter is
    composited on top afterwards."""
    os.makedirs(outdir, exist_ok=True)
    width = int(project.get('width', 1920)); height = int(project.get('height', 1080))
    fps = int(project.get('fps', 30))
    q = QUALITY.get(project.get('quality', 'balanced'), QUALITY['balanced'])

    pconf = project.get('presenter') or {}
    photoreal = (pconf.get('mode') == 'footage' and presenter_footage
                 and os.path.exists(presenter_footage))
    # Preflight BEFORE the stage render decides the presenter path once and
    # for all: if photoreal can't work, the stage renders WITH the animated
    # avatar — the video must never end up with no presenter at all.
    if photoreal:
        import presenter as pres_mod
        ok, why = pres_mod.preflight(presenter_footage)
        if not ok:
            photoreal = False
            print(f'[render] photoreal presenter unavailable: {why}')
            if progress_cb:
                progress_cb('voice', 0.0,
                            f'Photoreal presenter unavailable ({why}) — '
                            f'falling back to the animated presenter')

    # proper file:/// URIs (forward slashes, percent-encoded). Plain
    # 'file://' + backslash-path breaks CSS url() on Windows — backslashes
    # are CSS escapes — which made reveal/emphasis crops render empty.
    import pathlib
    state_urls = [[pathlib.Path(p).as_uri() for p in lst]
                  for lst in state_paths]
    timeline, master, sr = build_timeline(project, state_urls, fps, width, height,
                                          progress_cb, manifest=manifest)
    if photoreal:
        timeline = dict(timeline)
        timeline['avatar'] = dict(timeline['avatar'], visible=False)
    else:
        timeline = dict(timeline)
        av_cfg = dict(timeline.get('avatar') or {})
        av_cfg['visible'] = True
        timeline['avatar'] = av_cfg

    # mouth envelope from the VOICE ONLY — computed before the music bed is
    # mixed in, so lips never move to background music during pauses
    mouth = tts.mouth_envelope(master, sr, fps)
    voice_path = os.path.join(outdir, 'voice.wav')
    tts.write_wav(voice_path, master, sr)   # clean voice for Wav2Lip

    # ---- audio design: subtle music bed + UI sfx under the narration
    if project.get('audioDesign', True):
        try:
            trans_times = [s['t0'] for s in timeline['slides'][1:]]
            act_times = [a['t0'] for s in timeline['slides']
                         for a in s.get('actives', [])]
            bed = music_bed(len(master) / sr, sr)
            fx = sfx_track(len(master) / sr, sr, trans_times, act_times)
            L = min(len(master), len(bed), len(fx))
            voice_rms = float(np.sqrt(np.mean(master[:L] ** 2)) + 1e-6)
            master = master.copy()
            master[:L] += bed[:L] * (voice_rms * 0.22) + fx[:L] * (voice_rms * 0.5)
            master = np.clip(master, -1.0, 1.0)
        except Exception:
            import traceback; traceback.print_exc()
    wav_path = os.path.join(outdir, 'narration.wav')
    tts.write_wav(wav_path, master, sr)
    with open(os.path.join(outdir, 'timeline.json'), 'w') as f:
        json.dump(timeline, f)

    # ---- pre-render QC: fail fast on inconsistent inputs instead of
    # producing a silently incomplete video
    try:
        import validator
        issues = validator.validate_pre(state_paths, manifest, timeline)
        for lvl, m in issues:
            print(f'[qc:{lvl}] {m}')
        fatal = [m for lvl, m in issues if lvl == 'fatal']
        if fatal:
            raise RuntimeError('Pre-render validation failed: ' +
                               '; '.join(fatal))
    except RuntimeError:
        raise
    except Exception:
        import traceback; traceback.print_exc()

    total_frames = int(math.ceil(timeline['total'] * fps))
    out_path = os.path.join(outdir, 'video.mp4')

    from playwright.sync_api import sync_playwright
    ff = subprocess.Popen([
        FFMPEG_CMD, '-y', '-loglevel', 'error',
        '-f', 'image2pipe', '-framerate', str(fps), '-c:v', 'mjpeg', '-i', '-',
        '-i', wav_path,
        '-c:v', 'libx264', '-preset', q['preset'], '-crf', str(q['crf']),
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest',
        '-movflags', '+faststart', out_path,
    ], stdin=subprocess.PIPE)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--force-color-profile=srgb',
                                           '--disable-lcd-text',
                                           '--hide-scrollbars'])
        page = browser.new_page(viewport={'width': width, 'height': height})
        import pathlib
        page.goto(pathlib.Path(STAGE).as_uri())
        page.evaluate('tl => initStage(tl)', timeline)
        page.evaluate('m => { window.MOUTH = m; }', mouth)
        page.wait_for_timeout(700)  # image decode settle
        t_start = time.time()
        for f_i in range(total_frames):
            t = f_i / fps
            page.evaluate(f'seek({t})')
            shot = page.screenshot(type='jpeg', quality=q['jpeg'])
            ff.stdin.write(shot)
            if progress_cb and f_i % 15 == 0:
                el = time.time() - t_start
                rate = (f_i + 1) / max(el, 0.01)
                eta = (total_frames - f_i) / max(rate, 0.01)
                progress_cb('render', f_i / total_frames,
                            f'Rendering frame {f_i}/{total_frames} — ETA {int(eta)}s')
        browser.close()
    ff.stdin.close()
    ff.wait()

    if photoreal:
        import presenter as pres
        stage_path = os.path.join(outdir, 'stage.mp4')
        os.replace(out_path, stage_path)
        av = project.get('avatar', {})
        segs = None
        if project.get('smartPosition', True):
            segs = presenter_segments(timeline, manifest, width, height,
                                      default_x=av.get('x', 0.855),
                                      size=av.get('size', 0.24))

        def _composite(presenter_mp4):
            pres.composite_presenter(
                stage_path, presenter_mp4, out_path, width, height,
                pos_x=av.get('x', 0.855), pos_y=av.get('y', 0.80),
                size=av.get('size', 0.24),
                shape=pconf.get('shape', 'circle'),
                zoom=float(pconf.get('zoom', 1.0)),
                offset_y=float(pconf.get('offsetY', 0.0)),
                segments=segs)

        synced = os.path.join(outdir, 'presenter_synced.mp4')
        try:
            if progress_cb:
                progress_cb('lipsync', 0, 'Lip-syncing your presenter (AI)…')
            pres.lipsync(presenter_footage, voice_path, synced,
                         progress_cb=progress_cb)
            if progress_cb:
                progress_cb('composite', 0.5, 'Compositing presenter…')
            _composite(synced)
        except Exception as e:
            import traceback; traceback.print_exc()
            # Presenter must still appear: composite the raw (un-synced)
            # footage loop rather than shipping a presenter-less video.
            try:
                if progress_cb:
                    progress_cb('composite', 0.3,
                                f'Lip-sync failed ({e}) — compositing presenter '
                                f'without lip-sync')
                raw_loop = os.path.join(outdir, 'presenter_raw.mp4')
                pres.loop_silent(presenter_footage, timeline['total'], raw_loop)
                _composite(raw_loop)
            except Exception as e2:
                import traceback; traceback.print_exc()
                os.replace(stage_path, out_path)  # last resort: stage only
                if progress_cb:
                    progress_cb('render', 0.99,
                                f'Presenter compositing failed ({e2}); '
                                f'exported without presenter')
        # confirm the presenter actually landed in the frame
        if os.path.exists(stage_path) and os.path.exists(out_path):
            try:
                import validator
                ok, msg = validator.verify_presenter_composited(
                    stage_path, out_path, timeline, av, segs)
                if not ok and progress_cb:
                    progress_cb('composite', 0.95,
                                f'Warning: presenter check failed — {msg}')
            except Exception:
                import traceback; traceback.print_exc()

    # ---- post-render QC report (duration, resolution, audio, warnings)
    try:
        import validator
        validator.validate_post(out_path, timeline, outdir)
    except Exception:
        import traceback; traceback.print_exc()
    if progress_cb:
        progress_cb('done', 1.0, 'Render complete')
    return out_path, timeline
