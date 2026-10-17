# VN3D Launcher and Game Library: Design

Date: 2026-10-16
Status: draft for review
Sub-project 1 of 4 (launcher). Later sub-projects: backends (hybrid, ReShade depth, UEVR), fast GPU-capture viewer, better 3D.

## 1. Intent

The user plays flat PC games (visual novels and normal 3D games) on a PSVR2 through SteamVR,
with a 3D effect. Today this works through scripts (`vn3d_vr.bat`, iw3, a Ren'Py add-on, a Godot
viewer, an input bridge), started by hand per game with a typed window title.

This sub-project turns that into one app:

- a game library the user adds games to by picking the game's `.exe`;
- automatic engine detection, window finding and a suggested 3D method per game;
- per-game settings, including a controller layout (mouse/keys or virtual Xbox pad);
- a PC window for managing the library and a VR view for picking and playing games;
- a backend interface that later 3D methods plug into without changing the launcher.

Success: the user adds a Ren'Py visual novel and a Unity or Unreal game from the PC window, puts the
headset on, picks a game with the laser, plays it in 3D with their chosen controller layout,
opens the in-game menu, returns to the library, and never types a window title or runs a script.

### Decisions made with the user

| Topic | Decision |
| --- | --- |
| First sub-project | Launcher and library, using today's backends (depth, layers) |
| Where the launcher runs | Both: PC window for managing, VR for picking and playing |
| Controller layouts | Per game: mouse/keys mode or virtual Xbox pad mode |
| Adding games | Pick the `.exe`; auto-detect engine, window and 3D method |
| Technology | One Godot app for PC and VR (approach A) |

### Environment

Windows 11, RTX 5070 Ti (16 GB), Ryzen 7 7800X3D (16 threads), PSVR2 via Sony PC adapter and
SteamVR (OpenXR, 120 Hz), Godot 4.7.2, iw3 in `D:\nunif` (venv `D:\nunif\venv`, Python 3.12).
ComfyUI often runs on the same GPU and can hold 9-12 GB of VRAM.

### Already built (stable copy, carried into the app)

Built and tested in the headset on 2026-10-16 (`D:\vn3d-stable`, merged on `feat/launcher`):

- `iw3_fast.py` control channel (UDP 127.0.0.1:1306): `divergence`, `convergence`, `shape`;
  a change re-processes the last frame so it shows on still scenes.
- Auto-convergence in the viewer from the headset's eye spacing and the screen width (the
  far point stays within what the eyes can fuse). Total depth ≈ 1% of image width per strength unit.
- Shape boost (rounder local shapes), curved screen with matching laser hit test.
- Right-controller-only controls with on-screen readouts; stick click cycles strength /
  shape boost / screen size.
- Fullscreen games freeze window capture until Alt-Tab: the launcher switches a fullscreen
  Ren'Py game to a window (posting F to its window) and waits for its title bar before cropping.
- Depth model input 518 px. Bigger models and tiled/normal-based refinement were tried and gave
  no visible gain on game art (tests/spike_*.py).

- Videos (added 2026-10-17): "Watch video" opens a file in VLC (minimal view, remote control on
  127.0.0.1:8190 with a random password per run, window sized to 1080 px tall from the video's
  resolution, optional RTX Super Resolution via `--d3d11-upscale-mode=super`). In VR: seek bar
  under the screen, trigger = play/pause, A/grip = ∓10 s. Videos are not library entries; they
  share one remembered strength/shape setting under the key `video`.

The app's Session, Backends and Input units reuse these instead of re-implementing them. The app
keeps "Watch video" as a second way to start a session (PC window button and VR library tile).

## 2. Architecture

One Godot 4.7 project in `D:\vn3d\app`, grown from the current `D:\vn3d\viewer` project.

On start the app always opens a PC window with the library. If an OpenXR runtime with a headset is
available, the main viewport also renders to the headset, showing the VR library. Both views use
the same Library and Session objects, so they stay in sync. The PC window is a separate OS window
(Godot `Window` node with `gui_embed_subwindows = false`); the main viewport is the XR view.
Without a headset the main viewport shows a flat preview.

