"""Fake VN3D Ren'Py hook for testing the viewer's layers mode without a game.

Serves the hook's wire format (v2: premultiplied color PNG + gray alpha-mask PNG per layer)
on 127.0.0.1:1305: a 1920x1080 background, two sprites (one moves every capture) and a
textbox UI layer, 5 captures per second.
Usage: python -I fake_layer_stream.py [port] [seconds]
"""
import io
import json
import socket
import struct
import sys
import threading
import time
import zlib

from PIL import Image, ImageDraw

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1305
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 20
W, H = 1920, 1080


def png(im):
    bio = io.BytesIO()
    im.save(bio, "PNG", compress_level=1)
    return bio.getvalue()


def split(im):
    """RGBA image -> (color premultiplied over black, alpha mask) PNGs, like the hook sends."""
    black = Image.new("RGBA", im.size, (0, 0, 0, 255))
    color = Image.alpha_composite(black, im).convert("RGB")
    return png(color), png(im.getchannel("A"))


def make_static():
    bg = Image.new("RGBA", (W, H), (60, 90, 140, 255))
    d = ImageDraw.Draw(bg)
    for x in range(0, W, 120):
        d.line([x, 0, x, H], fill=(90, 120, 170, 255), width=3)
    sprite = Image.new("RGBA", (500, 900), (0, 0, 0, 0))
    ImageDraw.Draw(sprite).ellipse([50, 0, 450, 900], fill=(200, 150, 120, 255))
    ui = Image.new("RGBA", (1800, 280), (0, 0, 0, 0))
    ImageDraw.Draw(ui).rounded_rectangle([0, 0, 1799, 279], 20, fill=(0, 0, 0, 180))
    return (png(bg.convert("RGB")), b""), split(sprite), split(ui)


def message(seq, bg, sprite, ui):
    x2 = 1200 + (seq * 20) % 400
    layers = [
        ("master:bg:0", "bg", "bg", 0, 0, W, H, bg),
        ("master:eileen:1", "sprite", "eileen", 300, 180, 500, 900, sprite),
        ("master:lucy:2", "sprite", "lucy", x2, 180, 500, 900, sprite),
        ("ui", "ui", "ui", 60, 780, 1800, 280, ui),
    ]
    metas, blobs = [], []
    for key, kind, tag, x, y, w, h, (color, mask) in layers:
        metas.append({"key": key, "kind": kind, "tag": tag, "name": tag, "zorder": 0, "x": x, "y": y,
                      "w": w, "h": h, "hash": "%08x" % (zlib.crc32(color + mask) & 0xffffffff),
                      "size": len(color), "mask_size": len(mask)})
        blobs += [color, mask]
    header = json.dumps({"v": 2, "seq": seq, "w": W, "h": H, "layers": metas}).encode()
    return b"".join([b"VN3D", struct.pack(">I", len(header)), header] + blobs)


def serve(conn, static):
    try:
        seq = 0
        while True:
            seq += 1
            data = message(seq, *static)
            for i in range(0, len(data), 64000):  # partial writes exercise the viewer's buffering
                conn.sendall(data[i:i + 64000])
            time.sleep(0.2)
    except OSError:
        pass
    finally:
        conn.close()


def main():
    static = make_static()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen()
    srv.settimeout(1.0)
    end = time.time() + SECONDS
    print(f"fake layer stream on 127.0.0.1:{PORT} for {SECONDS}s", flush=True)
    while time.time() < end:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        print("client connected", flush=True)
        threading.Thread(target=serve, args=(conn, static), daemon=True).start()
    srv.close()


if __name__ == "__main__":
    main()
