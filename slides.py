"""
Slide engine: pptx/pdf upload -> exact-fidelity slide images + progressive
"build state" images (bullet-by-bullet reveals) rendered through LibreOffice
so the original styling is preserved pixel-for-pixel.

Build states are produced by duplicating each slide inside the pptx zip and
making not-yet-revealed paragraphs fully transparent (alpha 0) — layout never
reflows, so every state is the exact original slide with later bullets hidden.
"""
import os, re, shutil, subprocess, zipfile, copy, tempfile, uuid, json
from lxml import etree
from pptx import Presentation
from pptx.util import Emu

NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}
A = NS['a']; P = NS['p']; R = NS['r']

MAX_STEPS_PER_SLIDE = 25


def _q(tag):  # a:foo -> qualified
    pfx, local = tag.split(':')
    return '{%s}%s' % (NS[pfx], local)


def _run_soffice(args, timeout=300):
    env = dict(os.environ)
    for attempt in range(3):
        try:
            subprocess.run(['soffice', '--headless', *args], check=True,
                           timeout=timeout, capture_output=True, env=env)
            return
        except subprocess.CalledProcessError:
            subprocess.run(['pkill', '-f', 'soffice'], capture_output=True)
            import time; time.sleep(2)
    raise RuntimeError('LibreOffice conversion failed')


def _num_sort_key(filename):
    m = re.search(r'\d+', filename)
    return int(m.group()) if m else 0


def pptx_to_pngs(pptx_path, outdir, dpi=110, prefix='slide'):
    os.makedirs(outdir, exist_ok=True)
    # try native PowerPoint COM export on Windows
    try:
        import win32com.client
        abs_pptx = os.path.abspath(pptx_path)
        abs_out = os.path.abspath(outdir)
        tmp_exp = os.path.join(abs_out, '_tmp_exp_' + uuid.uuid4().hex[:6])
        os.makedirs(tmp_exp, exist_ok=True)
        ppt = win32com.client.Dispatch('PowerPoint.Application')
        pres = ppt.Presentations.Open(abs_pptx, WithWindow=False)
        pres.SaveAs(tmp_exp, 18) # 18 = ppSaveAsPNG
        pres.Close()
        ppt.Quit()
        exp_files = sorted((f for f in os.listdir(tmp_exp) if f.lower().endswith(('.png', '.jpg'))), key=_num_sort_key)
        out_files = []
        for idx, fname in enumerate(exp_files):
            src = os.path.join(tmp_exp, fname)
            dst_name = f"{prefix}-{idx+1:03d}.png"
            dst = os.path.join(abs_out, dst_name)
            shutil.copy(src, dst)
            out_files.append(dst)
        shutil.rmtree(tmp_exp, ignore_errors=True)
        if out_files:
            return out_files
    except Exception as e:
        pass

    with tempfile.TemporaryDirectory() as td:
        _run_soffice(['--convert-to', 'pdf', pptx_path, '--outdir', td])
        pdfs = [f for f in os.listdir(td) if f.endswith('.pdf')]
        pdf = os.path.join(td, pdfs[0])
        subprocess.run(['pdftoppm', '-png', '-r', str(dpi), pdf,
                        os.path.join(outdir, prefix)], check=True, timeout=600)
    files = sorted((f for f in os.listdir(outdir)
                    if f.startswith(prefix + '-') and f.endswith('.png')), key=_num_sort_key)
    return [os.path.join(outdir, f) for f in files]


def pdf_to_pngs(pdf_path, outdir, dpi=110, prefix='slide'):
    os.makedirs(outdir, exist_ok=True)
    subprocess.run(['pdftoppm', '-png', '-r', str(dpi), pdf_path,
                    os.path.join(outdir, prefix)], check=True, timeout=600)
    files = sorted((f for f in os.listdir(outdir)
                    if f.startswith(prefix + '-') and f.endswith('.png')), key=_num_sort_key)
    return [os.path.join(outdir, f) for f in files]



# ---------------------------------------------------------------- extraction

