"""Generate a synthetic test video (never use the user's own media for tests).

640x360, 30 fps, 60 s: a frame counter and clock, plus a ball moving in front of a gradient
background, so seeking, playback and depth are easy to check.
Run: python -I make_test_clip.py [out.mp4]
"""
import os
import sys

import cv2
import numpy as np

W, H, FPS, SECONDS = 640, 360, 30, 60


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                               "media", "test_clip.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    grad = np.tile(np.linspace(40, 140, W, dtype=np.uint8), (H, 1))
    for i in range(FPS * SECONDS):
        img = cv2.merge([grad, grad // 2, 255 - grad])
        t = i / FPS
        x = int(W / 2 + 200 * np.sin(t))
        cv2.circle(img, (x, H // 2 + 40), 50, (40, 220, 255), -1)
        cv2.putText(img, f"{int(t // 60):02d}:{t % 60:05.2f}  frame {i}", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
        vw.write(img)
    vw.release()
    print(out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
