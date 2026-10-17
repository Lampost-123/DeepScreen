# VN3D layer hook for Ren'Py 7.x (Python 2.7) and 8.x (Python 3), gl2 renderer.
#
# Drop this file into a game's game/ folder. It streams the scene, split into
# layers, to the VN3D Godot viewer on 127.0.0.1:1305 (localhost only):
#   bg      full-screen opaque images on the master layer (scene backgrounds, CGs)
#   sprite  every other image on the master layer (characters), with tag/zorder/position
#   ui      every layer above master (screens, textbox, menus, overlay) in one image
#
# Uninstall: delete vn3d_hook.rpy and vn3d_hook.rpyc from game/.
# Nothing is written to saves; the hook never touches the game's archives.
#
# Settings (environment variables, read when the game starts):
#   VN3D_PORT        TCP port (default 1305)
#   VN3D_FPS         capture rate cap while the scene changes (default 2)
#   VN3D_IDLE_FPS    capture rate while nothing changes (default 0.5)
#   VN3D_MAX_WIDTH   scale images wider than this down before sending (default 2560, 0 = off)
#   VN3D_TEST        1 = test mode: start the game from the main menu, auto-advance, no autosave
#   VN3D_TEST_SECONDS  test mode: quit after this many seconds (default 60)
#   VN3D_DUMP        folder to save the first captured layers as PNG files (debugging)
#
# Wire format (one message per capture):
#   b"VN3D" + uint32 big-endian header length + UTF-8 JSON header + image blobs
#   header = {"v": 2, "seq", "w", "h", "layers": [{"key", "kind", "tag", "name", "zorder",
#             "x", "y", "w", "h", "hash", "size", "mask_size"}]}
#   x/y/w/h are in game pixels (config.screen_width units); the images may be larger.
#   Per layer: "size" bytes of PNG color (premultiplied by alpha, drawn over black), then
#   "mask_size" bytes of PNG alpha mask (gray = alpha; 0 bytes = opaque, no mask).
#
# Why color + mask: Ren'Py's gl2 screenshot reads the opaque framebuffer, so transparency is
# captured as a second render of the same layer whose matrixcolor writes alpha into RGB.