def extract_slide_info(pptx_path):
    """Per slide: title, content paragraphs (in reading order), speaker notes."""
    prs = Presentation(pptx_path)
    slides = []
    for idx, slide in enumerate(prs.slides):
        title = ''
        paras = []            # list of {text, shape_id, para_idx}
        shapes_sorted = sorted(
            [sh for sh in slide.shapes if sh.has_text_frame],
            key=lambda sh: ((sh.top or 0), (sh.left or 0)))
        for sh in shapes_sorted:
            is_title = False
            try:
                if sh == slide.shapes.title:
                    is_title = True
            except Exception:
                pass
            for pi, para in enumerate(sh.text_frame.paragraphs):
                txt = ''.join(r.text for r in para.runs).strip()
                if not txt:
                    continue
                if is_title or (not title and (sh.top or 0) < prs.slide_height * 0.18):
                    if not title:
                        title = txt
                        continue
                paras.append({'text': txt, 'shape_id': sh.shape_id, 'para_idx': pi})
        notes = ''
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        slides.append({'index': idx, 'title': title, 'paragraphs': paras,
                       'notes': notes})
    return slides


def draft_script(slide_info):
    """Heuristic narration draft the user can edit (notes win if present)."""
    if slide_info['notes']:
        return slide_info['notes']
    parts = []
    if slide_info['title']:
        parts.append(f"Let's talk about {slide_info['title'].rstrip('?.! ')}.")
    for p in slide_info['paragraphs'][:8]:
        t = p['text'].rstrip()
        if len(t) < 3:
            continue
        if not re.search(r'[.!?]$', t):
            t += '.'
        parts.append(t)
    return ' '.join(parts) if parts else 'This slide speaks for itself.'


# ------------------------------------------------------- build-state engine

def _iter_body_paragraphs(sp_tree):
    """Yield (shape_el, txBody, [paragraph elements]) for non-title text shapes."""
    for sp in sp_tree.iter(_q('p:sp')):
        ph = sp.findall('.//' + _q('p:nvSpPr') + '/' + _q('p:nvPr') + '/' + _q('p:ph'))
        is_title = any(p.get('type') in ('title', 'ctrTitle') for p in ph)
        tx = sp.find(_q('p:txBody'))
        if tx is None or is_title:
            continue
        paras = tx.findall(_q('a:pPr') + '/..')  # not right; do directly
        yield sp, tx, tx.findall(_q('a:p'))


def _para_text(p_el):
    return ''.join(t.text or '' for t in p_el.iter(_q('a:t'))).strip()


def _make_transparent(p_el):
    """Make a paragraph invisible without changing layout."""
    # every run: force 0% alpha fill
    for r_el in list(p_el.iter(_q('a:r'))) + list(p_el.iter(_q('a:fld'))):
        rPr = r_el.find(_q('a:rPr'))
        if rPr is None:
            rPr = etree.SubElement(r_el, _q('a:rPr'))
            r_el.remove(rPr); r_el.insert(0, rPr)
        for fill in rPr.findall(_q('a:solidFill')):
            rPr.remove(fill)
        fill = etree.Element(_q('a:solidFill'))
        clr = etree.SubElement(fill, _q('a:srgbClr')); clr.set('val', 'FFFFFF')
        alpha = etree.SubElement(clr, _q('a:alpha')); alpha.set('val', '0')
        # attribute order: insert solidFill first child of rPr (after ln if any)
        rPr.insert(0, fill)
    # hide bullet glyph
    pPr = p_el.find(_q('a:pPr'))
    if pPr is None:
        pPr = etree.Element(_q('a:pPr'))
        p_el.insert(0, pPr)
    for tag in ('a:buChar', 'a:buAutoNum', 'a:buNone'):
        for e in pPr.findall(_q(tag)):
            pPr.remove(e)
    etree.SubElement(pPr, _q('a:buNone'))


