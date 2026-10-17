"""Run iw3-desktop with the depth model replayed through CUDA graphs.

Profiling (tests/profile_iw3.py) showed iw3-desktop is CPU-bound: the GPU works ~9 ms per
frame, but launching ~700 small kernels one by one from Python takes ~30 ms. A CUDA graph
records the depth model's kernels once and replays them with one launch per frame.

Usage (same arguments as `python -m iw3.desktop`, run with D:\\nunif as working directory):
    python D:\\vn3d\\iw3_fast.py --window-name "Game" --full-sbs ...
Set VN3D_NO_GRAPHS=1 to run stock iw3 for comparison.
"""
import os
import sys

sys.path.insert(0, r"D:\nunif")

import torch  # noqa: E402
from iw3 import depth_anything_model as dam  # noqa: E402

_original_forward = dam._forward
_graphs = {}  # (model id, shape, dtype, amp) -> (graph, static_in, static_out) or None if capture failed


def _capture(model, x, enable_amp):
    static_in = x.clone()
    stream = torch.cuda.Stream(device=x.device)
    stream.wait_stream(torch.cuda.current_stream(x.device))
    with torch.cuda.stream(stream):
        for _ in range(3):  # warm-up so cuDNN/attention pick kernels before capture
            _original_forward(model, static_in, enable_amp)
    torch.cuda.current_stream(x.device).wait_stream(stream)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        static_out = _original_forward(model, static_in, enable_amp)
    return graph, static_in, static_out


def _graphed_forward(model, x, enable_amp):
    if x.device.type != "cuda":
        return _original_forward(model, x, enable_amp)
    key = (id(model), tuple(x.shape), x.dtype, bool(enable_amp))
    entry = _graphs.get(key, False)
    if entry is False:
        try:
            entry = _capture(model, x, enable_amp)
            print(f"vn3d: depth model CUDA graph captured for input {tuple(x.shape)}", flush=True)
        except Exception as e:  # never break iw3: fall back to normal launches for this shape
            print(f"vn3d: CUDA graph capture failed ({e}); using normal depth inference", flush=True)
            entry = None
        _graphs[key] = entry
    if entry is None:
        return _original_forward(model, x, enable_amp)
    graph, static_in, static_out = entry
    static_in.copy_(x)
    graph.replay()
    return static_out.clone()


# Shape boost: exaggerate local roundness of the depth map (bodies, faces, objects) relative to
# the scene's overall layout: depth + k * (depth - blur(depth)). 0 = off. Set live via "shape <k>".
shape_boost = 0.0
SHAPE_BLUR_FRACTION = 1 / 12  # blur radius as a fraction of the depth map's height (~body-part size)


def apply_shape_boost(out, k):
    """out: Bx1xHxW raw depth from the model."""
    if k <= 0.0:
        return out
    h, w = out.shape[-2:]
    # Blur at 1/4 resolution: a large Gaussian is cheap there, and the base it removes is smooth anyway.
    small = torch.nn.functional.interpolate(out, size=(max(h // 4, 8), max(w // 4, 8)), mode="area")
    sigma = max(h * SHAPE_BLUR_FRACTION / 4, 1.0)
    kernel = int(sigma * 3) * 2 + 1
    import torchvision.transforms.functional as TF
    small = TF.gaussian_blur(small, [kernel, kernel], [sigma, sigma])
    base = torch.nn.functional.interpolate(small, size=(h, w), mode="bilinear", align_corners=False)
    return out + k * (out - base)


def _fast_forward(model, x, enable_amp):
    use_graphs = not os.environ.get("VN3D_NO_GRAPHS") and torch.cuda.is_available()
    out = _graphed_forward(model, x, enable_amp) if use_graphs else _original_forward(model, x, enable_amp)
    return apply_shape_boost(out, shape_boost)


dam._forward = _fast_forward


CONTROL_PORT = 1306  # localhost only: "divergence <value>" / "convergence <value>" change the 3D live

import threading  # noqa: E402

# Set by the control channel. Window capture only delivers a frame when the game redraws, and a
# visual novel often sits still, so without this a 3D change wouldn't show until the next redraw.
_params_changed = threading.Event()


def _patch_capture_reprocess():
    from iw3.desktop import screenshot_thread_cuda as stc
    cls = stc.ScreenshotThreadWCCUDA

    def get_frame(self):
        while True:
            if self.frame_set_event.wait(0.05):
                break
            if not self.is_alive():
                raise RuntimeError("thread is already dead")
            last = getattr(self, "_vn3d_last", None)
            if last is not None and _params_changed.is_set():
                _params_changed.clear()
                return last  # re-run the 3D conversion on the unchanged picture
        with self.frame_lock:
            frame = self.frame
            self.frame = None
            self.frame_set_event.clear()
        if frame is None:
            raise RuntimeError("thread is dead")
        self._vn3d_last = frame
        return frame

    cls.get_frame = get_frame


def _control_loop(args):
    global shape_boost
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", CONTROL_PORT))
    print(f"vn3d: control channel on 127.0.0.1:{CONTROL_PORT}", flush=True)
    while True:
        data, _ = sock.recvfrom(256)
        parts = data.decode("ascii", "ignore").split()
        if len(parts) != 2 or parts[0] not in ("divergence", "convergence", "shape"):
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        # apply_divergence() reads these every frame; the main loop holds this lock per frame.
        with args.state["args_lock"]:
            if parts[0] == "divergence":
                args.divergence = min(max(value, 0.0), 5.0)  # row_flow handles up to 5.0 in one step
                shown = args.divergence
            elif parts[0] == "convergence":
                args.convergence = min(max(value, 0.0), 1.0)  # which depth sits on the screen surface
                shown = args.convergence
            else:
                shape_boost = min(max(value, 0.0), 3.0)
                shown = shape_boost
        _params_changed.set()
        print(f"\nvn3d: {parts[0]} {shown:.2f}", flush=True)


def _with_control(main_fn):
    def wrapped(args, *a, **kw):
        import threading
        threading.Thread(target=_control_loop, args=(args,), daemon=True).start()
        return main_fn(args, *a, **kw)
    return wrapped


if __name__ == "__main__":
    # Our own option, removed before iw3 parses the command line: --vn3d-shape <k>
    if "--vn3d-shape" in sys.argv:
        i = sys.argv.index("--vn3d-shape")
        shape_boost = min(max(float(sys.argv[i + 1]), 0.0), 3.0)
        del sys.argv[i:i + 2]
    from iw3.desktop import cli
    _patch_capture_reprocess()
    cli.iw3_desktop_main = _with_control(cli.iw3_desktop_main)
    cli.cli_main()
