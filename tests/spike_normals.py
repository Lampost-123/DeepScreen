"""SPIKE (throwaway): do Sapiens surface normals recover small body relief that depth misses?

1. Depth Anything V2 Small @518 on the frame (today's depth).
2. Sapiens Normal 0.3B on a centred portrait crop (its native 1024x768 input).
3. Normals -> height by Frankot-Chellappa FFT integration; keep only fine detail (minus blur).
4. Depth + gain * detail, shown as relief shading next to plain depth.
Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d-stable\\tests\\spike_normals.py [frame.png] [gain]
"""
import math
import os
import sys
import time

import torch
import torch.nn.functional as F
import torchvision.transforms.functional as TF
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from spike_refine import load_model, infer, blur, relief, to_img, fit  # noqa: E402

SAPIENS = r"D:\nunif\iw3\pretrained_models\hub\checkpoints\sapiens_0.3b_normal_render_people_epoch_66_torchscript.pt2"
MEAN = torch.tensor([123.5, 116.5, 103.5]).view(3, 1, 1) / 255.0
STD = torch.tensor([58.5, 57.0, 57.5]).view(3, 1, 1) / 255.0


def sapiens_normals(model, crop):
    """crop: 3xHxW in 0..1 -> unit normals 3xHxW (camera space as Sapiens outputs)."""
    x = F.interpolate(crop[None], size=(1024, 768), mode="bilinear", antialias=True, align_corners=False)
    x = (x - MEAN.to(x.device)) / STD.to(x.device)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        n = model(x)
    n = F.interpolate(n.float(), size=crop.shape[1:], mode="bilinear", align_corners=False)[0]
    return n / n.norm(dim=0, keepdim=True).clamp_min(1e-6)


def integrate(n, sign_x=1.0, sign_y=1.0):
    """Frankot-Chellappa: height whose gradients best match the normals."""
    nz = n[2].abs().clamp_min(0.1)
    p = sign_x * -n[0] / nz  # dz/dx
    q = sign_y * -n[1] / nz  # dz/dy
    H, W = p.shape
    wx = torch.fft.fftfreq(W, device=p.device) * 2 * math.pi
    wy = torch.fft.fftfreq(H, device=p.device) * 2 * math.pi
    WX, WY = torch.meshgrid(wx, wy, indexing="xy")
    denom = WX ** 2 + WY ** 2
    denom[0, 0] = 1.0
    Z = (-1j * WX * torch.fft.fft2(p) - 1j * WY * torch.fft.fft2(q)) / denom
    Z[0, 0] = 0
    return torch.fft.ifft2(Z).real


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "spike_frame.png")
    gain = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    src = TF.to_tensor(Image.open(path).convert("RGB")).cuda()
    img = F.interpolate(src[None], size=(1080, round(src.shape[2] * 1080 / src.shape[1])),
                        mode="bilinear", antialias=True, align_corners=False)[0]
    H, W = img.shape[1:]
    dm = load_model(518)
    base = F.interpolate(infer(dm, img)[None, None], size=(H, W), mode="bilinear")[0, 0]

    # Portrait crop around the centre, in Sapiens' 4:3 portrait shape.
    ch = H
    cw = int(ch * 768 / 1024)
    x0 = (W - cw) // 2
    crop = img[:, :, x0:x0 + cw]
    model = torch.jit.load(SAPIENS).cuda().eval()
    sapiens_normals(model, crop)  # warm-up
    torch.cuda.synchronize()
    t = time.perf_counter()
    n = sapiens_normals(model, crop)
    torch.cuda.synchronize()
    ms = (time.perf_counter() - t) * 1000
    print(f"sapiens normals: {ms:.0f} ms for a {cw}x{ch} crop")

    base_c = base[:, x0:x0 + cw]
    rows = [("normals (RGB)", None), ("depth only (now)", base_c)]
    sigma = 12
    for sx, sy in ((1, 1), (-1, -1)):
        h = integrate(n, sx, sy)
        h = fit(h, base_c)  # bring to the depth's scale before taking detail
        detail = h - blur(h, sigma)
        rows.append((f"depth + normal detail (signs {sx:+d},{sy:+d}, gain {gain})", base_c + gain * detail))

    w, hh = 480, 640
    out = Image.new("RGB", (w * len(rows), hh + 28), (20, 20, 20))
    dr = ImageDraw.Draw(out)
    for i, (label, d) in enumerate(rows):
        dr.text((i * w + 6, 6), label, fill=(255, 255, 255))
        if d is None:
            im = TF.to_pil_image(((n + 1) / 2).clamp(0, 1).cpu()).resize((w, hh))
        else:
            im = to_img(relief(d), w, hh)
        out.paste(im, (i * w, 28))
    p = os.path.join(HERE, "spike_normals.png")
    out.save(p)
    print("saved", p)


if __name__ == "__main__":
    main()