def _hide_sp_visual(sp):
    """Make an entire shape invisible (fill, outline, effects, text) without
    touching its geometry — layout stays pixel-identical."""
    spPr = sp.find(_q('p:spPr'))
    if spPr is not None:
        for tag in ('a:solidFill', 'a:gradFill', 'a:blipFill', 'a:pattFill',
                    'a:grpFill', 'a:noFill', 'a:effectLst'):
            for e in spPr.findall(_q(tag)):
                spPr.remove(e)
        # explicit noFill overrides any style-inherited fill
        xfrm = spPr.find(_q('a:xfrm'))
        geom_idx = list(spPr).index(xfrm) + 1 if xfrm is not None else 0
        nf = etree.Element(_q('a:noFill'))
        # place after geometry elements (prstGeom/custGeom) if present
        insert_at = len(spPr)
        for i, ch in enumerate(spPr):
            if ch.tag in (_q('a:prstGeom'), _q('a:custGeom')):
                insert_at = i + 1
        spPr.insert(insert_at, nf)
        ln = spPr.find(_q('a:ln'))
        if ln is None:
            ln = etree.SubElement(spPr, _q('a:ln'))
        for tag in ('a:solidFill', 'a:gradFill', 'a:pattFill', 'a:noFill'):
            for e in ln.findall(_q(tag)):
                ln.remove(e)
        ln.insert(0, etree.Element(_q('a:noFill')))
    style = sp.find(_q('p:style'))
    if style is not None:
        sp.remove(style)
    tx = sp.find(_q('p:txBody'))
    if tx is not None:
        for p_el in tx.findall(_q('a:p')):
            _make_transparent(p_el)


def _hide_pic(pic):
    blipFill = pic.find(_q('p:blipFill'))
    if blipFill is not None:
        blip = blipFill.find(_q('a:blip'))
        if blip is not None:
            for e in blip.findall(_q('a:alphaModFix')):
                blip.remove(e)
            am = etree.SubElement(blip, _q('a:alphaModFix'))
            am.set('amt', '0')
    spPr = pic.find(_q('p:spPr'))
    if spPr is not None:
        for e in spPr.findall(_q('a:effectLst')):
            spPr.remove(e)
        ln = spPr.find(_q('a:ln'))
        if ln is not None:
            for tag in ('a:solidFill', 'a:gradFill', 'a:pattFill'):
                for e in ln.findall(_q(tag)):
                    ln.remove(e)
            ln.insert(0, etree.Element(_q('a:noFill')))


def _hide_elem(el):
    tag = etree.QName(el).localname
    if tag == 'pic':
        _hide_pic(el)
    elif tag == 'grpSp':
        for ch in el:
            ct = etree.QName(ch).localname
            if ct in ('sp', 'pic', 'grpSp', 'cxnSp'):
                _hide_elem(ch)
    else:  # sp / cxnSp
        _hide_sp_visual(el)


def _content_elems(root):
    """Direct children of spTree that are drawable elements, in z-order."""
    spTree = root.find(_q('p:cSld') + '/' + _q('p:spTree'))
    out = []
    for ch in spTree:
        t = etree.QName(ch).localname
        if t in ('sp', 'pic', 'grpSp', 'cxnSp'):
            out.append(ch)
    return out


def _elem_bbox(el, slide_w, slide_h):
    tag = etree.QName(el).localname
    pr = el.find(_q('p:grpSpPr')) if tag == 'grpSp' else el.find(_q('p:spPr'))
    if pr is None:
        return None
    xfrm = pr.find(_q('a:xfrm'))
    if xfrm is None:
        return None
    off, ext = xfrm.find(_q('a:off')), xfrm.find(_q('a:ext'))
    if off is None or ext is None:
        return None
    try:
        x, y = int(off.get('x')), int(off.get('y'))
        cx, cy = int(ext.get('cx')), int(ext.get('cy'))
        return (x / slide_w, y / slide_h, (x + cx) / slide_w, (y + cy) / slide_h)
    except (TypeError, ValueError):
        return None


def _shape_pos(sp):
    """(x, y) EMU of a shape, or None if inherited."""
    xfrm = sp.find(_q('p:spPr') + '/' + _q('a:xfrm'))
    if xfrm is None:
        return None
    off = xfrm.find(_q('a:off'))
    if off is None:
        return None
    try:
        return int(off.get('x')), int(off.get('y'))
    except (TypeError, ValueError):
        return None