### Units

Each unit is one script (or a small folder) with one job and a narrow interface.

| Unit | File(s) | Job | Depends on |
| --- | --- | --- | --- |
| Library | `core/library.gd` | Load, save and back up `library.json`; add, update and remove games; emit `changed` | nothing |
| Detector | `core/detector.gd` | From an `.exe` path: engine, real game exe, suggested name, default method and layout preset | filesystem only |
| Layouts | `core/layouts.gd` | Built-in presets, validation, and mapping controller input to actions | nothing |
| Session | `core/session.gd` | Play and stop flow: pre-checks, start the game, find its window, start backend and input, track play time | Library, Backends, Input, Platform |
| Platform | `core/platform.gd` + `tools/winhelper.py` | Windows facts Godot can't get directly: window of a process tree, restore and crop, free VRAM and top VRAM user, SteamVR state | Python helper |
| Backends | `backends/backend.gd` (interface), `backends/depth_backend.gd`, `backends/layers_backend.gd` | Start and stop one 3D method and deliver frames to the Stage | Stage |
| Stage | `stage/stage.gd`, existing shaders | Draw the VR screen (SBS) or the layer planes; recenter, distance and size | nothing |
| Input | `input/input_router.gd` + `input_bridge.py` | Read Sense controllers, apply the active layout, send mouse/keys or gamepad commands to the bridge, handle the reserved menu chord | Layouts |
| PC UI | `ui/pc/*.tscn` | Library grid, Add Game, game page, layout editor, status bar | Library, Session |
| VR UI | `ui/vr/*.tscn` | VR library shelf, in-game menu; same card and button scenes as the PC UI, drawn into a `SubViewport` on a quad | Library, Session, Input |

Python helpers stay in Python: iw3 (`iw3_fast.py`), the input bridge, and a new small
`tools/winhelper.py` for Windows queries (process tree, windows, DPI-correct rects, VRAM).
Godot starts them with `OS.create_process` / `OS.execute_with_pipe` and talks to them over
localhost sockets or stdout JSON lines. All sockets bind to `127.0.0.1` only.

### Backend interface

```gdscript
class_name Backend extends Node
signal status(text: String)          # "Loading depth model... 40 s"
signal failed(reason: String)        # shown in VR with Retry
func start(game: Dictionary, window: Dictionary) -> void   # window = {hwnd, title, crop}
func stop() -> void
func is_running() -> bool
```

The Stage pulls frames from the active backend (SBS texture or layer set). Later backends (hybrid,
ReShade, GPU capture, UEVR) implement the same interface.

Existing code moves, it isn't rewritten: the MJPEG client, decode pool and SBS shader from
`viewer/main.gd` go into `depth_backend.gd` and `stage.gd`; the layers client into
`layers_backend.gd`; the laser and controller code into `input_router.gd`.

## 3. Data

File: `%APPDATA%\VN3D\library.json`. Every save writes a temp file, copies the old file to
`library.json.bak`, then renames the temp file into place.

```json
{
  "version": 1,
  "games": [
    {
      "id": "c2f1b9e0",
      "name": "My Visual Novel",
      "exe": "C:\\Games\\MyVN\\MyVN.exe",
      "args": "",
      "workdir": "C:\\Games\\MyVN",
      "engine": "renpy",
      "method": "depth",
      "depth": { "divergence": 1.5, "shape_boost": 0.0, "depth_resolution": 518, "stream_height": 1080 },
      "screen": { "distance": 3.0, "width": 3.6, "curved": false },
      "layout": { "preset": "visual_novel", "mode": "mouse", "bindings": {
        "right_trigger": "click", "right_grip": "right_click",
        "left_stick_up": "wheel_up", "left_stick_down": "wheel_down",
        "right_primary": "recenter", "right_secondary": "swap_eyes" } },
      "renpy_hook_installed": false,
      "cover": "covers/c2f1b9e0.jpg",
      "last_played": "2026-10-16T22:40:00",
      "play_seconds": 5400
    }
  ]
}
```

