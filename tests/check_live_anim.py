"""Check the live iw3 stream of anim_window.py for torn frames and mismatched eyes.

Start anim_window.py and iw3 on it first (port given below, default 1313), then:
  python -I check_live_anim.py [port] [frames] [out folder]
Reads the barcodes (frame numbers) at the top and bottom of each eye. A frame whose top and
bottom numbers differ is torn (parts of two game frames); left/right differing means the two
eyes come from different game frames. Saves the first few stream frames as JPEG if a folder is given.
"""
import io
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

BITS, BW, BH = 16, 64, 24


def frames(port, count):
    r = urllib.request.urlopen(f"http://127.0.0.1:{port}/stream.jpg", timeout=10)
    buf = b""
    got = 0
    while got < count:
        buf += r.read(65536)
        while True:
            a = buf.find(b"\xff\xd8")
            b = buf.find(b"\xff\xd9", a + 2)
            if a < 0 or b < 0:
                break
            yield buf[a:b + 2]
            buf = buf[b + 2:]
            got += 1
            if got >= count:
                return


def read_code(gray, y):
    n = 0
    for b in range(BITS):
        if gray[y + BH // 2, b * BW + BW // 2] > 127:
            n |= 1 << b
    return n


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1313
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    out = sys.argv[3] if len(sys.argv) > 3 else None
    torn = mismatched = 0
    seen = []
    for i, jpg in enumerate(frames(port, count)):
        img = Image.open(io.BytesIO(jpg))
        gray = np.asarray(img.convert("L"))
        h, w2 = gray.shape
        w = w2 // 2
        codes = []
        for eye in (gray[:, :w], gray[:, w:]):
            codes.append((read_code(eye, 0), read_code(eye, h - BH)))
        (lt, lb), (rt, rb) = codes
        if lt != lb or rt != rb:
            torn += 1
        if lt != rt:
            mismatched += 1
        seen.append(lt)
        if out and i < 8:
            os.makedirs(out, exist_ok=True)
            img.save(os.path.join(out, f"live_{i:02d}.jpg"))
    steps = np.diff(seen)
    print(f"{count} stream frames: torn {torn}, eyes from different frames {mismatched}; "
          f"game frames advanced per stream frame: median {np.median(steps):.0f}, "
          f"repeats {int((steps == 0).sum())}, backwards {int((steps < 0).sum())}")


if __name__ == "__main__":
    main()
