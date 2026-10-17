"""Time each iw3 step on a real game frame, to find what limits VN3D's depth-mode FPS.

Run from D:\\nunif (iw3 must be importable):
    cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d\\tests\\bench_iw3.py "Window title"
Prints ms per frame for: 3D conversion (depth + warp) per method and stream height,
CPU vs GPU JPEG encode, and the resulting max FPS.
"""
import ctypes
import sys
import time

import torch
import torch.nn.functional as F
from PIL import ImageGrab
import torchvision.transforms.functional as TF

sys.path.insert(0, r"D:\vn3d")
sys.path.insert(0, r"D:\nunif")
import iw3_fast  # noqa: E402,F401  CUDA-graph depth model (VN3D_NO_GRAPHS=1 for stock iw3)
from window_crop import find_window  # noqa: E402
from iw3.desktop.utils import create_parser, set_state_args, init_win32, to_jpeg_data  # noqa: E402
from iw3 import utils as IW3U  # noqa: E402

N = 30


def grab_client(title):
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    hwnd = find_window(title)
    if not hwnd:
        sys.exit(f"window '{title}' not found")
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    img = ImageGrab.grab(bbox=(pt.x, pt.y, pt.x + r.right, pt.y + r.bottom), all_screens=True)
    return TF.to_tensor(img.convert("RGB"))


def timed(fn, n=N):
    for _ in range(3):
        fn()
    torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(n):
        out = fn()
    torch.cuda.synchronize()
    return (time.perf_counter() - t) / n * 1000, out


def setup(method, extra=()):
    parser = create_parser()
    args = parser.parse_args(["--depth-model", "Any_V2_S", "--divergence", "1.5", "--full-sbs",
                              "--method", method, *extra])
    set_state_args(args)
    dm = args.state["depth_model"]
    if not dm.loaded():
        dm.load(gpu=args.gpu, resolution=args.resolution, limit_resolution=args.limit_resolution)
    dm.enable_ema(args.ema_decay, buffer_size=1)
    args.mapper = IW3U.resolve_mapper_name(mapper=args.mapper, foreground_scale=args.foreground_scale,
                                           metric_depth=dm.is_metric())
    side = IW3U.create_stereo_model(args.method, divergence=args.divergence, device_id=args.gpu[0])
    return args, dm, side


def main():
    init_win32()
    title = sys.argv[1] if len(sys.argv) > 1 else "My Game"
    src = grab_client(title).cuda()
    print(f"game client area {src.shape[2]}x{src.shape[1]}, GPU {torch.cuda.get_device_name(0)}")
    heights = [1080, src.shape[1]]
    methods = sys.argv[2].split(",") if len(sys.argv) > 2 else ["row_flow", "row_flow_v3", "forward_fill"]
    for method in methods:
        try:
            args, dm, side = setup(method)
        except Exception as e:
            print(f"{method}: setup failed: {e}")
            continue
        for h in heights:
            w = round(src.shape[2] * h / src.shape[1] / 2) * 2
            frame = F.interpolate(src.unsqueeze(0), size=(h, w), mode="bilinear", antialias=True,
                                  align_corners=False).squeeze(0)
            with torch.inference_mode():
                ms, sbs = timed(lambda: IW3U.process_image(frame, args, dm, side, autocrop_uncrop=True))
            line = f"{method:13s} {w}x{h}: convert {ms:6.1f} ms"
            if method == "row_flow":
                cpu_ms, _ = timed(lambda: to_jpeg_data(sbs, quality=90, tick=0, gpu_jpeg=False), n=10)
                gpu_ms, _ = timed(lambda: to_jpeg_data(sbs, quality=90, tick=0, gpu_jpeg=True), n=10)
                line += f" | jpeg cpu {cpu_ms:5.1f} ms, gpu {gpu_ms:5.1f} ms"
            print(f"{line} -> max {1000 / ms:5.1f} fps (convert only)", flush=True)
        dm.reset()
        del side


if __name__ == "__main__":
    main()
