"""SPIKE (throwaway): does tiled / higher-res depth recover small surface relief?

A: Depth Anything V2 Small at 518 (current setting)
B: A + high-frequency detail from the same model at 1036
C: A + high-frequency detail from a 3x3 grid of overlapping zoomed tiles (each at 518)
Each depth map is also rendered as a lit surface ("relief"), which shows bumps far better than gray depth.
Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d-stable\\tests\\spike_refine.py [frame.png] [gain]
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
from iw3.desktop.utils import create_parser, set_state_args, init_win32  # noqa: E402


def load_model(res):
    args = create_parser().parse_args(["--depth-model", "Any_V2_S", "--full-sbs", "--resolution", str(res)])
    set_state_args(args)
    dm = args.state["depth_model"]
    dm.load(gpu=args.gpu, resolution=args.resolution, limit_resolution=args.limit_resolution)
    return dm


def infer(dm, img):
    with torch.inference_mode():
        return dm.infer(img, tta=False, enable_amp=True, edge_dilation=0).float().squeeze()


def blur(d, sigma):
    k = int(sigma * 3) * 2 + 1
    return TF.gaussian_blur(d[None, None], [k, k], [sigma, sigma])[0, 0]


def fit(src, ref, mask=None):
    """Least-squares scale/shift so src matches ref (depth models' output scale is arbitrary)."""
    s, r = src.flatten(), ref.flatten()
    A = torch.stack([s, torch.ones_like(s)], 1)
    sol = torch.linalg.lstsq(A, r[:, None]).solution
    return src * sol[0, 0] + sol[1, 0]


def detail_from_tiles(dm, img, base, grid=3, overlap=0.5):
    _, H, W = img.shape
    th, tw = int(H / (grid - (grid - 1) * overlap)), int(W / (grid - (grid - 1) * overlap))
    acc = torch.zeros_like(base)
    wsum = torch.zeros_like(base)
    for gy in range(grid):
        for gx in range(grid):
            y0 = min(int(gy * th * (1 - overlap)), H - th)
            x0 = min(int(gx * tw * (1 - overlap)), W - tw)
            d = infer(dm, img[:, y0:y0 + th, x0:x0 + tw])
            d = F.interpolate(d[None, None], size=(th, tw), mode="bilinear", align_corners=False)[0, 0]
            d = fit(d, base[y0:y0 + th, x0:x0 + tw])
            # Feathered weight so tile seams don't show.
            wy = torch.hann_window(th, periodic=False, device=d.device).clamp_min(1e-3)
            wx = torch.hann_window(tw, periodic=False, device=d.device).clamp_min(1e-3)
            w = wy[:, None] * wx[None, :]
            acc[y0:y0 + th, x0:x0 + tw] += d * w
            wsum[y0:y0 + th, x0:x0 + tw] += w
    return acc / wsum.clamp_min(1e-6)


def relief(d):
    """Lit-surface view of a depth map (bigger = nearer), so small bumps become visible."""
    d = (d - d.min()) / (d.max() - d.min() + 1e-6) * 300.0
    gx = F.pad(d[:, 1:] - d[:, :-1], (0, 1))
    gy = F.pad(d[1:, :] - d[:-1, :], (0, 0, 0, 1))
    n = torch.stack([gx, gy, torch.ones_like(d)], 0)
    n = n / n.norm(dim=0, keepdim=True)
    light = torch.tensor([-0.5, -0.5, 0.7], device=d.device)
    light = light / light.norm()
    return (n * light[:, None, None]).sum(0).clamp(0, 1)


def to_img(t, w, h):
    t = (t - t.min()) / (t.max() - t.min() + 1e-6)
    return TF.to_pil_image(t[None].cpu()).convert("RGB").resize((w, h))


def main():
    init_win32()
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "spike_frame.png")
    gain = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5
    src = TF.to_tensor(Image.open(path).convert("RGB")).cuda()
    img = F.interpolate(src[None], size=(1080, round(src.shape[2] * 1080 / src.shape[1])),
                        mode="bilinear", antialias=True, align_corners=False)[0]
    H, W = img.shape[1:]
    dm = load_model(518)
    t = time.perf_counter()
    base = F.interpolate(infer(dm, img)[None, None], size=(H, W), mode="bilinear")[0, 0]
    torch.cuda.synchronize(); ms_a = (time.perf_counter() - t) * 1000

    # Detail = what the finer pass has that a blur of it doesn't (high frequencies only).
    sigma = 12
    t = time.perf_counter()
    tiles = detail_from_tiles(dm, img, base)
    torch.cuda.synchronize(); ms_c = (time.perf_counter() - t) * 1000
    c = base + gain * (tiles - blur(tiles, sigma))

    dm_hi = load_model(1036)
    t = time.perf_counter()
    hi = F.interpolate(infer(dm_hi, img)[None, None], size=(H, W), mode="bilinear")[0, 0]
    hi = fit(hi, base)
    torch.cuda.synchronize(); ms_b = (time.perf_counter() - t) * 1000
    b = base + gain * (hi - blur(hi, sigma))

    w, h = 640, 360
    rows = [("A: 518 (now)", base, ms_a), ("B: + 1036 detail", b, ms_b), ("C: + 3x3 tile detail", c, ms_c)]
    out = Image.new("RGB", (w * 3, (h + 24) * 3 + 24), (20, 20, 20))
    dr = ImageDraw.Draw(out)
    dr.text((6, 4), f"gain {gain}, detail = finer pass minus its blur (sigma {sigma}px)", fill=(255, 255, 255))
    for i, (label, d, ms) in enumerate(rows):
        y = 24 + i * (h + 24)
        dr.text((6, y + 4), f"{label}  ({ms:.0f} ms)", fill=(255, 255, 255))
        out.paste(TF.to_pil_image(img.cpu()).resize((w, h)), (0, y + 24))
        out.paste(to_img(d, w, h), (w, y + 24))
        out.paste(to_img(relief(d), w, h), (2 * w, y + 24))
        print(f"{label}: {ms:.0f} ms")
    p = os.path.join(HERE, "spike_refine.png")
    out.save(p)
    # Close-up of the centre (where the small details are) as relief only, bigger.
    cy0, cy1, cx0, cx1 = int(H * 0.2), int(H * 0.75), int(W * 0.1), int(W * 0.75)
    crop = Image.new("RGB", (900 * 3, 520), (20, 20, 20))
    for i, (label, d, _) in enumerate(rows):
        crop.paste(to_img(relief(d)[cy0:cy1, cx0:cx1], 880, 500), (i * 900 + 10, 10))
    crop.save(os.path.join(HERE, "spike_refine_closeup.png"))
    print("saved", p)


if __name__ == "__main__":
    main()
