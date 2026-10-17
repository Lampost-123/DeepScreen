"""Test client for the VN3D Ren'Py layer hook (wire format v2): connects to 127.0.0.1:1305 and logs each capture.

Usage: python -I layer_client.py [port] [seconds] [save_dir]
With save_dir, the layers of each new capture are saved there as PNG files (color and _mask).
"""
import json
import os
import socket
import struct
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1305
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 60
SAVE = sys.argv[3] if len(sys.argv) > 3 else ""


def read_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return bytes(buf)


def main():
    end = time.time() + SECONDS
    while time.time() < end:
        try:
            sock = socket.create_connection(("127.0.0.1", PORT), timeout=2)
        except OSError:
            time.sleep(0.5)
            continue
        print("connected", flush=True)
        sock.settimeout(max(1.0, end - time.time()))
        seen = set()
        try:
            while time.time() < end:
                if read_exact(sock, 4) != b"VN3D":
                    print("bad magic")
                    return 1
                (n,) = struct.unpack(">I", read_exact(sock, 4))
                header = json.loads(read_exact(sock, n))
                parts = []
                for layer in header["layers"]:
                    blob = read_exact(sock, layer["size"])
                    mask = read_exact(sock, layer.get("mask_size", 0))
                    for b in (blob, mask):
                        assert not b or b[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
                    new = layer["hash"] not in seen
                    seen.add(layer["hash"])
                    if new and SAVE:
                        base = os.path.join(SAVE, "%04d_%s" % (header["seq"], layer["key"].replace(":", "_")))
                        with open(base + ".png", "wb") as f:
                            f.write(blob)
                        if mask:
                            with open(base + "_mask.png", "wb") as f:
                                f.write(mask)
                    parts.append("%s[%s] %dx%d@%d,%d %dKB%s%s" % (
                        layer["key"], layer["kind"], layer["w"], layer["h"], layer["x"], layer["y"],
                        (layer["size"] + len(mask)) // 1024, " +mask" if mask else "", " new" if new else ""))
                print("seq %d %dx%d: %s" % (header["seq"], header["w"], header["h"], "; ".join(parts)), flush=True)
        except (OSError, ConnectionError) as e:
            print("disconnected:", e, flush=True)
        finally:
            sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
