"""Compare depth models on a moving clip: speed and frame-to-frame flicker of the static background.

Uses the generated test clip (tests/make_test_clip.py: ball moving over a static gradient).
Flicker = mean absolute change of normalized depth between consecutive frames, measured only
where the picture itself didn't change (so any change there is the model's instability).
Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d\\tests\\compare_temporal.py [clip.mp4]
"""
import os
import sys
import time

import cv2
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, r"D:\nunif")
import iw3_fast  # noqa: E402,F401
from iw3.desktop.utils import create_parser, set_state_args, init_win32  # noqa: E402

MODELS = ["Any_V2_S", "VDA_Stream_S"]
FRAMES = 120


def load(model):
    args = create_parser().parse_args(["--depth-model", model, "--full-sbs", "--resolution", "518"])
    set_state_args(args)
    dm = args.state["depth_model"]
    dm.load(gpu=args.gpu, resolution=args.resolution, limit_resolution=args.limit_resolution)
    return dm


def main():
    init_win32()
    clip = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "media", "test_clip.mp4")
    cap = cv2.VideoCapture(clip)
    frames = []
    while len(frames) < FRAMES:
        ok, f = cap.read()
        if not ok:
            break
        f = cv2.resize(f, (1920, 1080))
        frames.append(torch.from_numpy(f[:, :, ::-1].copy()).permute(2, 0, 1).float().div(255).cuda())
    for model in MODELS:
        dm = load(model)
        depths = []
        with torch.inference_mode():
            for f in frames[:5]:
                dm.infer(f, tta=False, enable_amp=True, edge_dilation=0)
            if hasattr(dm, "reset"):
                dm.reset()
            torch.cuda.synchronize()
            t = time.perf_counter()
            for f in frames:
                d = dm.infer(f, tta=False, enable_amp=True, edge_dilation=0).float().squeeze()
                depths.append(d)
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t) / len(frames) * 1000
        flicker = []
        for i in range(1, len(depths)):
            a, b = depths[i - 1], depths[i]
            a = (a - a.min()) / (a.max() - a.min() + 1e-6)
            b = (b - b.min()) / (b.max() - b.min() + 1e-6)
            fa = torch.nn.functional.interpolate(frames[i - 1][None], size=a.shape, mode="area")[0]
            fb = torch.nn.functional.interpolate(frames[i][None], size=a.shape, mode="area")[0]
            static = (fa - fb).abs().amax(0) < 0.01
            if static.any():
                flicker.append((a - b).abs()[static].mean().item())
        print(f"{model:13s}: {ms:5.1f} ms/frame ({1000 / ms:5.1f} fps), background flicker {np.mean(flicker) * 100:.3f}%",
              flush=True)
        del dm


if __name__ == "__main__":
    main()
