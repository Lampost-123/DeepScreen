"""Compare what the Ren'Py hook sends with what the game shows.

Records the hook's layers for a few seconds (layer_client.py), grabs the game window with
PrintWindow, rebuilds the frame from the newest capture's layers, and saves
tests/layer_dump/compare.png: game window on top, rebuilt-from-layers below.
Usage: python -I compare_layers.py "Window title"
"""
import ctypes
import ctypes.wintypes as wt
import glob
import os
import re
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, "layer_dump")
sys.path.insert(0, os.path.dirname(HERE))
from window_crop import find_window  # noqa: E402


def grab_window(title):
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    h = find_window(title)
    r = wt.RECT()
    u.GetClientRect(h, ctypes.byref(r))
    w, hh = r.right, r.bottom
    hdc = u.GetDC(h)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, hh)
    g.SelectObject(mdc, bmp)
    u.PrintWindow(h, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT (works while covered)

    class BIH(ctypes.Structure):
        _fields_ = [("a", wt.DWORD), ("w", wt.LONG), ("h", wt.LONG), ("p", wt.WORD), ("b", wt.WORD),
                    ("c", wt.DWORD), ("s", wt.DWORD), ("x", wt.LONG), ("y", wt.LONG), ("u", wt.DWORD),
                    ("i", wt.DWORD)]

    bi = BIH(ctypes.sizeof(BIH), w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * hh * 4)
    g.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(h, hdc)
    return Image.frombuffer("RGB", (w, hh), buf, "raw", "BGRX", 0, 1)


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "My Game"
    os.makedirs(DUMP, exist_ok=True)
    for f in glob.glob(os.path.join(DUMP, "*")):
        os.remove(f)
    out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "layer_client.py"), "1305", "5", DUMP],
                         capture_output=True, text=True).stdout
    game = grab_window(title)
    lines = [ln for ln in out.splitlines() if ln.startswith("seq ")]
    if not lines:
        sys.exit("no captures received (is the game running with the hook and a viewer connected?)")
    last = lines[-1]
    seq = int(last.split()[1])
    W, H = map(int, last.split()[2].rstrip(":").split("x"))
    canvas = Image.new("RGB", (W, H), (255, 0, 255))
    # "key[kind] WxH@X,Y SIZEKB [+mask]" entries, in draw order
    for key, w, h, x, y in re.findall(r"(\S+)\[\w+\] (\d+)x(\d+)@(-?\d+),(-?\d+)", last):
        name = key.replace(":", "_")
        path = os.path.join(DUMP, "%04d_%s.png" % (seq, name))
        if not os.path.exists(path):
            matches = sorted(glob.glob(os.path.join(DUMP, "*_%s.png" % name)))
            if not matches:
                continue
            path = matches[-1]  # unchanged layers are only saved when they change
        c = Image.open(path).convert("RGB").resize((int(w), int(h)))
        m = path.replace(".png", "_mask.png")
        if os.path.exists(m):
            canvas.paste(c, (int(x), int(y)), Image.open(m).convert("L").resize(c.size))
        else:
            canvas.paste(c, (int(x), int(y)))
    print(last[:300])
    top = game.resize((960, 540))
    bottom = canvas.resize((960, 540))
    cmp = Image.new("RGB", (960, 1080))
    cmp.paste(top, (0, 0))
    cmp.paste(bottom, (0, 540))
    cmp.save(os.path.join(DUMP, "compare.png"))
    print("saved", os.path.join(DUMP, "compare.png"))


if __name__ == "__main__":
    main()
