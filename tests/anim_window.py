"""A window that plays a generated animation, for testing the live 3D pipeline on motion.

Same scene as compare_warp.py (grid room, swaying figure), 1280x720 at 60 fps, with the frame
number drawn as a 16-bit barcode (64x24 px blocks) along the top and bottom edges, so a
stream frame can be checked for tearing (top and bottom numbers differ) or for eyes from
different frames. Window title: "DeepScreen anim test". Esc or 60 s closes it.
Run: python -I anim_window.py [seconds]
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TITLE = "DeepScreen anim test"
BITS, BW, BH = 16, 64, 24


def barcode(img, n, y):
    for b in range(BITS):
        v = 255 if (n >> b) & 1 else 0
        img[y:y + BH, b * BW:(b + 1) * BW] = v


def main():
    import compare_warp as cw
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    import torch
    frames = [(f.permute(1, 2, 0).cpu().numpy()[:, :, ::-1] * 255).astype(np.uint8) for f in cw.make_frames()]
    del torch
    cv2.namedWindow(TITLE, cv2.WINDOW_AUTOSIZE)
    start = time.perf_counter()
    n = 0
    while time.perf_counter() - start < seconds:
        img = frames[(n // 2) % len(frames)].copy()  # scene at 30 fps, barcode at 60
        barcode(img, n, 0)
        barcode(img, n, img.shape[0] - BH)
        cv2.imshow(TITLE, img)
        n += 1
        wait = start + n / 60 - time.perf_counter()
        if cv2.waitKey(max(1, int(wait * 1000))) == 27:
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
