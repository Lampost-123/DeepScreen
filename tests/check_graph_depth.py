"""Check the CUDA-graph depth model gives the same output as stock iw3 on two different frames."""
import sys

import torch

sys.path.insert(0, r"D:\vn3d\tests")
sys.path.insert(0, r"D:\vn3d")
sys.path.insert(0, r"D:\nunif")
import iw3_fast  # noqa: E402
from bench_iw3 import setup  # noqa: E402


def main():
    args, dm, _ = setup("row_flow")
    model = dm.model
    torch.manual_seed(0)
    a = torch.rand(1, 3, 392, 686, device="cuda")
    b = torch.rand(1, 3, 392, 686, device="cuda")
    with torch.inference_mode():
        for name, x in (("frame A", a), ("frame B", b), ("frame A again", a)):
            ref = iw3_fast._original_forward(model, x, True)
            got = iw3_fast._graphed_forward(model, x, True)
            err = (ref - got).abs().max().item()
            print(f"{name}: max abs diff {err:.2e} (depth range {ref.min().item():.3f}..{ref.max().item():.3f})")
    print("OK" if err < 1e-3 else "MISMATCH")


if __name__ == "__main__":
    main()
