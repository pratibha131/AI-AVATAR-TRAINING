import shutil, os, sys

def get_ffmpeg():
    f = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if f:
        return f
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Users\Pratibha\anaconda3\Scripts\ffmpeg.exe",
        r"C:\Users\Pratibha\anaconda3\Library\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

exe = get_ffmpeg()
print("FFMPEG_EXE:", exe)
