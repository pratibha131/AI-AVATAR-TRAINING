import os, json
import app
import renderer

pid = 'ai_guru_v5'
d = os.path.join(app.PROJECTS, pid)
proj = app.load_project(pid)
proj['quality'] = 'fast'
app.save_project(pid, proj)

with open(os.path.join(d, 'states.json')) as f:
    states = json.load(f)

manifest = None
mpath = os.path.join(d, 'manifest.json')
if os.path.exists(mpath):
    with open(mpath) as f:
        manifest = json.load(f)

def progress_cb(stage, frac, msg):
    print(f"[{stage}] {frac*100:.1f}% - {msg}", flush=True)

out_dir = os.path.join(d, 'out')
print("Starting video rendering (fast preset)...", flush=True)
out_path, tl = renderer.render_video(proj, states, out_dir, progress_cb=progress_cb, manifest=manifest)
print("Render complete! Video output saved to:", out_path, flush=True)
