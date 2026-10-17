"""Shape boost check on a saved frame: relief view at boost 0 / 1 / 2, timing, and that 0 changes nothing.

Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d-stable\\tests\\check_shape_boost.py [frame.png]
Writes D:\\vn3d-stable\\tests\\shape_boost.png
"""
import os
import sys
import time

import torch
import torch.nn.functional as F
import torchvision.transforms.functional as TF
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from spike_refine import load_model, relief, to_img  # noqa: E402  (imports iw3_fast too)
import iw3_fast  # noqa: E402


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "spike_frame.png")
    src = TF.to_tensor(Image.open(path).convert("RGB")).cuda()
    img = F.interpolate(src[None], size=(1080, round(src.shape[2] * 1080 / src.shape[1])),
                        mode="bilinear", antialias=True, align_corners=False)[0]
    dm = load_model(518)
    tiles = []
    ref = None
    for k in (0.0, 1.0, 2.0):
        iw3_fast.shape_boost = k
        with torch.inference_mode():
            d = dm.infer(img, tta=False, enable_amp=True, edge_dilation=0).float().squeeze()
        if k == 0.0:
            ref = d
        tiles.append((f"shape boost {k}", d))
    # Cost of the boost itself on a model-sized depth map.
    raw = torch.rand(1, 1, 518, 910, device="cuda")
    for _ in range(5):
        iw3_fast.apply_shape_boost(raw, 1.0)
    torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(50):
        iw3_fast.apply_shape_boost(raw, 1.0)
    torch.cuda.synchronize()
    print(f"boost cost: {(time.perf_counter() - t) / 50 * 1000:.2f} ms")
    iw3_fast.shape_boost = 0.0
    with torch.inference_mode():
        again = dm.infer(img, tta=False, enable_amp=True, edge_dilation=0).float().squeeze()
    print(f"boost 0 identical to plain: {torch.equal(again, ref)}")
    w, h = 640, 360
    out = Image.new("RGB", (w * 3, h * 2 + 24), (20, 20, 20))
    dr = ImageDraw.Draw(out)
    for i, (label, d) in enumerate(tiles):
        dr.text((i * w + 6, 4), label, fill=(255, 255, 255))
        out.paste(to_img(d, w, h), (i * w, 24))
        out.paste(to_img(relief(d), w, h), (i * w, 24 + h))
    p = os.path.join(HERE, "shape_boost.png")
    out.save(p)
    print("saved", p)


if __name__ == "__main__":
    main()
