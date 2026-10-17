# VN3D: play 2D games in 3D in VR (PSVR2 / SteamVR)

iw3 (in `D:\nunif`) turns the game window into side-by-side 3D with a depth model.
The Godot viewer shows it as a big screen in SteamVR, and `input_bridge.py` turns the
controller laser into mouse clicks on the game.

## Run

1. Start SteamVR and the game (windowed or fullscreen).
2. `vn3d_vr.bat "Game window title" [divergence]`  (divergence = 3D strength, 0–2, default 1.5)
3. Ctrl-C in that console stops iw3, the viewer and the bridge.

## Layers mode (Ren'Py games, no depth guessing)

For Ren'Py games a small hook inside the game sends the scene as separate layers, so the
viewer puts them on real depth planes instead of guessing depth (no warped text boxes, no
iw3, almost no GPU load):

| Layer | What | Distance |
| --- | --- | --- |
| bg | full-screen opaque images on the master layer (scene backgrounds, CGs) | 6 m |
| sprite | other master-layer images (characters), each on its own plane | 1.8 m, later ones 4 cm closer |
| ui | every layer above master: textbox, choices, menus, overlays | 1.2 m (the laser clicks this panel) |

All planes cover the same view angle, so from your head they line up like the flat game.

**Install** (per game): copy `renpy_hook\vn3d_hook.rpy` into the game's `game\` folder
(next to its `.rpa` archives). Works with Ren'Py 7.x (Python 2) and 8.x (Python 3). The game
archives are not changed.

**Run:** start SteamVR and the game, then `vn3d_vr.bat "Game window title" layers`.
The hook listens on 127.0.0.1:1305 only (never the LAN) and only renders while a viewer is
connected. It captures on every change (new line, sprite, menu, hover), keeps capturing at
2 captures/s for 1.5 s after a change (text typing out, transitions), then every 2 s.
Unchanged sprites and backgrounds are not captured again.

**Uninstall:** delete `vn3d_hook.rpy` and `vn3d_hook.rpyc` from the game's `game\` folder.
The hook stores nothing in saves or persistent data.

