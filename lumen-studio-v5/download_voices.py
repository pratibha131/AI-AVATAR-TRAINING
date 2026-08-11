"""Download the neural voice models (~250 MB total) from the official
rhasspy/piper GitHub releases into ./voices/. Run once before first use."""
import os, tarfile, urllib.request

VOICES = [
    'voice-en-us-lessac-medium.tar.gz',       # Sofia — warm professional (F, US)
    'voice-en-us-ryan-high.tar.gz',           # Ryan  — confident presenter (M, US)
    'voice-en-gb-southern_english_female-low.tar.gz',  # Emily — friendly educator (F, UK)
]
BASE = 'https://github.com/rhasspy/piper/releases/download/v0.0.2/'
here = os.path.dirname(os.path.abspath(__file__))
vdir = os.path.join(here, 'voices')
os.makedirs(vdir, exist_ok=True)

for name in VOICES:
    tar_path = os.path.join(vdir, name)
    print('downloading', name, '…')
    urllib.request.urlretrieve(BASE + name, tar_path)
    with tarfile.open(tar_path) as t:
        t.extractall(vdir)
    os.remove(tar_path)
print('done — voices ready in', vdir)
