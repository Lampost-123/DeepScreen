"""Print iw3 crop options that cut a window's title bar and borders down to its client area.

Windows Graphics Capture (iw3 --screenshot wc_cuda) captures the window's visible frame
(DWM extended frame bounds), so the crop is client rect minus that frame, in physical pixels.
Usage: python -I window_crop.py "Part of window title" [--resize-client WxH [--frame-offscreen]]
Prints: --crop-top N --crop-left N --crop-right N --crop-bottom N  (nothing if not found)
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

DWMWA_EXTENDED_FRAME_BOUNDS = 9


def find_window(title_part):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_part.lower() in buf.value.lower():
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def crop_for(hwnd):
    frame = wt.RECT()
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(frame), ctypes.sizeof(frame))
    client = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    top = pt.y - frame.top
    left = pt.x - frame.left
    right = frame.right - (pt.x + client.right)
    bottom = frame.bottom - (pt.y + client.bottom)
    size = (frame.right - frame.left, frame.bottom - frame.top, client.right, client.bottom)
    return [max(0, v) for v in (top, left, right, bottom)], size


def resize_client(hwnd, w, h, frame_offscreen=False):
    """Make the window's inner (client) area exactly w x h physical pixels.

    Normally the window is moved to the monitor's work-area corner so it stays visible. With
    frame_offscreen, the client area's corner goes to the monitor's corner and the title bar and
    borders hang off-screen: lets a client as big as the monitor (4K on a 4K screen) exist as a
    normal window, which window capture keeps updating (a true fullscreen window it doesn't)."""
    wr = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    cr = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    extra_w = (wr.right - wr.left) - cr.right
    extra_h = (wr.bottom - wr.top) - cr.bottom
    mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    mi = MONITORINFO(ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    if frame_offscreen:
        x = mi.rcMonitor.left - (pt.x - wr.left)
        y = mi.rcMonitor.top - (pt.y - wr.top)
    else:
        x, y = mi.rcWork.left, mi.rcWork.top
    # SWP_NOZORDER | SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, None, x, y, w + extra_w, h + extra_h, 0x0004 | 0x0010)


def main():
    hwnd = find_window(sys.argv[1]) if len(sys.argv) > 1 else None
    if not hwnd:
        return
    if user32.IsIconic(hwnd):
        # A minimized window has a 0x0 client area, which crashes iw3; bring it back first.
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(1.0)
        print("restored minimized game window", file=sys.stderr)
    if "--resize-client" in sys.argv:
        # e.g. --resize-client 1920x1080 (used to let VLC upscale a video to the stream size)
        w, h = map(int, sys.argv[sys.argv.index("--resize-client") + 1].lower().split("x"))
        resize_client(hwnd, w, h, frame_offscreen="--frame-offscreen" in sys.argv)
        time.sleep(0.5)
    (top, left, right, bottom), size = crop_for(hwnd)
    print(f"frame {size[0]}x{size[1]} client {size[2]}x{size[3]}", file=sys.stderr)
    print(f"--crop-top {top} --crop-left {left} --crop-right {right} --crop-bottom {bottom}")


if __name__ == "__main__":
    main()
