"""Profile one iw3 conversion (row_flow, 1080p) with torch.profiler: top ops by CPU and GPU time.

Run: cd /d D:\\nunif && venv\\Scripts\\python.exe D:\\vn3d\\tests\\profile_iw3.py "Window title"
"""
import sys
import time

import torch
import torch.nn.functional as F
from torch.profiler import profile, ProfilerActivity

sys.path.insert(0, r"D:\vn3d\tests")
sys.path.insert(0, r"D:\vn3d")
sys.path.insert(0, r"D:\nunif")
from bench_iw3 import grab_client, setup  # noqa: E402
from iw3.desktop.utils import init_win32  # noqa: E402
from iw3 import utils as IW3U  # noqa: E402


def main():
    init_win32()
    src = grab_client(sys.argv[1] if len(sys.argv) > 1 else "My Game").cuda()
    frame = F.interpolate(src.unsqueeze(0), size=(1080, 1920), mode="bilinear", antialias=True,
                          align_corners=False).squeeze(0)
    args, dm, side = setup("row_flow")
    with torch.inference_mode():
        for _ in range(5):
            IW3U.process_image(frame, args, dm, side, autocrop_uncrop=True)
        torch.cuda.synchronize()
        # Depth only, to separate it from the warp.
        t = time.perf_counter()
        for _ in range(20):
            dm.infer(frame, tta=False, enable_amp=not args.disable_amp, edge_dilation=args.edge_dilation,
                     depth_aa=args.depth_aa)
        torch.cuda.synchronize()
        print(f"depth infer only: {(time.perf_counter() - t) / 20 * 1000:.1f} ms")
        print(f"args: edge_dilation={args.edge_dilation} depth_aa={args.depth_aa} ema={args.ema_normalize} "
              f"amp={not args.disable_amp} tta={args.tta} method={args.method}")
        with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
            for _ in range(10):
                IW3U.process_image(frame, args, dm, side, autocrop_uncrop=True)
            torch.cuda.synchronize()
    print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=15))
    print(prof.key_averages().table(sort_by="cpu_time_total", row_limit=15))


if __name__ == "__main__":
    main()
