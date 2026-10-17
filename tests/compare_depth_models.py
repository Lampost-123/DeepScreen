"""Compare depth models / resolutions on the live game frame: depth maps side by side plus timing.

Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d-stable\\tests\\compare_depth_models.py "Window title"
Writes D:\\vn3d-stable\\tests\\depth_compare.png (frame + one depth map per config, labelled).
Note: only Depth Anything V2 models get the CUDA-graph speed-up from iw3_fast.py.
"""
import os
import sys
import time

import torch
import torch.nn.functional as F
import torchvision.transforms.functional as TF
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, r"D:\nunif")
import iw3_fast  # noqa: E402,F401
from compare_layers import grab_window  # noqa: E402
from iw3.desktop.utils import create_parser, set_state_args, init_win32  # noqa: E402

CONFIGS = [("Any_V2_S", None), ("Any_V2_S", 518), ("Any_V2_S", 770),
           ("Any_V3_Mono", None), ("Any_V3_Mono", 770)]


def depth_of(model, res, frame):
    extra = ["--resolution", str(res)] if res else []
    args = create_parser().parse_args(["--depth-model", model, "--full-sbs", *extra])
    set_state_args(args)
    dm = args.state["depth_model"]
    dm.load(gpu=args.gpu, resolution=args.resolution, limit_resolution=args.limit_resolution)
    with torch.inference_mode():
        for _ in range(3):
            d = dm.infer(frame, tta=False, enable_amp=True, edge_dilation=args.edge_dilation)
        torch.cuda.synchronize()
        t = time.perf_counter()
        for _ in range(10):
            d = dm.infer(frame, tta=False, enable_amp=True, edge_dilation=args.edge_dilation)
        torch.cuda.synchronize()
    ms = (time.perf_counter() - t) / 10 * 1000
    d = d.float().squeeze()
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)
    del dm
    args.state.clear()
    torch.cuda.empty_cache()
    return d.cpu(), ms


def main():
    init_win32()
    title = sys.argv[1] if len(sys.argv) > 1 else "My Game"
    src = TF.to_tensor(grab_window(title)).cuda()
    frame = F.interpolate(src.unsqueeze(0), size=(1080, round(src.shape[2] * 1080 / src.shape[1] / 2) * 2),
                          mode="bilinear", antialias=True, align_corners=False).squeeze(0)
    w = 800
    h = round(w * frame.shape[1] / frame.shape[2])
    tiles = [("game frame", TF.to_pil_image(frame.cpu()).resize((w, h)))]
    for model, res in CONFIGS:
        try:
            d, ms = depth_of(model, res, frame)
        except Exception as e:
            print(f"{model} @ {res or 'default'}: failed: {e}")
            continue
        label = f"{model} @ {res or 'default'}: {ms:.0f} ms ({1000 / ms:.0f} fps depth only)"
        print(label, flush=True)
        tiles.append((label, TF.to_pil_image(d.unsqueeze(0)).convert("RGB").resize((w, h))))
    cols = 2
    rows = (len(tiles) + 1) // 2
    out = Image.new("RGB", (w * cols, (h + 28) * rows), (20, 20, 20))
    draw = ImageDraw.Draw(out)
    for i, (label, im) in enumerate(tiles):
        x, y = (i % cols) * w, (i // cols) * (h + 28)
        draw.text((x + 6, y + 6), label, fill=(255, 255, 255))
        out.paste(im, (x, y + 28))
    path = os.path.join(HERE, "depth_compare.png")
    out.save(path)
    print("saved", path)


if __name__ == "__main__":
    main()
