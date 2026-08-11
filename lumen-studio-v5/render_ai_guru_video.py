import os, json
import app
import slides
import renderer

pid = 'ai_guru_v5'
d = os.path.join(app.PROJECTS, pid)
proj = app.load_project(pid)
source_pptx = os.path.join(d, 'source.pptx')

build_dir = os.path.join(d, 'build')
print("Regenerating slide build states in narration order...")
scripts = [(s.get('script') or '') for s in proj.get('slides', [])]
states, manifest = slides.render_build_states(source_pptx, build_dir, dpi=110,
                                              scripts=scripts)

with open(os.path.join(d, 'states.json'), 'w') as f:
    json.dump(states, f)

if manifest:
    with open(os.path.join(d, 'manifest.json'), 'w') as f:
        json.dump(manifest, f)

def progress_cb(stage, frac, msg):
    print(f"[{stage}] {frac*100:.1f}% - {msg}")

out_dir = os.path.join(d, 'out')
print("Starting video rendering with AI Avatar & AE Broadcast Visuals...")
out_path, tl = renderer.render_video(proj, states, out_dir, progress_cb=progress_cb, manifest=manifest)
print("Render complete! Video output saved to:", out_path)

