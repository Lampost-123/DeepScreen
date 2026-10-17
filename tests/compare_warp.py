"""Compare iw3 stereo warp methods on a generated animation (never the user's own media).

Scene: a static grid room (walls and floor, so warping bends straight lines) with a figure that
sways and bobs, like a visual novel character animation. For each method it reports:
  - ms/frame for the whole 3D step (depth + warp)
  - background wobble: mean change of the 3D eye images, between frames, where the source picture
    did not change and is more than 48 px from anything that did (should be 0: a still
    background must stay still)
  - edge drag: the same, but in the 48 px band around the moving figure, minus the source's own
    change there (background pulled along by the figure)
and saves tests/media/compare_warp.png: the left eye of each method at the same frame.
Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d\\tests\\compare_warp.py [divergence] [config ...]
  config = "name=iw3 args", e.g. "dilate4=--edge-dilation 4"; default: row_flow_v3 vs mlbw_l2.
"""
import os
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, r"D:\nunif")
from iw3 import utils as IW3U  # noqa: E402
from iw3.desktop.utils import create_parser, set_state_args, init_win32  # noqa: E402

CONFIGS = ["row_flow_v3=--method row_flow_v3", "mlbw_l2=--method mlbw_l2"]
W, H, FRAMES = 1280, 720, 90
BAND = 48


def make_frames():
    room = np.zeros((H, W, 3), np.uint8)
    room[:] = (70, 90, 120)
    horizon = int(H * 0.62)
    room[horizon:] = (60, 70, 85)
    for x in range(0, W + 1, 64):  # back wall verticals
        cv2.line(room, (x, 0), (x, horizon), (200, 210, 230), 2)
    for y in range(0, horizon, 64):
        cv2.line(room, (0, y), (W, y), (200, 210, 230), 2)
    vx = W // 2
    for x in range(-W, 2 * W, 96):  # floor lines converge to the middle: perspective depth
        cv2.line(room, (vx + (x - vx) // 6, horizon), (x, H), (180, 190, 200), 2)
    for k in range(1, 8):
        y = horizon + int((H - horizon) * (k / 8) ** 1.6)
        cv2.line(room, (0, y), (W, y), (180, 190, 200), 2)
    frames = []
    for i in range(FRAMES):
        img = room.copy()
        t = i / 30
        cx = int(W / 2 + 120 * np.sin(t * 2.2))
        cy = int(H * 0.52 + 12 * np.sin(t * 4.4))
        for r, c in ((150, (90, 120, 200)), (120, (110, 150, 230))):  # shaded body
            cv2.ellipse(img, (cx, cy + 120), (r // 2 + 20, r + 40), 0, 0, 360, c, -1)
        cv2.circle(img, (cx, cy - 70), 55, (150, 190, 240), -1)  # head
        cv2.circle(img, (cx - 12, cy - 82), 30, (175, 210, 250), -1)  # highlight
        frames.append(torch.from_numpy(img[:, :, ::-1].copy()).permute(2, 0, 1).float().div(255).cuda())
    return frames


def setup(extra, divergence):
    args = create_parser().parse_args(["--depth-model", "Any_V2_S", "--full-sbs", "--resolution", "518",
                                       "--divergence", str(divergence)] + extra.split())
    set_state_args(args)
    dm = args.state["depth_model"]
    dm.load(gpu=args.gpu, resolution=args.resolution, limit_resolution=args.limit_resolution)
    dm.enable_ema(args.ema_decay, buffer_size=1)
    args.mapper = IW3U.resolve_mapper_name(mapper=args.mapper, foreground_scale=args.foreground_scale,
                                           metric_depth=dm.is_metric())
    side = IW3U.create_stereo_model(args.method, divergence=args.divergence, device_id=args.gpu[0])
    return args, dm, side


def main():
    init_win32()
    divergence = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    frames = make_frames()
    moved = []
    for i in range(1, FRAMES):
        m = ((frames[i] - frames[i - 1]).abs().amax(0) > 0.01).float()[None, None]
        near = F.max_pool2d(m, 2 * BAND + 1, stride=1, padding=BAND)[0, 0] > 0
        moved.append((m[0, 0] > 0, near))
    shots = []
    for config in (sys.argv[2:] or CONFIGS):
        method, extra = config.split("=", 1)
        args, dm, side = setup(extra, divergence)
        with torch.inference_mode():
            for f in frames[:5]:
                IW3U.process_image(f, args, dm, side, autocrop_uncrop=True)
            dm.reset()
            torch.cuda.synchronize()
            t = time.perf_counter()
            outs = [IW3U.process_image(f, args, dm, side, autocrop_uncrop=True).float() for f in frames]
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t) / FRAMES * 1000
        wobble, drag = [], []
        for i in range(1, FRAMES):
            changed, near = moved[i - 1]
            band = near & ~changed
            for half in (slice(0, W), slice(W, 2 * W)):
                a, b = outs[i - 1][:, :, half], outs[i][:, :, half]
                d = (a - b).abs().amax(0)
                wobble.append(d[~near].mean().item())
                drag.append(d[band].mean().item())
        print(f"{method:12s} div {divergence}: {ms:5.1f} ms/frame, background wobble {np.mean(wobble) * 100:.3f}%, "
              f"edge drag {np.mean(drag) * 100:.2f}%", flush=True)
        left = outs[FRAMES // 2][:, :, :W]
        shots.append((method, (left.clamp(0, 1).permute(1, 2, 0).cpu().numpy()[:, :, ::-1] * 255).astype(np.uint8)))
        del dm, side, outs
        torch.cuda.empty_cache()
    row = []
    for name, img in shots:
        img = img[H // 6:H * 5 // 6, W // 5:W * 4 // 5].copy()
        cv2.putText(img, name, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        row.append(img)
    out = os.path.join(HERE, "media", "compare_warp.png")
    cv2.imwrite(out, np.hstack(row))
    print(out)


if __name__ == "__main__":
    main()
