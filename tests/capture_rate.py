"""Count how many frames Windows Graphics Capture delivers for a window in N seconds.

Used to check that a big (4K) video window keeps updating, i.e. isn't treated as fullscreen.
Run: python -I capture_rate.py "exact window title" [seconds]
Prints the frame count, rate and frame size.
"""
import sys
import threading
import time

from windows_capture import WindowsCapture

title = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
count = 0
size = None
start = None
done = threading.Event()

cap = WindowsCapture(cursor_capture=False, draw_border=False, window_name=title)


@cap.event
def on_frame_arrived(frame, control):
    global count, size, start
    if start is None:
        start = time.perf_counter()
    count += 1
    size = (frame.width, frame.height)
    if time.perf_counter() - start >= seconds:
        control.stop()
        done.set()


@cap.event
def on_closed():
    done.set()


cap.start_free_threaded()
done.wait(seconds + 10)
elapsed = time.perf_counter() - start if start else 0
print(f"frames {count} in {elapsed:.1f}s = {count / max(elapsed, 1e-6):.1f} fps, size {size}")