def _shape_bbox(sp, slide_w, slide_h):
    """Normalized (x0,y0,x1,y1) of a shape, or None."""
    xfrm = sp.find(_q('p:spPr') + '/' + _q('a:xfrm'))
    if xfrm is None:
        return None
    off, ext = xfrm.find(_q('a:off')), xfrm.find(_q('a:ext'))
    if off is None or ext is None:
        return None
    try:
        x, y = int(off.get('x')), int(off.get('y'))
        cx, cy = int(ext.get('cx')), int(ext.get('cy'))
        return (x / slide_w, y / slide_h, (x + cx) / slide_w, (y + cy) / slide_h)
    except (TypeError, ValueError):
        return None


def plan_steps(slide_xml_bytes, slide_w=12192000, slide_h=6858000, script=None):
    """AI Motion Director layout & unit analyzer.
    Detects lines, containers, dots/icons, cards, headings, and bullet points,
    clustering them into semantic narrative units that reveal in narration sequence.
    """
    root = etree.fromstring(slide_xml_bytes)
    elems = _content_elems(root)
    
    raw_items = []
    for ei, el in enumerate(elems):
        tag = etree.QName(el).localname
        ph = el.findall('.//' + _q('p:ph'))
        if any(p.get('type') in ('title', 'ctrTitle') for p in ph):
            continue
        bb = _elem_bbox(el, slide_w, slide_h)
        if bb is None:
            continue
        x0, y0, x1, y1 = bb
        w, h, area = x1 - x0, y1 - y0, (x1 - x0) * (y1 - y0)
        
        # Header / branding band
        if y0 < 0.16 and w > 0.4:
            continue
            
        tx = el.find(_q('p:txBody'))
        texts = [_para_text(p) for p in tx.findall(_q('a:p'))] if tx is not None else []
        live = [t for t in texts if t]
        
        is_line = (w > 0.35 and h < 0.05) or tag == 'cxnSp'
        is_dot = (w < 0.15 and h < 0.15 and not live)
        spPr = el.find(_q('p:spPr'))
        has_fill = spPr is not None and any(spPr.find(_q(t)) is not None for t in ('a:solidFill', 'a:gradFill', 'a:blipFill', 'a:pattFill'))
        is_container = (area > 0.12 and not live and has_fill) or (tag == 'grpSp' and area > 0.15)
        
        if len(live) >= 3 and not is_container:
            n_live, li = len(live), 0
            for pi, t in enumerate(texts):
                if not t:
                    continue
                hh = h / n_live
                raw_items.append({
                    'kind': 'para', 'ei': ei, 'pi': pi, 'text': t,
                    'bbox': (x0, y0 + li * hh, x1, y0 + (li + 1) * hh),
                    'is_line': False, 'is_dot': False, 'is_container': False
                })
                li += 1
        else:
            raw_items.append({
                'kind': 'elem', 'ei': ei, 'pi': None, 'text': ' '.join(live),
                'bbox': bb, 'is_line': is_line, 'is_dot': is_dot, 'is_container': is_container
            })

    if not raw_items:
        return [], [], []

    containers = [it for it in raw_items if it.get('is_container')]
    lines = [it for it in raw_items if it.get('is_line')]
    dots = [it for it in raw_items if it.get('is_dot')]
    content_items = [it for it in raw_items if not it.get('is_container') and not it.get('is_line') and not it.get('is_dot')]
    
    units = []
    used = set()
    
    for ln in lines:
        units.append({'items': [ln], 'type': 'line', 'text': ln['text'] or 'timeline_line'})
        used.add(id(ln))
        
    for c in containers:
        units.append({'items': [c], 'type': 'container', 'text': c['text'] or 'section_container'})
        used.add(id(c))
        
    for d in dots:
        dx0, dy0, dx1, dy1 = d['bbox']
        dcx, dcy = (dx0 + dx1) / 2, (dy0 + dy1) / 2
        matches = []
        for ci in content_items:
            if id(ci) in used: continue
            cx0, cy0, cx1, cy1 = ci['bbox']
            ccx, ccy = (cx0 + cx1) / 2, (cy0 + cy1) / 2
            dist = ((dcx - ccx)**2 + (dcy - ccy)**2)**0.5
            if dist < 0.25:
                matches.append((dist, ci))
        matches.sort(key=lambda x: x[0])
        unit_items = [d]
        used.add(id(d))
        for _, ci in matches[:2]:
            unit_items.append(ci)
            used.add(id(ci))
        txt = ' '.join(i['text'] for i in unit_items if i.get('text'))
        units.append({'items': unit_items, 'type': 'marker_or_tool', 'text': txt})
        
    remaining = [it for it in content_items if id(it) not in used]
    headings = [it for it in remaining if len(it['text']) < 45 and not it['text'].endswith('.')]
    
    for h in headings:
        if id(h) in used: continue
        hx0, hy0, hx1, hy1 = h['bbox']
        hcx, hcy = (hx0 + hx1) / 2, (hy0 + hy1) / 2
        best = None
        best_dist = 1e9
        for c in remaining:
            if id(c) in used or c == h: continue
            cx0, cy0, cx1, cy1 = c['bbox']
            ccx, ccy = (cx0 + cx1) / 2, (cy0 + cy1) / 2
            dx = abs(hcx - ccx)
            dy_vert = cy0 - hy1
            dy_horiz = abs(hcy - ccy)
            dx_horiz = cx0 - hx1
            
            is_vert = dx < 0.22 and (-0.05 < dy_vert < 0.25)
            is_horiz = dy_horiz < 0.12 and (-0.02 < dx_horiz < 0.35)
            
            if is_vert or is_horiz:
                dist = dx + dy_vert if is_vert else dy_horiz + dx_horiz
                if dist < best_dist:
                    best_dist = dist
                    best = c
        unit_items = [h]
        used.add(id(h))
        if best:
            unit_items.append(best)
            used.add(id(best))
        txt = ' '.join(i['text'] for i in unit_items if i.get('text'))
        units.append({'items': unit_items, 'type': 'card', 'text': txt})

    for it in remaining:
        if id(it) not in used:
            units.append({'items': [it], 'type': 'item', 'text': it['text']})
            used.add(id(it))
            
    final_units = []
    for u in units:
        txt = u['text'].strip()
        if u['type'] in ('line', 'container') or txt:
            final_units.append(u)
            
    groups = [u['items'] for u in final_units]
    gboxes = []
    for g in groups:
        bs = [it['bbox'] for it in g]
        gboxes.append([min(b[0] for b in bs), min(b[1] for b in bs),
                       max(b[2] for b in bs), max(b[3] for b in bs)])
    gtexts = [' '.join(it.get('text') or '' for it in g).strip() for g in groups]
    
    if script:
        groups, gboxes, gtexts = _reorder_by_narration(groups, gboxes, gtexts, script)
        
    if len(groups) > MAX_STEPS_PER_SLIDE:
        size = -(-len(groups) // MAX_STEPS_PER_SLIDE)
        groups = [sum(groups[i:i + size], []) for i in range(0, len(groups), size)]
        gboxes = []
        for g in groups:
            bs = [it['bbox'] for it in g]
            gboxes.append([min(b[0] for b in bs), min(b[1] for b in bs),
                           max(b[2] for b in bs), max(b[3] for b in bs)])
        gtexts = [' '.join(it.get('text') or '' for it in g).strip() for g in groups]

    return groups, gboxes, gtexts


_STOP = set('''a an the and or but if then than so of to in on for with at by from
as is are was were be been being it its this that these those we you they he she
i our your their my me us him her will would can could should may might must do
does did done have has had having not no nor also very just about into over
under out up down again more most other some such only own same too today well
now here there when what which who how why all each both few many'''.split())


def _reorder_by_narration(groups, gboxes, gtexts, script):
    """Motion Director: reorder reveal groups so build states follow the
    narration's story order (Data -> Learning -> Decision, tool by tool),
    not the pptx z-order. Containers still reveal before their contents."""
    sents = [s for s in re.split(r'(?<=[.!?])\s+', script or '') if s.strip()]
    if not sents or len(groups) < 2:
        return groups, gboxes, gtexts
    lsents = [s.lower() for s in sents]

    def toks(t):
        return [w for w in re.findall(r'[a-z0-9]{4,}', (t or '').lower())
                if w not in _STOP][:14]

    keys = []
    last = -1.0
    for gi, gt in enumerate(gtexts):
        tk = toks(gt)
        scores = [sum(1 for w in tk if w in s) for s in lsents]
        idx = None
        if tk and scores and max(scores) > 0:
            thr = max(1.0, max(scores) * 0.5)
            for j, sc in enumerate(scores):
                if sc >= thr:
                    idx = j
                    break
        if idx is None:
            w = gboxes[gi][2] - gboxes[gi][0]
            h = gboxes[gi][3] - gboxes[gi][1]
            if not tk and w > 0.5 and h < max(0.09, w / 6):
                idx = -2.0      # backbone/timeline line: draws in first
            else:
                idx = last      # unmatched groups follow their predecessor
        keys.append(idx)
        last = idx
    order = sorted(range(len(groups)), key=lambda gi: (keys[gi], gi))

    def contains(a, b):
        return (a[0] <= b[0] + 0.02 and a[1] <= b[1] + 0.02 and
                a[2] >= b[2] - 0.02 and a[3] >= b[3] - 0.02 and
                (a[2] - a[0]) * (a[3] - a[1]) >
                (b[2] - b[0]) * (b[3] - b[1]) * 1.3)

    guard = 0
    changed = True
    while changed and guard < 60:
        changed = False
        guard += 1
        for j in range(len(order)):
            for i in range(j):
                if contains(gboxes[order[j]], gboxes[order[i]]):
                    order.insert(i, order.pop(j))
                    changed = True
                    break
            if changed:
                break
    return ([groups[i] for i in order], [gboxes[i] for i in order],
            [gtexts[i] for i in order])


def build_states_pptx(src_pptx, out_pptx, scripts=None):
    """Create a pptx whose slide list is every build state of every slide,
    in order. Returns manifest: list per original slide of state counts &
    revealed-paragraph plan."""
    zin = zipfile.ZipFile(src_pptx)
    names = zin.namelist()
    pres_xml = zin.read('ppt/presentation.xml')
    pres_root = etree.fromstring(pres_xml)
    rels_xml = zin.read('ppt/_rels/presentation.xml.rels')
    rels_root = etree.fromstring(rels_xml)
    ct_xml = zin.read('[Content_Types].xml')
    ct_root = etree.fromstring(ct_xml)

    # slide dimensions (for header-band detection)
    sldSz = pres_root.find(_q('p:sldSz'))
    slide_w = int(sldSz.get('cx')) if sldSz is not None else 12192000
    slide_h = int(sldSz.get('cy')) if sldSz is not None else 6858000

    # ordered original slide part names
    sldIdLst = pres_root.find(_q('p:sldIdLst'))
    rid_to_target = {rel.get('Id'): rel.get('Target')
                     for rel in rels_root}
    slide_parts = []
    for sldId in sldIdLst:
        rid = sldId.get(_q('r:id'))
        tgt = rid_to_target[rid]
        slide_parts.append('ppt/' + tgt.lstrip('/').replace('../', ''))

    manifest = []
    new_parts = {}          # part name -> bytes
    new_rels_entries = []   # (rid, target)
    new_sldids = []
    rid_counter = 9000
    sld_counter = 90000
    part_counter = 1

    for orig_idx, part in enumerate(slide_parts):
        slide_bytes = zin.read(part)
        script = (scripts[orig_idx] if scripts and orig_idx < len(scripts)
                  else None)
        groups, gboxes, gtexts = plan_steps(slide_bytes, slide_w, slide_h,
                                            script=script)
        n_states = len(groups) + 1  # state 0 .. len(groups)
        state_plan = []
        for state in range(n_states):
            root = etree.fromstring(slide_bytes)
            elems = _content_elems(root)
            # Clean up empty placeholder shapes across all states to prevent stray boxes
            for ei, el in enumerate(elems):
                tag = etree.QName(el).localname
                if tag == 'sp':
                    ph = el.findall('.//' + _q('p:ph'))
                    tx = el.find(_q('p:txBody'))
                    texts = [_para_text(p) for p in tx.findall(_q('a:p'))] if tx is not None else []
                    live = [t for t in texts if t]
                    if not live:
                        spPr = el.find(_q('p:spPr'))
                        has_fill = spPr is not None and any(spPr.find(_q(t)) is not None for t in ('a:solidFill', 'a:gradFill', 'a:blipFill', 'a:pattFill'))
                        if ph or not has_fill:
                            _hide_sp_visual(el)
            hidden = []
            for gi, group in enumerate(groups):
                if gi >= state:           # not yet revealed
                    for it in group:
                        try:
                            el = elems[it['ei']]
                            if it['kind'] == 'para':
                                tx = el.find(_q('p:txBody'))
                                _make_transparent(tx.findall(_q('a:p'))[it['pi']])
                            else:
                                _hide_elem(el)
                            hidden.append([it['ei'], it.get('pi')])
                        except Exception:
                            pass
            new_name = f'ppt/slides/slideBS{part_counter}.xml'
            new_parts[new_name] = etree.tostring(root, xml_declaration=True,
                                                 encoding='UTF-8', standalone=True)
            # rels for the new part = copy of original slide rels
            orig_rels = part.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels'
            if orig_rels in names:
                new_parts[f'ppt/slides/_rels/slideBS{part_counter}.xml.rels'] = \
                    zin.read(orig_rels)
            rid = f'rIdBS{rid_counter}'; rid_counter += 1
            new_rels_entries.append((rid, f'slides/slideBS{part_counter}.xml'))
            new_sldids.append((sld_counter, rid)); sld_counter += 1
            part_counter += 1
            state_plan.append(hidden)
        manifest.append({'orig_index': orig_idx, 'n_states': n_states,
                         'regions': gboxes, 'texts': gtexts,
                         'gsizes': [len(g) for g in groups]})

    # rewrite sldIdLst
    for child in list(sldIdLst):
        sldIdLst.remove(child)
    for (sid, rid) in new_sldids:
        el = etree.SubElement(sldIdLst, _q('p:sldId'))
        el.set('id', str(sid)); el.set(_q('r:id'), rid)
    # add relationships
    for (rid, tgt) in new_rels_entries:
        rel = etree.SubElement(rels_root, _q('rel:Relationship'))
        rel.set('Id', rid)
        rel.set('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide')
        rel.set('Target', tgt)
    # content types: ensure slide override for each new part
    for name in new_parts:
        if name.endswith('.rels'):
            continue
        ov = etree.SubElement(ct_root, _q('ct:Override'))
        ov.set('PartName', '/' + name)
        ov.set('ContentType',
               'application/vnd.openxmlformats-officedocument.presentationml.slide+xml')

    with zipfile.ZipFile(out_pptx, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            if name == 'ppt/presentation.xml':
                zout.writestr(name, etree.tostring(pres_root, xml_declaration=True,
                                                   encoding='UTF-8', standalone=True))
            elif name == 'ppt/_rels/presentation.xml.rels':
                zout.writestr(name, etree.tostring(rels_root, xml_declaration=True,
                                                   encoding='UTF-8', standalone=True))
            elif name == '[Content_Types].xml':
                zout.writestr(name, etree.tostring(ct_root, xml_declaration=True,
                                                   encoding='UTF-8', standalone=True))
            else:
                zout.writestr(name, zin.read(name))
        for name, data in new_parts.items():
            zout.writestr(name, data)
    zin.close()
    return manifest


def render_build_states(src_pptx, workdir, dpi=110, scripts=None):
    """Full pipeline: returns per-slide list of state image paths + manifest.
    scripts: optional per-slide narration used to order reveals by story."""
    os.makedirs(workdir, exist_ok=True)
    bs_pptx = os.path.join(workdir, 'build_states.pptx')
    manifest = build_states_pptx(src_pptx, bs_pptx, scripts=scripts)
    imgdir = os.path.join(workdir, 'states')
    if os.path.isdir(imgdir):
        shutil.rmtree(imgdir)
    pngs = pptx_to_pngs(bs_pptx, imgdir, dpi=dpi, prefix='st')
    out, cursor = [], 0
    for m in manifest:
        out.append(pngs[cursor:cursor + m['n_states']])
        cursor += m['n_states']
    return out, manifest