**Check it loaded:** the game's `log.txt` has `vn3d: hook installed (Ren'Py ...)`; errors are
logged there as `vn3d: ...` (after 5 failed captures in a row the hook turns itself off; the
game keeps running).

**Cost:** Ren'Py can only read layers back from the GPU as whole-window frames, so every
capture briefly stalls the game: about 55 ms per text/UI capture with a 4K window (most of it is
the 4K readback; a 1080p window is much cheaper), more when a new background arrives.
Each layer is sent as two PNGs, the color (drawn over black) and an alpha mask, because the
readback has no transparency; the viewer recombines them in `viewer/layer.gdshader`.

Hook settings are environment variables set before starting the game: `VN3D_PORT` (1305),
`VN3D_FPS` (2), `VN3D_IDLE_FPS` (0.5), `VN3D_MAX_WIDTH` (2560: images are sent at the window's
real resolution, scaled down to this width), `VN3D_DUMP=<short folder path>` (save the first
captures and matching full frames as PNG). `VN3D_TEST=1` is a test mode: it starts a new game
from the main menu, auto-advances, turns autosave off and quits after `VN3D_TEST_SECONDS` (60).
It does not touch save slots, but it marks lines as seen (persistent data).

Limits: needs the gl2 renderer (the default since Ren'Py 7.4). Layer-wide effects
(`show layer master at ...`, camera, screen shake) are not applied to the split sprites;
in-game dissolves are replaced by a switch at the next capture; an image that covers the whole
screen with no transparency counts as background, so games drawn as full-screen CGs
give a background plane plus the UI panel, with no separate sprites.

## Controls

Everything works from the right controller alone (the left one is optional).

| Input | Action |
| --- | --- |
| Trigger, laser on screen | Click there (advance text, choose options) |
| Trigger, laser off screen | Bring the screen in front of you |
| Grip | Right click (Ren'Py game menu) |
| A | Go back one line (rollback) |
| B | Recenter screen; hold 1 s: swap eyes |
| Right stick left / right | 3D strength −/+ (or shape boost / screen size, see stick click) |
| Right stick up / down | Screen closer / farther (layers mode: sprite plane closer / farther) |
| Stick click | Cycle what left/right changes: 3D strength → shape boost → screen size |
| Stick click, hold 1 s | Curved / flat screen |
| Left stick up / down | Rollback / roll forward (if the left controller is on) |
| PC keys in the viewer window | R recenter, S swap eyes, C curved, +/− strength, [ ] shape boost |

Screen size, distance, curve and eye swap are saved in
`%APPDATA%\Godot\app_userdata\VN3D Viewer\settings.cfg`. 3D strength and shape boost are
saved per game in `%APPDATA%\VN3D-stable\strength.json` (read by the desktop launcher).

### 3D tuning

- **3D strength** (iw3 divergence, 0.2–5): total depth is about 1% of the image width per unit.
- **Auto-convergence**: the viewer reads your eye spacing from the headset and keeps the
  farthest point within what your eyes can fuse for the current screen size, putting the rest
  of the depth in front of the screen. Without it, a big screen (e.g. 4 m) pushed the background
  past the eye spacing above strength ~1.6 and the picture read flat.
- **Shape boost** (0–3): depth + k × (depth − blur(depth)) for rounder bodies/objects; ~1.4 ms.
- Depth model input is 518 px tall (`-DepthResolution`); 392 is faster, larger models were not
  better on game art (see `tests/compare_depth_models.py`, `tests/spike_*.py`).
- iw3's control channel (`iw3_fast.py`, UDP 127.0.0.1:1306): `divergence <v>`,
  `convergence <v>`, `shape <k>`; a change re-processes the last frame, so it shows on still scenes.

### Watching videos in 3D (VLC)

Launcher button **Watch video...**: VLC (`C:\Program Files\VideoLAN\VLC\vlc.exe`) opens the file in
minimal view (no menus or controls in the picture), with its remote control on 127.0.0.1:8190
(random password per run). The launcher reads the video size from VLC and sizes the window to
the chosen **Video size** (720p / 1080p / 1440p / 2160p experimental; also the 3D stream height;
remembered in `%APPDATA%\VN3D-stable\launcher.json`), so small videos are scaled up and large ones
fit. 2160p fills a 4K monitor, so the window's title bar is placed off-screen
(`window_crop.py --frame-offscreen`): a screen-filling window counts as fullscreen and freezes
window capture, an off-screen-framed one doesn't (`tests/capture_rate.py`: 60 fps at 3840x2160).
2160p costs frame rate (7680x2160 3D frames). With **Upscale videos (RTX Super
Resolution)** ticked VLC uses `--d3d11-upscale-mode=super` (also switch on NVIDIA App → System →
Video → RTX Video Enhancement → Super Resolution). In VR: a seek bar under the screen (aim and
pull the trigger to jump), trigger on the picture = play/pause, A = −10 s, grip = +10 s.
Videos share one remembered strength / shape boost. Test with `tests/make_test_clip.py` (a
generated clip), not personal media.

### Desktop launcher (stable copy)

`D:\vn3d-stable\vn3d_launcher.ps1` (desktop shortcut "VN3D (Ren'Py in VR)"): pick a Ren'Py
game (Downloads is scanned automatically, or Add game), set strength and shape boost, Play.
It starts SteamVR if needed, starts the game, switches a fullscreen Ren'Py game to a window
(fullscreen games freeze window capture until Alt-Tab), waits for its title bar, then runs
`vn3d_vr.ps1`.
The viewer log (stream FPS, controller profiles) is in `...\VN3D Viewer\logs\godot.log`.

## Pieces

- `vn3d_vr.ps1`: launcher (iw3 on 127.0.0.1:1303, bridge on 127.0.0.1:1304, viewer;
  `-Layers` skips iw3 and starts the viewer in layers mode)
- `viewer/`: Godot 4.7 OpenXR project (MJPEG client, SBS shader, laser pointer, layers mode:
  `godot --path viewer -- --mode=layers`)
- `renpy_hook/vn3d_hook.rpy`: Ren'Py hook for layers mode. Wire format: `VN3D` + uint32
  big-endian header length + JSON header + PNG blobs (format details at the top of the file)
- `input_bridge.py`: UDP commands to SendInput on the game window. The Windows cursor stays
  parked outside the game window and only jumps in for a click (window capture always draws
  the real cursor). `--hover` keeps it on the laser point instead: hover effects work, but
  the cursor shows in the 3D picture.
- `window_crop.py`: measures the game window's title bar and borders; the launcher passes
  them to iw3 as `--crop-*` so only the game area is shown. Restores a minimized game window
  first (a minimized window crashes iw3).
- `iw3_fast.py`: runs iw3-desktop with the depth model replayed through CUDA graphs. iw3 is
  CPU-bound (~700 small kernel launches per frame); graphs cut a 1080p frame from 32.5 ms to
  14.1 ms with identical output (`tests\check_graph_depth.py`). `VN3D_NO_GRAPHS=1` = stock iw3.
- `tests/bench_iw3.py`, `tests/profile_iw3.py`: time / profile iw3 steps on the live game window.

## Frame rate

The headset renders at its own rate (PSVR2: 120 Hz, `preferredRefreshRate` in SteamVR), so head
movement is always smooth. The game picture updates at what the chain allows:
game (~60 FPS) -> iw3 (~70 FPS alone, ~40 FPS while SteamVR renders) -> viewer (~63 FPS at
1080p with mipmaps). Close GPU-heavy apps (ComfyUI) first: with VRAM full it drops to ~1 FPS
and SteamVR can crash.
- `tests/fake_iw3_stream.py`: fake iw3 stream, for testing the viewer without the GPU:
  `python -I tests\fake_iw3_stream.py`, then
  `godot --headless --xr-mode off --path viewer`
- `tests/fake_layer_stream.py`: fake Ren'Py hook (background, two sprites, textbox):
  `python -I tests\fake_layer_stream.py`, then
  `godot --headless --xr-mode off --path viewer -- --mode=layers`
- `tests/layer_client.py`: logs what a running hook sends (`python -I tests\layer_client.py 1305 60 <png folder>`)

## Local patch to iw3

`D:\nunif\iw3\desktop\screenshot_thread_cuda.py`: window capture now scales a window bigger
than the stream (e.g. 4K fullscreen) instead of cropping its top-left corner. A `git pull`
in `D:\nunif` may conflict with it; `git -C D:\nunif diff` shows it.