Covers live in `%APPDATA%\VN3D\covers\`, grabbed from the game window about 20 s after the
first successful play.

### Controller layouts

- `mode`: `mouse` or `gamepad`.
- `bindings`: map from input to action. Inputs: `left|right` × `trigger`, `grip`, `primary`
  (A/X), `secondary` (B/Y), `stick_click`, `stick_up`, `stick_down`, `stick_left`, `stick_right`,
  plus `stick` (analog, gamepad mode only). Inputs not listed do nothing.
- Mouse mode actions: `click`, `right_click`, `wheel_up`, `wheel_down`, `key:<name>`,
  `recenter`, `swap_eyes`, `screen_closer`, `screen_farther`, `screen_bigger`, `screen_smaller`, `none`.
  The laser always moves the pointer in mouse mode.
- Gamepad mode actions: `pad:a|b|x|y|lb|rb|lt|rt|ls|rs|start|back|dpad_*`, and the analog
  sticks map to the pad's sticks. No laser in gamepad mode.
- Binding keys are `<hand>_<input>`, for example `right_trigger` or `left_stick_up`.
- Reserved in every layout: holding the left controller's menu (Options) button for 1 s opens
  the VN3D in-game menu. It can't be rebound, so the user can always get out. (The right
  controller's matching button is SteamVR's system button and never reaches apps.)
- Presets: `visual_novel` (today's mapping: trigger click, grip right click, left stick
  rollback/forward, right stick screen distance/size, A recenter, B swap eyes) and `gamepad`
  (Sense mapped 1:1 to an Xbox pad). A game gets its own copy of a preset; editing a game's
  layout never changes the preset.

## 4. Detection

Input: path to the picked `.exe`. Checks run on the exe's folder, in order:

| Engine | Signature |
| --- | --- |
| `renpy` | `renpy\` and `game\` folders |
| `unreal` | `Engine\` folder, or an exe matching `*-Win64-Shipping.exe` under `*\Binaries\Win64\`. If the picked exe is a small launcher at the root, the shipping exe is used as the real game exe |
| `unity` | `UnityPlayer.dll` and a `<name>_Data\` folder |
| `rpgmaker` | `www\js\rpg_core.js` (MV) or `js\rmmz_core.js` (MZ) |
| `tyrano` | `tyrano\` folder (also inside `resources\app` or `package.nw`) |
| `godot` | a `.pck` file next to the exe with the exe's name |
| `unknown` | none of the above |

Suggested name: Ren'Py `config.name` from the game's `log.txt` if present, otherwise the exe's
version-info product name, otherwise the folder name. Default method: `depth` for every engine
until later backends exist; Ren'Py can be switched to `layers`. Default layout preset:
`visual_novel` for renpy, rpgmaker and tyrano; `gamepad` for everything else.

The user sees the detection result in an editable dialog before the game is added.

## 5. Play and stop flow

1. Pre-checks
   - SteamVR not running: offer "Start SteamVR" (runs `steam://rungameid/250820`) or "Play flat".
   - Free VRAM under 4 GB: show the biggest VRAM user by name and size, with buttons
     "Close <name>" and "Play anyway". The app closes only that one process, only after this click.
   - Ren'Py with `layers` method and no hook installed: ask before copying `vn3d_hook.rpy` into
     the game's `game\` folder, then record `renpy_hook_installed: true`.
2. Start the game with its working folder and arguments; keep its process ID.
3. Find the window: poll every 500 ms for up to 60 s for the first visible, non-tool window
   owned by the process or any descendant (covers launcher exes). Restore it if minimized.
   If it covers its whole monitor (fullscreen), switch it to a window (Ren'Py: post F; other
   engines: post Alt+Enter, then ask the user if it stays fullscreen) and wait for its title bar.
   Measure the crop (title bar and borders) DPI-correctly, as `window_crop.py` does today.
4. Start the backend with `{hwnd, title, crop}` and the game's settings. Start the input bridge
   with the game's layout. Show backend `status` text on the VR screen until the first frame.
