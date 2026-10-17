"""Save the game frame, iw3's depth map and SBS output side by side, for judging 3D quality.

Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d-stable\\tests\\depth_snapshot.py "Window title" [divergence] [convergence]
Writes D:\\vn3d-stable\\tests\\depth_snapshot.png and prints depth statistics.
"""
import ctypes
import os
import sys

import torch
import torch.nn.functional as F
import torchvision.transforms.functional as TF

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, r"D:\nunif")
import iw3_fast  # noqa: E402,F401
from compare_layers import grab_window  # noqa: E402
from iw3.desktop.utils import create_parser, set_state_args, init_win32  # noqa: E402
from iw3 import utils as IW3U  # noqa: E402


def main():
    init_win32()
    title = sys.argv[1] if len(sys.argv) > 1 else "My Game"
    div = sys.argv[2] if len(sys.argv) > 2 else "1.5"
    conv = sys.argv[3] if len(sys.argv) > 3 else "1.0"
    img = grab_window(title)
    src = TF.to_tensor(img).cuda()
    frame = F.interpolate(src.unsqueeze(0), size=(1080, round(src.shape[2] * 1080 / src.shape[1] / 2) * 2),
                          mode="bilinear", antialias=True, align_corners=False).squeeze(0)
    args = create_parser().parse_args(["--depth-model", "Any_V2_S", "--divergence", div, "--convergence", conv,
                                      "--full-sbs"])
    set_state_args(args)
    dm = args.state["depth_model"]
    dm.load(gpu=args.gpu, resolution=args.resolution, limit_resolution=args.limit_resolution)
    args.mapper = IW3U.resolve_mapper_name(mapper=args.mapper, foreground_scale=args.foreground_scale,
                                           metric_depth=dm.is_metric())
    side = IW3U.create_stereo_model(args.method, divergence=args.divergence, device_id=args.gpu[0])
    with torch.inference_mode():
        depth = dm.infer(frame, tta=False, enable_amp=True, edge_dilation=args.edge_dilation)
        sbs = IW3U.process_image(frame, args, dm, side, autocrop_uncrop=True)
    d = depth.float().squeeze()
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)
    print(f"mapper={args.mapper} depth: mean {d.mean():.3f} std {d.std():.3f} "
          f"p10 {d.quantile(0.1):.3f} p90 {d.quantile(0.9):.3f}")
    w = 640
    h = round(w * frame.shape[1] / frame.shape[2])
    tiles = [TF.to_pil_image(frame.cpu()).resize((w, h)),
             TF.to_pil_image(d.unsqueeze(0).cpu()).convert("RGB").resize((w, h)),
             TF.to_pil_image(sbs.clamp(0, 1).cpu()).resize((w * 2, h))]
    from PIL import Image
    out = Image.new("RGB", (w * 2, h * 2))
    out.paste(tiles[0], (0, 0))
    out.paste(tiles[1], (w, 0))
    out.paste(tiles[2], (0, h))
    path = os.path.join(HERE, "depth_snapshot.png")
    out.save(path)
    print("saved", path)


if __name__ == "__main__":
    main()
