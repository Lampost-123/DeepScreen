"""VN3D input bridge: turns UDP commands from the VR viewer into mouse/keyboard input on the game window.

Listens on 127.0.0.1:1304 (localhost only). Commands, one per datagram:
    move <u> <v>     pointer at normalized game coords (0..1, top-left origin)
    click            left click at the pointer
    rclick           right click (Ren'Py: game menu)
    wheel <n>        mouse wheel notches (+ = up = Ren'Py rollback)
    key <name>       tap a key: space, enter, esc, ctrl_down, ctrl_up, h, pgup, pgdn, left, right

Usage: python input_bridge.py "Part of window title" [--hover]
  Default: the Windows cursor stays parked outside the game window and only jumps in for a
  click, so window capture never shows it. --hover keeps it on the laser point instead
  (button hover effects work, but the cursor shows in the 3D picture).
"""
import ctypes
import ctypes.wintypes as wt
import socket
import sys
import time

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels, matches 4K game window
except Exception:
    pass

HOST, PORT = "127.0.0.1", 1304

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
VK = {"space": 0x20, "enter": 0x0D, "esc": 0x1B, "ctrl": 0x11, "h": 0x48,
      "pgup": 0x21, "pgdn": 0x22, "alt": 0x12, "left": 0x25, "right": 0x27}
EXTENDED = {0x21, 0x22, 0x25, 0x27}  # arrow / page keys need KEYEVENTF_EXTENDEDKEY to not read as numpad
KEYEVENTF_EXTENDEDKEY = 0x0001


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def send(inp):
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def mouse(flags, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.u.mi = MOUSEINPUT(0, 0, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, None)
    send(inp)


def key(vk, up=False):
    inp = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    inp.u.ki = KEYBDINPUT(vk, 0, flags, 0, None)
    send(inp)


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


def client_rect(hwnd):
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def focus(hwnd):
    if user32.GetForegroundWindow() != hwnd:
        # Tapping ALT lets a background process take foreground (Windows focus-steal rule).
        key(VK["alt"])
        key(VK["alt"], up=True)
        user32.SetForegroundWindow(hwnd)


# Without --hover the Windows cursor is parked outside the game window between clicks:
# window capture always draws the real cursor, and the VR viewer shows its own laser dot.
HOVER = "--hover" in sys.argv


def park_point(hwnd):
    """A point on some monitor but outside the game window, or the virtual screen's corner."""
    wr = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    midx, midy = (wr.left + wr.right) // 2, (wr.top + wr.bottom) // 2
    for x, y in ((wr.right + 40, midy), (wr.left - 40, midy), (midx, wr.bottom + 40), (midx, wr.top - 40)):
        if user32.MonitorFromPoint(wt.POINT(x, y), 0):  # MONITOR_DEFAULTTONULL
            return x, y
    return vx + vw - 1, vy + vh - 1


def with_cursor(hwnd, pos, action):
    """Put the cursor on pos (or the window centre), run action, then park it again."""
    if pos is None:
        x0, y0, w, h = client_rect(hwnd)
        pos = (x0 + w // 2, y0 + h // 2)
    user32.SetCursorPos(*pos)
    if not HOVER:
        time.sleep(0.05)  # let the game see the mouse move (hover target) before the click
    action()
    if not HOVER:
        time.sleep(0.08)
        user32.SetCursorPos(*park_point(hwnd))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    title = args[0]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    sock.settimeout(2.0)
    print(f"input bridge listening on {HOST}:{PORT} for window '{title}'")
    hwnd = None
    last_move = None
    while True:
        try:
            data, _ = sock.recvfrom(256)
        except socket.timeout:
            continue
        if hwnd is None or not user32.IsWindow(hwnd):
            hwnd = find_window(title)
            if hwnd is None:
                print(f"window '{title}' not found")
                time.sleep(1)
                continue
            if not HOVER:
                user32.SetCursorPos(*park_point(hwnd))
        parts = data.decode("ascii", "ignore").split()
        if not parts:
            continue
        cmd = parts[0]
        if cmd == "move" and len(parts) == 3:
            x0, y0, w, h = client_rect(hwnd)
            u = min(max(float(parts[1]), 0.0), 1.0)
            v = min(max(float(parts[2]), 0.0), 1.0)
            pos = (x0 + int(u * (w - 1)), y0 + int(v * (h - 1)))
            if pos != last_move:
                last_move = pos
                if HOVER:
                    user32.SetCursorPos(*pos)
        elif cmd == "click":
            focus(hwnd)
            with_cursor(hwnd, last_move, lambda: (mouse(MOUSEEVENTF_LEFTDOWN), mouse(MOUSEEVENTF_LEFTUP)))
        elif cmd == "rclick":
            focus(hwnd)
            with_cursor(hwnd, last_move, lambda: (mouse(MOUSEEVENTF_RIGHTDOWN), mouse(MOUSEEVENTF_RIGHTUP)))
        elif cmd == "wheel" and len(parts) == 2:
            focus(hwnd)
            with_cursor(hwnd, last_move, lambda: mouse(MOUSEEVENTF_WHEEL, int(parts[1]) * 120))
        elif cmd == "key" and len(parts) == 2:
            focus(hwnd)
            name = parts[1]
            if name.endswith("_down") or name.endswith("_up"):
                base, _, state = name.rpartition("_")
                if base in VK:
                    key(VK[base], up=(state == "up"))
            elif name in VK:
                key(VK[name])
                key(VK[name], up=True)


if __name__ == "__main__":
    main()
