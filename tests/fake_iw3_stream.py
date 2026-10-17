"""Fake iw3-desktop MJPEG server for testing the viewer without the GPU.

Serves /stream.jpg as multipart/x-mixed-replace (same framing as iw3: no trailing CRLF,
boundary 'frame') with a 3840x1080 test SBS image: left half red tint, right half blue tint.
Usage: python -I fake_iw3_stream.py [port] [seconds] [fps] [real_frame.jpg]
"""
import io
import socket
import sys
import threading
import time

from PIL import Image, ImageDraw

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1303
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 20
FPS = float(sys.argv[3]) if len(sys.argv) > 3 else 15  # frames are pre-encoded, so high rates work
REAL_JPEG = sys.argv[4] if len(sys.argv) > 4 else None  # optional real SBS JPEG (realistic decode cost)


def make_frame(n):
    im = Image.new("RGB", (3840, 1080), (40, 40, 40))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1919, 1079], fill=(160, 40, 40))
    d.rectangle([1920, 0, 3839, 1079], fill=(40, 40, 160))
    d.text((100, 100), f"frame {n}", fill=(255, 255, 255))
    bio = io.BytesIO()
    im.save(bio, "JPEG", quality=80)
    return bio.getvalue()


def serve(conn):
    try:
        conn.recv(4096)
        conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n")
        if REAL_JPEG:
            with open(REAL_JPEG, "rb") as f:
                frames = [f.read()]
        else:
            frames = [make_frame(n) for n in range(8)]
        n = 0
        next_at = time.perf_counter()
        while True:
            # Send each part in small chunks to exercise the viewer's partial-frame handling.
            part = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frames[n % len(frames)]
            for i in range(0, len(part), 64000):
                conn.sendall(part[i:i + 64000])
            n += 1
            next_at += 1 / FPS
            time.sleep(max(0.0, next_at - time.perf_counter()))
    except OSError:
        pass
    finally:
        conn.close()


def main():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen()
    srv.settimeout(1.0)
    end = time.time() + SECONDS
    print(f"fake stream on 127.0.0.1:{PORT} for {SECONDS}s", flush=True)
    while time.time() < end:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        print("client connected", flush=True)
        threading.Thread(target=serve, args=(conn,), daemon=True).start()
    srv.close()


if __name__ == "__main__":
    main()