5. While playing: on the in-game menu's "Back to library" the app asks "Close the game too?".
   When the game process exits on its own, the session stops.
6. Stop: stop backend, tell the bridge to release everything, add play time, save the library,
   return both UIs to the library.

### Known issue to address in this sub-project

iw3 takes about 3 minutes from start to the first frame. The plan includes measuring where that
time goes (imports, model load, torch hub checks, CUDA init) and fixing the main cause. Keeping
the depth backend process warm while the user browses the library is the fallback.

## 6. Interfaces

### PC window

- Library grid of cover cards (name, engine badge, last played); "missing" badge when the exe
  is gone.
- Add Game: Windows file dialog for `.exe` files, then the editable detection dialog.
- Game page: Play, 3D method, 3D strength slider, screen distance and size, controller layout,
  Remove (offers to remove the Ren'Py hook if the app installed it).
- Layout editor: a drawing of both Sense controllers with a dropdown per input; a Mouse/Gamepad
  switch; "Reset to preset".
- Status bar: SteamVR state, free VRAM, and while playing, the game and picture FPS.

### VR

- Library shelf: curved row of cover cards about 2 m in front; laser and trigger select; stick
  scrolls; Play button on the selected card.
- In-game menu (reserved chord): Resume, Recenter, 3D strength +/-, Swap eyes,
  Back to library, Quit game. Changes to strength, distance and size are saved to that game.
- No layout editing in VR.
- VR panels are the same Control scenes as the PC UI, rendered into a `SubViewport` on a quad;
  the laser hit point is sent as mouse events into that viewport.

## 7. Input

The Input Router reads Sense controller state each frame from Godot's OpenXR action map (Sense
controllers show up under SteamVR's `oculus/touch_controller` profile), applies the active
game's layout, and sends commands to `input_bridge.py` over UDP on `127.0.0.1:1304`.

The bridge gains:

- a `layout` command at session start;
- gamepad mode through a virtual Xbox 360 pad (`vgamepad` package on the ViGEmBus driver);
- a `release_all` command, also run when the bridge exits, which lifts held keys and buttons,
  unplugs the virtual pad and frees the cursor.

If ViGEmBus isn't installed, gamepad layouts are marked "driver needed" with a link to the
driver's install page, and mouse layouts keep working. The app never installs drivers itself.

## 8. Errors

| Problem | Behaviour |
| --- | --- |
| Game exe moved or deleted | Card shows "missing" and a "Find it" button to relink |
| Window not found in 60 s | Message with "Keep waiting" and "Pick window" (list of visible windows) |
| Backend crash (iw3 error, CUDA out of memory) | VR shows the reason and Retry; the game keeps running |
| VRAM full mid-game | Message names the biggest VRAM user |
| SteamVR off or headset not found | Flat preview plus the hint: turn the PSVR2 on, then restart SteamVR |
| `library.json` damaged | Load `library.json.bak` and tell the user |
| ViGEmBus missing | Gamepad layouts disabled with a "driver needed" note |
| Any session end | Bridge `release_all`, backend stopped, cursor freed |

## 9. Testing

Automatic tests run on the CPU only, so they're safe while other GPU work runs:

- Library: load, save, backup and recovery from a damaged file.
- Detector: fake game folders for each engine signature, including an Unreal launcher exe.
- Layouts: preset validity, input-to-action mapping, the reserved menu chord.
- Bridge: command parsing and layout application with a fake gamepad and fake SendInput.
- Session flow, headless: Godot with `--headless --xr-mode off`, the existing fake iw3 and
  fake layer streams, and a small fake game (a Python window) to test Add, Play, finding the
  window, Stop and play-time tracking.

Manual headset check after each milestone: a Ren'Py game in depth and layers mode, and one
Unity or Unreal game in gamepad mode.

## 10. Out of scope

Separate specs later: hybrid Ren'Py mode (AI depth per layer, flat UI), ReShade depth-buffer
3D, GPU-capture viewer at 90-120 FPS, UEVR, better depth models, Steam library scanning,
editing layouts in VR.
