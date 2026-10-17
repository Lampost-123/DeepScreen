"""Measure the real left/right pixel shift in the live iw3 stream at several 3D strengths.

Sets strength over the control channel, grabs a frame from http://127.0.0.1:1303/stream.jpg,
and matches the two eye images with OpenCV block matching. Prints the near/far disparity
spread (p5..p95, in pixels of the 1922-px-wide eye image) per strength.
Run: python -I measure_disparity.py [strengths...]   (default 0.5 1 2 3 5)
"""
import io
import socket
import sys
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image

CTRL = ("127.0.0.1", 1306)


def grab():
    r = urllib.request.urlopen("http://127.0.0.1:1303/stream.jpg", timeout=5)
    buf = b""
    while buf.count(b"--frame") < 3:
        buf += r.read(65536)
    a = buf.find(b"--frame")
    b = buf.find(b"--frame", a + 7)
    c = buf.find(b"--frame", b + 7)
    part = buf[b:c]
    return np.array(Image.open(io.BytesIO(part[part.find(b"\xff\xd8"):])).convert("L"))


def disparity(im):
    w = im.shape[1] // 2
    left, right = im[:, :w], im[:, w:]
    sgbm = cv2.StereoSGBM_create(minDisparity=-64, numDisparities=128, blockSize=7,
                                 P1=8 * 49, P2=32 * 49, uniquenessRatio=5)
    d = sgbm.compute(left, right).astype(np.float32) / 16.0
    valid = d > -64
    return d[valid]


def main():
    strengths = [float(s) for s in sys.argv[1:]] or [0.5, 1.0, 2.0, 3.0, 5.0]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for v in strengths:
        s.sendto(f"divergence {v}".encode(), CTRL)
        time.sleep(1.5)
        d = disparity(grab())
        p5, p50, p95 = np.percentile(d, [5, 50, 95])
        print(f"strength {v:3.1f}: disparity p5 {p5:6.1f}  median {p50:6.1f}  p95 {p95:6.1f}  "
              f"-> depth spread {p95 - p5:5.1f} px of 1922 ({(p95 - p5) / 19.22:.2f}% of width)", flush=True)


if __name__ == "__main__":
    main()