init -999 python:

    # The implementation is compiled as plain Python (not Ren'Py store code), so its
    # objects stay out of saves and rollback, and its threads never touch store objects.
    _vn3d_hook_source = r'''
from __future__ import division, print_function

import ctypes
import io
import json
import math
import os
import socket
import struct
import sys
import threading
import time
import zlib

import pygame_sdl2
import renpy

VERSION = 2
HOST = "127.0.0.1"
PORT = int(os.environ.get("VN3D_PORT", "1305"))
FPS = float(os.environ.get("VN3D_FPS", "2"))
IDLE_FPS = float(os.environ.get("VN3D_IDLE_FPS", "0.5"))
# Images are captured at the window's real pixel size (e.g. 3840 wide on a 4K screen) and
# scaled down to at most this width before encoding. 0 = never scale.
MAX_WIDTH = int(os.environ.get("VN3D_MAX_WIDTH", "2560"))
SETTLE = 1.5    # seconds to keep capturing after a change (text typing out, transitions)
REFRESH = 2.0   # seconds before an unchanged sprite is captured again (animated sprites)
TEST = os.environ.get("VN3D_TEST", "") == "1"
TEST_SECONDS = float(os.environ.get("VN3D_TEST_SECONDS", "60"))
DUMP = os.environ.get("VN3D_DUMP", "")
BG_TAGS = ("bg", "background", "scene", "cg")


def pixel_crc(surf):
    """CRC of the raw pixels, so unchanged layers are not PNG-encoded again; None if the
    pixels can't be read directly (then the PNG bytes are hashed instead).

    pygame_sdl2's get_buffer() is a stub; _pixels_address is what Ren'Py itself uses."""
    addr = getattr(surf, "_pixels_address", None)
    if not addr:
        return None
    return zlib.crc32(ctypes.string_at(addr, surf.get_pitch() * surf.get_height())) & 0xffffffff


def log(msg):
    try:
        renpy.display.log.write("vn3d: %s" % msg)
    except Exception:
        pass


class Server(object):
    """Accepts viewer connections on localhost and sends them the latest capture."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.pending = None   # (seq, w, h, [(meta, color, mask)]) waiting to be encoded
        self.latest = None    # last encoded message, sent to new clients
        self.clients = []
        self.png_cache = {}   # pixel key -> png bytes, for unchanged images
        self.sock = None

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, PORT))
        self.sock.listen(4)
        for target in (self.accept_loop, self.encode_loop):
            t = threading.Thread(target=target, name="vn3d-" + target.__name__)
            t.daemon = True
            t.start()
        log("listening on %s:%d" % (HOST, PORT))

    def has_clients(self):
        with self.lock:
            return bool(self.clients) or bool(DUMP)

    def accept_loop(self):
        while True:
            try:
                conn, addr = self.sock.accept()
            except Exception:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            log("viewer connected from %s:%d" % addr)
            with self.lock:
                self.clients.append(conn)
                latest = self.latest
            if latest is not None:
                self.send_to(conn, latest)

    def send_to(self, conn, data):
        try:
            conn.sendall(data)
            return True
        except Exception:
            log("viewer disconnected")
            with self.lock:
                if conn in self.clients:
                    self.clients.remove(conn)
            try:
                conn.close()
            except Exception:
                pass
            return False

    def submit(self, capture):
        with self.cond:
            self.pending = capture   # older unencoded captures are dropped
            self.cond.notify()

    def encode_loop(self):
        while True:
            with self.cond:
                while self.pending is None:
                    self.cond.wait()
                capture = self.pending
                self.pending = None
            try:
                data = self.encode(capture)
            except Exception:
                import traceback
                log("encode failed: %s" % traceback.format_exc())
                continue
            with self.lock:
                self.latest = data
                clients = list(self.clients)
            for c in clients:
                self.send_to(c, data)

    def png(self, surf, cache):
        if MAX_WIDTH > 0 and surf.get_width() > MAX_WIDTH:
            size = (MAX_WIDTH, max(1, int(round(surf.get_height() * MAX_WIDTH / float(surf.get_width())))))
            surf = renpy.display.scale.smoothscale(surf, size)
        crc = pixel_crc(surf)
        key = None if crc is None else "%08x-%dx%d" % (crc, surf.get_width(), surf.get_height())
        data = self.png_cache.get(key) if key else None
        if data is None:
            bio = io.BytesIO()
            renpy.display.module.save_png(surf, bio, 1)
            data = bio.getvalue()
            if key is None:
                key = "p%08x-%d" % (zlib.crc32(data) & 0xffffffff, len(data))
        cache[key] = data
        return key, data

    def encode(self, capture):
        seq, w, h, items = capture
        metas = []
        blobs = []
        cache = {}
        for meta, color, mask in items:
            ckey, cdata = self.png(color, cache)
            blobs.append(cdata)
            meta["size"] = len(cdata)
            meta["hash"] = ckey
            meta["mask_size"] = 0
            if mask is not None:
                mkey, mdata = self.png(mask, cache)
                blobs.append(mdata)
                meta["mask_size"] = len(mdata)
                meta["hash"] = ckey + "/" + mkey
            metas.append(meta)
            if DUMP and seq <= 5:
                self.dump(seq, meta["key"], cdata, mdata if mask is not None else None)
        self.png_cache = cache
        header = json.dumps({"v": VERSION, "seq": seq, "w": w, "h": h, "layers": metas}).encode("utf-8")
        return b"".join([b"VN3D", struct.pack(">I", len(header)), header] + blobs)

    @staticmethod
    def dump(seq, key, cdata, mdata):
        try:
            base = os.path.join(DUMP, "vn3d_%03d_%s" % (seq, key.replace(":", "_")))
            with open(base + ".png", "wb") as f:
                f.write(cdata)
            if mdata is not None:
                with open(base + "_mask.png", "wb") as f:
                    f.write(mdata)
        except Exception as e:
            log("dump failed: %r" % (e,))


class Hook(object):

    def __init__(self):
        self.server = Server()
        self.seq = 0
        self.last_capture = 0.0
        self.last_change = 0.0
        self.signature = None
        self.errors = 0
        self.disabled = False
        self.started = time.time()
        self.test_started = False
        self.test_last_dismiss = 0.0
        self.logged = 0
        self.sprite_cache = {}  # (layer, id(displayable)) -> (placement, time, item)
        self.alpha_matrix = None
        self.t_shot = self.t_copy = 0.0  # time spent in screenshots / pixel copies, per capture

    def install(self):
        try:
            self.server.start()
        except Exception as e:
            log("could not listen on %s:%d (%r); hook disabled" % (HOST, PORT, e))
            self.disabled = True
            return
        self.attach()
        if TEST:
            renpy.config.has_autosave = False
            renpy.config.autosave_on_quit = False
            log("test mode: auto start, auto advance, quit after %ds" % TEST_SECONDS)
        log("hook installed (Ren'Py %s, Python %d.%d)" % (
            getattr(renpy, "version_only", renpy.version), sys.version_info[0], sys.version_info[1]))

    def attach(self):
        # Also called after a script reload (Shift+R), which resets renpy.config.
        if self.on_interact not in renpy.config.interact_callbacks:
            renpy.config.interact_callbacks.append(self.on_interact)
        if self.periodic not in renpy.config.periodic_callbacks:
            renpy.config.periodic_callbacks.append(self.periodic)

    def on_interact(self):
        self.last_change = time.time()

    # ---- scene inspection ----

    @staticmethod
    def unwrap(d):
        # MultiBox has a class attribute untransformed_layer = None, so check the value.
        while getattr(d, "untransformed_layer", None) is not None:
            d = d.untransformed_layer
        return d

    def compute_signature(self):
        sl = renpy.game.context().scene_lists
        sig = []
        for layer in renpy.config.layers:
            for sle in sl.layers.get(layer, ()):
                sig.append((layer, sle.tag, id(sle.displayable)))
        try:
            sig.append(id(renpy.display.focus.get_focused()))
        except Exception:
            pass
        return tuple(sig)

    def periodic(self):
        if self.disabled:
            return
        now = time.time()
        if TEST:
            self.test_drive(now)  # may raise Ren'Py's jump/quit exceptions on purpose
        try:
            sig = self.compute_signature()
            if sig != self.signature:
                self.signature = sig
                self.last_change = now
            interface = renpy.game.interface
            if not getattr(interface, "old_scene", None) or not self.server.has_clients():
                return
            busy = (now - self.last_change) < SETTLE or bool(getattr(interface, "ongoing_transition", None))
            interval = 1.0 / FPS if busy else (1.0 / IDLE_FPS if IDLE_FPS > 0 else 1e9)
            if now - self.last_capture < interval:
                return
            self.last_capture = now
            self.capture(now, busy)
            self.errors = 0
        except Exception:
            self.errors += 1
            import traceback
            log("capture failed (%d): %s" % (self.errors, traceback.format_exc()))
            if self.errors >= 5:
                log("too many errors; hook disabled for this session")
                self.disabled = True

    def masked(self, d):
        """d drawn with its alpha written into RGB (gray = alpha), as a premultiplied matrix."""
        if self.alpha_matrix is None:
            self.alpha_matrix = renpy.store.Matrix([0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1])
        return renpy.store.Transform(d, matrixcolor=self.alpha_matrix)

    def shoot(self, d, surf, st, at, W, H, need_mask, pos=None):
        """Returns (color, mask, f): screenshots of the render `surf` of `d`, cropped to its size.

        With pos=(x, y), `surf` is drawn at that screen position on a full-screen canvas and the
        whole screen is returned instead: many games draw sprites partly outside the render's
        reported box (transform offsets, zoom), and cropping to the box cut those parts off.
        f is screenshot pixels per game pixel (2.0 for a 1920x1080 game on a 4K screen)."""
        screenshot = renpy.display.draw.screenshot

        def placed(s):
            if pos is None:
                return s
            canvas = renpy.display.render.Render(W, H)
            canvas.blit(s, pos)
            return canvas

        t = time.time()
        color = screenshot(placed(surf))
        self.t_shot += time.time() - t
        f = color.get_width() / float(W)
        if pos is None:
            cw = min(color.get_width(), int(math.ceil(surf.width * f)))
            ch = min(color.get_height(), int(math.ceil(surf.height * f)))
        else:
            cw, ch = color.get_width(), color.get_height()
        if cw <= 0 or ch <= 0:
            return None, None, f
        t = time.time()
        color = self.own(color, cw, ch)
        self.t_copy += time.time() - t
        mask = None
        if need_mask:
            msurf = renpy.display.render.render(self.masked(d), W, H, st, at)
            t = time.time()
            mshot = screenshot(placed(msurf))
            self.t_shot += time.time() - t
            t = time.time()
            mask = self.own(mshot, cw, ch)
            self.t_copy += time.time() - t
        return color, mask, f

    @staticmethod
    def own(shot, cw, ch):
        """Crops a screenshot into a surface that owns its pixels.

        The screenshot's pixels live in a buffer Ren'Py reuses, so they must be copied here,
        on the main thread, before the encoder thread sees them (it also scales them down)."""
        src = getattr(shot, "_pixels_address", None)
        if src:
            # Raw copy in the screenshot's own pixel format: much faster than a converting blit.
            rv = pygame_sdl2.Surface((cw, ch), 0, shot)
            dst = rv._pixels_address
            sp, dp = shot.get_pitch(), rv.get_pitch()
            if sp == dp:
                ctypes.memmove(dst, src, dp * ch)
            else:
                row = cw * shot.get_bytesize()
                for y in range(ch):
                    ctypes.memmove(dst + y * dp, src + y * sp, row)
            return rv
        rv = renpy.display.pgrender.surface_unscaled((cw, ch), False)
        rv.blit(shot.subsurface((0, 0, cw, ch)), (0, 0))
        return rv

    def capture(self, now, busy):
        t0 = time.time()
        self.t_shot = self.t_copy = 0.0
        interface = renpy.game.interface
        scene = interface.old_scene
        W = renpy.config.screen_width
        H = renpy.config.screen_height
        items = []

        layers = list(renpy.config.layers)
        master_index = layers.index("master") if "master" in layers else -1
        ui_layers = []
        for li, layer in enumerate(layers):
            d = scene.get(layer)
            if d is None:
                continue
            if li <= master_index:
                items.extend(self.capture_scene_layer(layer, self.unwrap(d), W, H, now, busy))
            else:
                ui_layers.append(d)
        if ui_layers:
            box = renpy.display.layout.MultiBox(layout="fixed")
            for d in ui_layers:
                box.add(d)
            surf = renpy.display.render.render(box, W, H, 0, 0)
            color, mask, f = self.shoot(box, surf, 0, 0, W, H, True)
            if color is not None:
                meta = {"key": "ui", "kind": "ui", "tag": "ui", "name": "ui", "zorder": 0, "x": 0, "y": 0,
                        "w": int(round(color.get_width() / f)), "h": int(round(color.get_height() / f))}
                items.append((meta, color, mask))

        self.seq += 1
        if DUMP and (self.seq <= 5 or self.seq % 20 == 0):
            # What the player actually sees, for comparing with the split layers.
            frame = renpy.display.draw.screenshot(interface.surftree)
            bio = io.BytesIO()
            renpy.display.module.save_png(renpy.display.scale.smoothscale(frame, (960, 540)), bio, 1)
            Server.dump(self.seq, "frame", bio.getvalue(), None)
            sl = renpy.game.context().scene_lists
            log("capture %d scene lists: %s" % (self.seq, "; ".join("%s=%s" % (
                l, ",".join("%s" % (s.tag,) for s in sl.layers.get(l, []))) for l in renpy.config.layers)))
        self.server.submit((self.seq, W, H, items))
        if self.logged < 10 or self.seq % 100 == 0:
            self.logged += 1
            log("capture %d: %s in %.0f ms (screenshots %.0f ms, copies %.0f ms)" % (self.seq, ", ".join(
                "%s[%s] %dx%d@%d,%d" % (m["key"], m["kind"], m["w"], m["h"], m["x"], m["y"]) for m, _, _ in items),
                (time.time() - t0) * 1000, self.t_shot * 1000, self.t_copy * 1000))

    def capture_scene_layer(self, layer, lay, W, H, now, busy):
        render = renpy.display.render.render
        frame_time = renpy.game.interface.frame_time
        children = getattr(lay, "children", None) or []
        scene_list = getattr(lay, "scene_list", None) or []
        starts = getattr(lay, "start_times", None) or []
        anims = getattr(lay, "anim_times", None) or []

        def adjust(t):
            # Same child times as MultiBox.render for a layer, so renders come from the cache.
            if t is None or t is True:
                return 0
            return frame_time - t

        out = []
        seen = set()
        for i, child in enumerate(children):
            sle = scene_list[i] if i < len(scene_list) else None
            st = adjust(starts[i]) if i < len(starts) else 0
            at = adjust(anims[i]) if i < len(anims) else 0
            surf = render(child, W, H, st, at)
            if surf.width <= 0 or surf.height <= 0:
                continue
            x, y = child.place(None, 0, 0, W, H, surf)
            placement = (int(round(x)), int(round(y)), surf.width, surf.height)
            ckey = (layer, id(child))
            seen.add(ckey)
            cached = self.sprite_cache.get(ckey)
            # Reuse the last capture of an unchanged image; recapture while it may be animating.
            if cached is not None and cached[0] == placement and st > SETTLE and now - cached[1] < REFRESH:
                out.append(cached[2])
                continue
            tag = (sle.tag if sle is not None else None) or ("%s_%d" % (layer, i))
            name = " ".join(sle.name) if (sle is not None and sle.name) else tag
            # Captured full-screen at its real position, so nothing drawn outside its box is lost.
            color, mask, f = self.shoot(child, surf, st, at, W, H, True, pos=placement[:2])
            if color is None:
                continue
            full = (0, 0, W, H)
            kind = "sprite"
            if layer != "master" or ("%s" % tag).lower().startswith(BG_TAGS) or \
                    self.covers_screen(mask, full, f, W, H):
                kind = "bg"
                mask = None  # opaque
            meta = {"key": "%s:%s:%d" % (layer, tag, i), "kind": kind, "tag": "%s" % tag,
                    "name": "%s" % name, "zorder": sle.zorder if sle is not None else 0,
                    "x": 0, "y": 0,
                    "w": int(round(color.get_width() / f)), "h": int(round(color.get_height() / f))}
            item = (meta, color, mask)
            self.sprite_cache[ckey] = (placement, now, item)
            out.append(item)
        for k in list(self.sprite_cache):
            if k[0] == layer and k not in seen:
                del self.sprite_cache[k]
        return out

    @staticmethod
    def covers_screen(mask, placement, f, W, H):
        """True if the image is opaque over the whole screen (a background or CG)."""
        x, y, rw, rh = placement
        if x > W * 0.02 or y > H * 0.02 or x + rw < W * 0.98 or y + rh < H * 0.98:
            return False
        mw, mh = mask.get_size()
        for fx, fy in ((0.02, 0.02), (0.98, 0.02), (0.02, 0.98), (0.98, 0.98), (0.5, 0.5)):
            px = int((W * fx - x) * f)
            py = int((H * fy - y) * f)
            if not (0 <= px < mw and 0 <= py < mh):
                return False
            if mask.get_at((px, py))[0] < 250:
                return False
        return True

    # ---- test mode ----

    def test_drive(self, now):
        if now - self.started > TEST_SECONDS:
            log("test mode: time is up, quitting")
            renpy.exports.quit()
        if not self.test_started and renpy.exports.get_screen("main_menu") is not None and now - self.started > 3:
            self.test_started = True
            log("test mode: starting the game")
            renpy.exports.jump_out_of_context("start")
        if now - self.test_last_dismiss > 1.5:
            self.test_last_dismiss = now
            renpy.exports.queue_event("dismiss")


hook = Hook()
'''

    def _vn3d_hook_install():
        import sys as _sys
        import types as _types
        if "vn3d_hook_impl" in _sys.modules:
            # Script reload (Shift+R): the server is still running, re-attach the callbacks.
            _sys.modules["vn3d_hook_impl"].hook.attach()
            return

        def native(text):
            # Store code has unicode_literals (and str = unicode) on Python 2.
            return text.encode("ascii") if _sys.version_info[0] < 3 else text

        mod = _types.ModuleType(native("vn3d_hook_impl"))
        exec(compile(_vn3d_hook_source, native("vn3d_hook.rpy (impl)"), native("exec")), mod.__dict__)
        _sys.modules["vn3d_hook_impl"] = mod
        mod.hook.install()

    try:
        _vn3d_hook_install()
    except Exception as _vn3d_e:
        import traceback as _vn3d_tb
        renpy.display.log.write("vn3d: hook failed to load: %s" % _vn3d_tb.format_exc())
