# VN3D Launcher and Game Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the VN3D scripts into one Godot app with a game library (PC window + VR shelf), per-game settings and controller layouts, a backend interface for 3D methods, and the existing video mode.

**Architecture:** The Godot project `viewer/` becomes `app/` and is split into focused units (Library, Detector, Layouts, Session, Platform, Backends, Stage, Input, PC UI, VR UI). Python stays for iw3 (`iw3_fast.py`), the input bridge and a new Windows helper (`tools/winhelper.py`); Godot starts them as processes and talks over 127.0.0.1 sockets or JSON lines on stdout. Existing behaviour (auto-convergence, shape boost, curved screen, seek bar, layers mode) is moved, not rewritten.

**Tech Stack:** Godot 4.7.2 (GDScript, OpenXR, Mobile renderer), Python 3.12 in `D:\nunif\venv` (stdlib `unittest`, pywin32, tkinter, OpenCV), iw3/nunif, VLC 3 HTTP interface, optional `vgamepad` + ViGEmBus.

**Spec:** `docs/superpowers/specs/2026-10-16-vn3d-launcher-design.md`

## Global Constraints

- Repo `D:\vn3d`, branch `feat/launcher`. `D:\vn3d-stable` is the user's working copy: never edit it from this plan.
- Godot: `%LOCALAPPDATA%\Microsoft\WinGet\Packages\GodotEngine.GodotEngine_Microsoft.Winget.Source_8wekyb3d8bbwe\Godot_v4.7.2-stable_win64_console.exe` (call it `GODOT` below).
- Python: `D:\nunif\venv\Scripts\python.exe` (`PY`), always `-I` for repo scripts. No pytest: tests use `unittest`.
- Library file `%APPDATA%\VN3D\library.json`, backup `library.json.bak`, covers in `%APPDATA%\VN3D\covers\`.
- All sockets bind `127.0.0.1` only. Ports: iw3 stream 1303, input bridge 1304, Ren'Py hook 1305, iw3 control 1306, VLC remote 8190.
- Defaults: divergence 1.5, shape boost 0.0, depth resolution 518, stream height 1080, screen distance 3.0 m, width 3.6 m, flat.
- Reserved controller chord: hold the **left** menu button 1 s = VN3D in-game menu, in every layout.
- The app never installs drivers; it may offer `pip install vgamepad` only after the user agrees.
- Tests run on the CPU only (`--headless --xr-mode off`); never start SteamVR or iw3 on the GPU in automated tests.
- Never use the user's own media or game folders as test input; use generated fixtures (`tests/make_test_clip.py`, temp dirs).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Window titles with `[ ]`, quotes or non-ASCII (video file names, Japanese VNs): window finding, crop and iw3's exact-title capture must still work. Test in Task 5.
2. Games whose exe is a launcher that starts another process (Unreal, some Ren'Py builds): the session must find the window in the process tree. Test in Task 5 and Task 9.
3. A damaged or half-written `library.json` (crash during save, both UIs saving): load the `.bak`, never lose the library. Test in Task 2.
4. The game window closing mid-session (game quit, crash, VLC end of video): everything stops, keys and buttons are released, no processes left holding ports 1303/1304/1306. Test in Task 9.
5. Leftover VN3D processes from an earlier run still holding the ports: Play must clean them up or say which process blocks. Test in Task 9.

---

### Task 1: Move the project to `app/` and add test runners

**Files:**
- Move: `viewer/` → `app/` (`git mv`), keep `project.godot` name "VN3D Viewer" for now (Task 10 renames).
- Create: `app/tests/run_tests.gd`, `app/tests/test_smoke.gd`, `tests/py/__init__.py`, `tests/py/test_smoke.py`
- Modify: `vn3d_vr.ps1` (viewer path → `$PSScriptRoot\app`), `tests/test_curved_screen.gd`, `tests/test_seek_bar.gd` (move into `app/tests/` as `test_curved_screen.gd`, `test_seek_bar.gd` converted to the runner format)

**Interfaces:**
- Produces: GDScript test convention used by every later task: a file `app/tests/test_<unit>.gd` that `extends RefCounted` with methods `func test_<name>(t) -> void`; `t` has `eq(a, b, msg := "")`, `ok(cond: bool, msg := "")`, `approx(a: float, b: float, eps := 1e-3, msg := "")`, `tmp_dir() -> String` (fresh dir under `user://test_tmp/`), and `scene_root() -> Node` (the SceneTree root, for tests that need nodes in the tree).
- Produces: Python test convention: `tests/py/test_<unit>.py` with `unittest.TestCase`, run by `PY -m unittest discover -s D:\vn3d\tests\py -t D:\vn3d`.

- [ ] **Step 1:** `git mv viewer app`; update `vn3d_vr.ps1` and README paths; confirm `GODOT --headless --xr-mode off --path D:\vn3d\app --quit` exits without `SCRIPT ERROR`.
- [ ] **Step 2: Write `app/tests/run_tests.gd`** (`extends SceneTree`): on the first `_process` frame, load every `res://tests/test_*.gd`, call each `test_*` method with a fresh `t`, print `PASS <file>::<method>` / `FAIL <file>::<method>: <msg>`, then `ALL PASSED (<n>)` or `FAILED <k> of <n>`, and `quit(0 or 1)`.
- [ ] **Step 3: Write `test_smoke.gd`** with `test_runner_works(t)`: `t.eq(1 + 1, 2)`, and convert the two existing Godot tests into runner methods (`test_curved_hit_matches_mesh`, `test_seek_bar_fraction`, `test_seek_bar_autohide`) with the same assertions they have today.
- [ ] **Step 4: Run** `GODOT --headless --xr-mode off --path D:\vn3d\app --script res://tests/run_tests.gd`. Expected: `ALL PASSED (4)`.
- [ ] **Step 5: Python runner:** `tests/py/test_smoke.py::test_imports` imports `window_crop` and `input_bridge` (with `sys.path` set to `D:\vn3d`). Run `PY -m unittest discover -s D:\vn3d\tests\py -t D:\vn3d -v`. Expected: `OK`.
- [ ] **Step 6: Commit** `refactor: move viewer to app/ and add GDScript/Python test runners`.

### Task 2: Library

**Files:** Create `app/core/library.gd`, `app/tests/test_library.gd`

**Interfaces:**
- Produces: `class_name Library extends RefCounted`
  - `func _init(path := OS.get_environment("APPDATA").path_join("VN3D/library.json"))`
  - `signal changed`
  - `func load() -> String` returns `""` or a warning (e.g. `"library.json was damaged; loaded the backup"`)
  - `func save() -> void` (temp file → copy old to `.bak` → rename)
  - `func games() -> Array[Dictionary]` sorted by `last_played` desc, then `name`
  - `func get_game(id: String) -> Dictionary`, `func add_game(g: Dictionary) -> String` (fills defaults, returns new 8-hex-char id), `func update_game(id: String, patch: Dictionary) -> void` (deep merge), `func remove_game(id: String) -> void`
  - `static func default_game() -> Dictionary` exactly the spec's JSON shape with Global Constraints defaults; `layout` = `Layouts.copy_preset("visual_novel")` (Task 3; until then `{}`).
  - `func get_media_settings() -> Dictionary` / `func set_media_settings(d)` for the shared `video` key `{divergence, shape_boost}`.

- [ ] **Step 1: Failing tests** in `test_library.gd`: `test_add_save_reload` (add 2 games, save, new Library on same path, `t.eq(games().size(), 2)`, fields round-trip), `test_defaults_filled` (`add_game({"name":"X","exe":"C:/x.exe"})` → `depth.divergence == 1.5`, `depth.depth_resolution == 518`, `screen.curved == false`), `test_update_deep_merge` (patch `{"depth":{"shape_boost":1.0}}` keeps `divergence`), `test_damaged_file_uses_backup` (save twice, overwrite `library.json` with `"{garbage"`, `load()` returns non-empty warning and the games from `.bak`), `test_missing_file_is_empty` (`load()` → `""`, 0 games), `test_sort_last_played`.
- [ ] **Step 2: Run tests** → FAIL (`Library` not defined).
- [ ] **Step 3: Implement** `library.gd` per Interfaces; JSON via `JSON.stringify(data, "  ")`; file version key `"version": 1`.
- [ ] **Step 4: Run tests** → all PASS.
- [ ] **Step 5: Commit** `feat(app): library storage with backup recovery`.

### Task 3: Layouts

**Files:** Create `app/core/layouts.gd`, `app/tests/test_layouts.gd`

**Interfaces:**
- Produces: `class_name Layouts extends RefCounted`
  - `const INPUTS := ["trigger","grip","primary","secondary","stick_click","stick_up","stick_down","stick_left","stick_right","stick"]` (bound per hand as `"<left|right>_<input>"`)
  - `const MOUSE_ACTIONS := ["click","right_click","wheel_up","wheel_down","recenter","swap_eyes","screen_closer","screen_farther","screen_bigger","screen_smaller","strength_up","strength_down","cycle_stick","none"]` plus `"key:<name>"`
  - `const PAD_ACTIONS := ["pad:a","pad:b","pad:x","pad:y","pad:lb","pad:rb","pad:lt","pad:rt","pad:ls","pad:rs","pad:start","pad:back","pad:dpad_up","pad:dpad_down","pad:dpad_left","pad:dpad_right","pad:stick_left","pad:stick_right","none"]`
  - `static func preset(name: String) -> Dictionary` for `"visual_novel"`, `"gamepad"`, `"video"`
  - `static func copy_preset(name: String) -> Dictionary` (deep copy with `"preset": name`)
  - `static func validate(layout: Dictionary) -> Array[String]` (errors: unknown input/action, action not allowed in mode, binding of the reserved `left_menu`)
  - `static func action_for(layout: Dictionary, input: String) -> String` (`"none"` if unbound)
  - `static func preset_for_engine(engine: String) -> String`: `visual_novel` for renpy/rpgmaker/tyrano, else `gamepad`.

Presets (the values the router relies on; matches today's stable controls):
- `visual_novel` (mouse): right_trigger click, right_grip right_click, right_primary wheel_up (Ren'Py rollback), right_secondary recenter, right_stick_click cycle_stick, right_stick_left strength_down, right_stick_right strength_up, right_stick_up screen_closer, right_stick_down screen_farther, left_stick_up wheel_up, left_stick_down wheel_down.
- `video` (mouse): as `visual_novel` but right_trigger `key:space`, right_primary `key:left`, right_grip `key:right` (the router sends VLC remote commands instead when a VLC password is present).
- `gamepad`: right/left trigger → `pad:rt`/`pad:lt`, grips → `pad:rb`/`pad:lb`, right primary/secondary → `pad:a`/`pad:b`, left primary/secondary → `pad:x`/`pad:y`, sticks → `pad:stick_right`/`pad:stick_left`, stick clicks → `pad:rs`/`pad:ls`.

- [ ] **Step 1: Failing tests:** `test_presets_valid` (`validate(preset(n)).is_empty()` for all three), `test_reserved_menu_rejected` (`{"mode":"mouse","bindings":{"left_menu":"click"}}` → 1 error), `test_pad_action_in_mouse_mode_rejected`, `test_action_for_unbound_is_none`, `test_copy_is_deep` (mutating a copy doesn't change `preset()`), `test_engine_presets` (`renpy` → `visual_novel`, `unity` → `gamepad`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5:** Library `default_game()` now uses `Layouts.copy_preset("visual_novel")`; rerun Task 2 tests → PASS.
- [ ] **Step 6: Commit** `feat(app): controller layouts and presets`.

### Task 4: Detector

**Files:** Create `app/core/detector.gd`, `app/tests/test_detector.gd`

**Interfaces:**
- Produces: `class_name Detector extends RefCounted`, `static func detect(exe_path: String) -> Dictionary` returning `{engine, real_exe, name, method, layout_preset, notes: Array[String]}`; engines and signatures exactly as spec §4; `method` is `"depth"`; `name` from Ren'Py `log.txt` (line after the `Ren'Py x.y` line and a blank line), else the folder name.

- [ ] **Step 1: Failing tests** building fake folders in `t.tmp_dir()`: `test_renpy` (`renpy/`, `game/`, `log.txt` with `"Ren'Py 8.5.3\n\nMy VN\n"` → engine renpy, name "My VN", preset visual_novel), `test_unreal_launcher` (root `Game.exe` + `Game/Binaries/Win64/Game-Win64-Shipping.exe` + `Engine/` → engine unreal, `real_exe` ends with `-Win64-Shipping.exe`), `test_unity` (`UnityPlayer.dll`, `Game_Data/`), `test_rpgmaker_mv` (`www/js/rpg_core.js`), `test_rpgmaker_mz` (`js/rmmz_core.js`), `test_tyrano` (`resources/app/tyrano/`), `test_godot` (`Game.pck` beside `Game.exe`), `test_unknown`, `test_name_with_brackets` (folder `My Game [v1.2]` → name keeps brackets).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** with `DirAccess`/`FileAccess` only. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(app): engine detection`.

### Task 5: Windows helper and Platform

**Files:** Create `tools/winhelper.py`, `tests/py/test_winhelper.py`, `tests/py/fake_game.py`, `app/core/platform.gd`, `app/tests/test_platform.gd`

**Interfaces:**
- Produces (`tools/winhelper.py`, one JSON object per command on stdout, DPI-aware, built from `window_crop.py` which stays as a thin wrapper for the stable scripts):
  - `find-window --pid <pid> [--timeout S]` → `{"hwnd": int, "title": str, "pid": int}` or `{"error": "not found"}`; searches the pid and all descendants, visible, non-tool, titled windows.
  - `prepare-window --hwnd <h> [--renpy]` → `{"fullscreen_before": bool, "windowed": bool, "crop": [top,left,right,bottom], "client": [w,h]}`: restores if minimized; if fullscreen, posts F (Ren'Py, WM_KEYDOWN scancode 0x21) or Alt+Enter (others) and waits up to 5 s for `WS_CAPTION`.
  - `resize-client --hwnd <h> --size WxH` → `{"client": [w,h]}`.
  - `gpu` → `{"free_mb": int, "top": [{"name","pid","mb"}...]}` via `nvidia-smi` and the GPU Process Memory counter.
  - `steamvr` → `{"running": bool, "hmd": bool}` (vrcompositor running; last vrserver.txt line contains `[HMD]` and not `HMD is not found`).
  - `list-windows` → `{"windows": [{"hwnd","title","pid","exe"}...]}` (visible, titled, non-tool) for the "Pick window" fallback.
  - `capture --hwnd <h> --out <path.jpg> [--width 480]` → `{"path": str}` (PrintWindow with `PW_RENDERFULLCONTENT`, client area only) for cover images.
  - `kill-vn3d` → `{"killed": [pids]}` for processes matching `input_bridge\.py|iw3_fast\.py|iw3\.desktop|vn3d[^\\]*\\(app|viewer)`, excluding the caller's own pid.
- Produces (`app/core/platform.gd`): `class_name Platform extends RefCounted`, `static func call_helper(args: PackedStringArray, timeout_s := 10.0) -> Dictionary` (runs `PY -I tools/winhelper.py ...`, parses the last stdout line as JSON, `{"error": ...}` on failure).

- [ ] **Step 1: Failing Python tests** with `tests/py/fake_game.py` (tkinter window titled from argv; with `--spawn-child` it starts a child copy and exits its own window-less parent after 1 s): `test_find_window_child_process` (start fake game with `--spawn-child "Fake [Game] ☆"`, `find-window --pid <parent>` finds the child's window and the exact title), `test_prepare_window_crop` (crop top > 0, client > 0), `test_resize_client` (`640x360` → client `[640,360]`), `test_kill_vn3d_skips_self`, `test_list_windows_contains_fake` (fake game's title present), `test_capture_writes_jpeg` (file exists, width 480).
- [ ] **Step 2: Run** `PY -m unittest tests.py.test_winhelper -v` → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: GDScript test** `test_platform.gd::test_helper_roundtrip`: `Platform.call_helper(["steamvr"])` returns a Dictionary with key `running`. Run runner → PASS.
- [ ] **Step 6: Commit** `feat: windows helper (process-tree window finding, fullscreen switch, gpu, steamvr)`.

### Task 6: Stage and Backends (move code out of main.gd)

**Files:** Create `app/stage/stage.gd` (screen quad/curved mesh, toast, seek bar, layer planes), `app/backends/backend.gd`, `app/backends/depth_backend.gd` (MJPEG client + decode pool + iw3 control channel + auto-convergence + process start), `app/backends/layers_backend.gd`, `app/tests/test_backends.gd`. Modify `app/main.gd` to compose them; it must shrink to scene wiring (< 250 lines).

**Interfaces:**
- Produces `class_name Backend extends Node`: signals `status(text: String)`, `failed(reason: String)`, `frame_ready`; `func start(game: Dictionary, window: Dictionary) -> void` (`window = {hwnd, title, crop: [t,l,r,b]}`), `func stop() -> void`, `func is_running() -> bool`, `func set_strength(v: float)`, `func set_shape(v: float)`, `func latest_sbs() -> Image` (depth) / `func latest_layers() -> Dictionary` (layers).
- `DepthBackend` starts `PY iw3_fast.py` with the exact argument list `vn3d_vr.ps1` uses today (including `--vn3d-shape`, `--resolution 518`, crop, `--disable-draw-cursor`, `--gpu-jpeg`), reads its stdout for status (`Open http://` = ready; `vn3d: depth model CUDA graph captured` = loading step), and owns auto-convergence (`DEPTH_RANGE_PER_STRENGTH = 0.00995`, `FUSE_MARGIN = 0.85`, eye spacing from the XR views, fallback 0.063 m).
- Produces `class_name Stage extends Node3D`: `func show_sbs(img: Image)`, `func show_layers(frame: Dictionary)`, `func set_screen(distance: float, width: float, curved: bool)`, `func recenter(head: Transform3D)`, `func ray_hit(origin: Vector3, dir: Vector3) -> Dictionary` (`{t, uv, point}` incl. curved), `func bar_hit(origin, dir) -> Dictionary` (`{t, frac, point}`), `func toast(text: String)`, `func set_media_status(time_s: float, length_s: float, state: String)`.

- [ ] **Step 1: Failing tests:** `test_depth_backend_fake_stream` (start `tests/fake_iw3_stream.py 1399` as a process, a `DepthBackend` in "attach" mode on port 1399 delivers `latest_sbs()` with size 3840x1080 within 5 s), `test_auto_convergence_values` (screen width 4.01 m, strength 2.3, eye spacing 0.059 → convergence ≈ 0.55 ± 0.01), `test_stage_ray_hit_flat_and_curved` (move the curved test here), `test_layers_backend_fake_sender` (`tests/fake_layer_stream.py` → 4 planes).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** by moving code; no behaviour changes. **Step 4: Run** all Godot tests → PASS.
- [ ] **Step 5: Manual check** (no GPU needed): `GODOT --path app -- --port=1399` against the fake stream shows the picture in the flat preview.
- [ ] **Step 6: Commit** `refactor(app): split viewer into Stage and Backends`.

### Task 7: Input router

**Files:** Create `app/input/input_router.gd`, `app/tests/test_input_router.gd`; modify `app/main.gd`.

**Interfaces:**
- Consumes: `Layouts.action_for`, `Stage.ray_hit/bar_hit/toast`, `Backend.set_strength/set_shape`.
- Produces `class_name InputRouter extends Node`: `func set_layout(layout: Dictionary)`, `func set_vlc_password(p: String)`, `signal menu_requested`; `func feed(input: String, pressed: bool, value := 0.0)` (the test entry point; `_process` calls it from the XR controllers); sends bridge commands (`move`, `click`, `rclick`, `wheel`, `key`, `pad <button> <0|1>`, `stick <left|right> <x> <y>`, `trigger <l|r> <0..1>`, `release_all`) on UDP 1304, VLC commands via HTTP when a password is set.

- [ ] **Step 1: Failing tests** with a fake UDP listener on a spare port: `test_vn_trigger_clicks_at_laser` (feed laser uv 0.5,0.5 then `right_trigger` → `move 0.50000 0.50000` then `click`), `test_video_trigger_pauses` (video preset + password → HTTP `pl_pause` queued, no `click`), `test_reserved_menu_hold` (`left_menu` pressed, 1.1 s of `_process` → `menu_requested` emitted; 0.5 s → not), `test_gamepad_mode_sends_pad` (`right_primary` → `pad a 1` / `pad a 0`), `test_cycle_stick` (stick_click cycles strength → shape → size).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, removing the input code from `main.gd`. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(app): layout-driven input router`.

### Task 8: Input bridge: release_all and gamepad

**Files:** Modify `input_bridge.py`; create `tests/py/test_input_bridge.py`.

**Interfaces:**
- Consumes: commands from Task 7.
- Produces: `release_all` (lift every key/button this bridge pressed, centre the virtual pad, park the cursor), also on exit (`atexit` + Ctrl-C); `pad <name> <0|1>`, `stick <left|right> <x> <y>` (−1..1), `trigger <left|right> <0..1>` via `vgamepad.VX360Gamepad` when importable; otherwise reply `{"error":"vgamepad not installed"}` once on stdout and ignore pad commands. `--dry-run` flag records actions to stdout as JSON instead of calling SendInput/vgamepad (for tests).

- [ ] **Step 1: Failing tests** (`--dry-run`, UDP on a spare port): `test_key_down_then_release_all` (`key ctrl_down`, `release_all` → a ctrl key-up is recorded), `test_pad_without_vgamepad` (no crash, one error line), `test_exit_releases` (terminate the process after `key ctrl_down` → key-up recorded before exit).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5:** Ask the user before `PY -m pip install vgamepad` (and tell them ViGEmBus is a separate driver install); if they decline, gamepad stays "driver needed".
- [ ] **Step 6: Commit** `feat(bridge): release_all, virtual Xbox pad, dry-run for tests`.

### Task 9: Session

**Files:** Create `app/core/session.gd`, `app/core/media_session.gd`, `app/tests/test_session.gd`.

**Interfaces:**
- Consumes: `Library`, `Platform.call_helper` (Task 5 commands), `Backend`, `InputRouter`.
- Produces `class_name Session extends Node`: signals `state_changed(state: String)` (`idle`, `checking`, `starting_game`, `finding_window`, `starting_3d`, `playing`, `stopping`), `needs_user(question: String, options: PackedStringArray)` (VRAM warning, SteamVR off, hook install), `ended(reason: String)`; `func play(game_id: String)`, `func play_media(path: String, upscale: bool)`, `func stop(close_game: bool)`, `func answer(option: String)`; play time added to the game on end.
- `MediaSession` holds the VLC launch arguments exactly as `vn3d_launcher.ps1` builds them today (minimal view, remote control with a 16-hex random password, `--play-and-exit`, `--image-duration=-1`, 10 s jumps, optional `--d3d11-upscale-mode=super`), then `resize-client` to height 1080 at the video's aspect.

- [ ] **Step 1: Failing tests** with `fake_game.py`, a `FakeBackend` (records start/stop) and the bridge in `--dry-run`: `test_play_finds_child_window` (exe = fake game with `--spawn-child`), `test_game_exit_ends_session` (close the fake game → `ended("game closed")`, backend stopped, `release_all` recorded, no child processes left), `test_leftovers_killed_before_play` (start a dummy `iw3_fast.py`-named sleeper first → gone after `play`), `test_low_vram_asks_user` (helper stub returns `free_mb: 2000` → `needs_user` with options `["Close <name>", "Play anyway"]`), `test_media_title_with_brackets` (generated clip copied to `tmp/Clip [1080p].mp4`, `play_media` reaches `starting_3d` with that title), `test_window_not_found_offers_pick` (fake exe that never opens a window, timeout shortened to 2 s → `needs_user` with `["Keep waiting", "Pick window"]`; answering "Pick window" then a listed hwnd continues to `starting_3d`), `test_backend_failure_offers_retry` (FakeBackend emits `failed("CUDA out of memory")` → `needs_user` with `["Retry", "Back to library"]`, game still running; "Retry" restarts only the backend), `test_cover_saved_after_first_play` (cover delay shortened to 1 s → `covers/<id>.jpg` exists and `game.cover` set; not taken again on the second play).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(app): play/stop sessions for games and videos`.

### Task 10: PC window

**Files:** Create `app/ui/pc/pc_window.tscn/.gd`, `game_card.tscn/.gd`, `add_game_dialog.tscn/.gd`, `game_page.tscn/.gd`, `layout_editor.tscn/.gd`, `status_bar.tscn/.gd`; `app/tests/test_pc_ui.gd`. Modify `project.godot` (`config/name="VN3D"`).

**Interfaces:** Consumes `Library`, `Detector`, `Layouts`, `Session`, `Platform`. The PC window is a `Window` node with `gui_embed_subwindows = false`; `game_card.tscn` is reused by the VR shelf (Task 11).

- [ ] **Step 1: Failing tests** (instantiate scenes headless): `test_add_game_flow` (call `add_game_dialog.confirm_with(path)` on a fake Ren'Py folder → library has 1 game named from `log.txt`), `test_missing_exe_badge` (card for a game whose exe doesn't exist shows `"missing"`; its "Find it" action with a new path updates `exe` and clears the badge), `test_gamepad_without_driver` (Platform stub says vgamepad unavailable → layout editor's Gamepad switch shows "driver needed" and stays on Mouse), `test_layout_editor_roundtrip` (change `right_grip` to `key:esc`, save → `Layouts.validate` empty and library updated), `test_strength_slider_saves` (game page slider 2.3 → `depth.divergence == 2.3`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (Add Game uses `DisplayServer.file_dialog_show` with filter `*.exe`; Watch video uses media filters from the launcher). **Step 4: Run** → PASS.
- [ ] **Step 5: Manual check** on the PC (no headset): add the fake game, edit its layout, press Play → flat preview.
- [ ] **Step 6: Commit** `feat(app): PC library window`.

### Task 11: VR library and in-game menu

**Files:** Create `app/ui/vr/vr_shelf.tscn/.gd`, `vr_menu.tscn/.gd`, `app/ui/vr/vr_panel.gd` (Control scene in a `SubViewport` on a quad; laser hit → `InputEventMouseButton/Motion` pushed into the viewport); `app/tests/test_vr_ui.gd`.

**Interfaces:** Consumes `game_card.tscn`, `Library`, `Session`, `InputRouter.menu_requested`, `Stage.ray_hit` (panel quads use the same hit maths).

- [ ] **Step 1: Failing tests:** `test_panel_uv_to_click` (uv 0.25,0.5 on a 1024x512 panel → a click at (256,256) reaches a Button and fires `pressed`), `test_shelf_lists_games` (3 games → 3 cards, newest first), `test_menu_back_to_library` (press "Back to library" → `Session.stop` called with the answer to "Close the game too?"), `test_needs_user_shown_in_vr` (a `Session.needs_user` while in VR shows a panel with the question and one button per option; pressing one calls `Session.answer`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (shelf curved row ~2 m ahead; menu items: Resume, Recenter, 3D strength ±, Shape ±, Swap eyes, Back to library, Quit game). **Step 4: Run** → PASS.
- [ ] **Step 5: Manual headset check** (user present, GPU free): pick a game on the shelf, play, open the menu with the left menu hold, go back.
- [ ] **Step 6: Commit** `feat(app): VR library shelf and in-game menu`.

### Task 12: Ren'Py hook install/remove

**Files:** Create `app/core/renpy_hook.gd`, `app/tests/test_renpy_hook.gd`.

**Interfaces:** `class_name RenpyHook`, `static func install(game_dir: String) -> String` (copies `renpy_hook/vn3d_hook.rpy` to `game/`, returns error or ""), `static func remove(game_dir: String) -> void` (deletes `vn3d_hook.rpy` and `vn3d_hook.rpyc` only), `static func is_installed(game_dir: String) -> bool`. Session asks before install (Task 9 `needs_user`); Remove-game offers removal when `renpy_hook_installed`.

- [ ] **Step 1: Failing tests** on a fake Ren'Py folder: install → file present and identical; remove → both files gone, other `game/` files untouched; install into a folder without `game/` → error string.
- [ ] **Step 2–4:** Run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(app): Ren'Py layer hook install/remove`.

### Task 13: iw3 startup time

**Files:** Create `tests/startup_profile.py`; modify `iw3_fast.py` and `app/backends/depth_backend.gd` as the findings require.

**Interfaces:** `DepthBackend` gains `func prewarm()` (start iw3 with no window, waiting on a `window <title>` control command) if the profile shows model/CUDA init dominates.

- [ ] **Step 1:** `startup_profile.py` runs `iw3_fast.py` against a fake game window (Task 5 `fake_game.py`, 640x360) and timestamps stdout lines plus `python -X importtime` totals; output a table of phases (imports, model load, graph capture, first frame).
- [ ] **Step 2:** Run it twice (cold, warm). Record the numbers in the plan's notes section of the README.
- [ ] **Step 3:** Fix the largest phase (e.g. torch hub network check: set `TORCH_HUB_OFFLINE`/local `hub_dir`; or prewarm). Expected: first frame ≤ 60 s warm on this PC; if not reachable, implement `prewarm()` and show its status in the VR library.
- [ ] **Step 4:** Rerun the profile; record before/after.
- [ ] **Step 5: Commit** `perf: faster iw3 startup`.

### Task 14: Start-up shortcut and docs

**Files:** Create `vn3d.bat` (starts `GODOT --path app` without console: use the non-console Godot exe), `tools/make_shortcut.ps1` (desktop shortcut "VN3D" → `vn3d.bat`); modify `README.md`.

- [ ] **Step 1:** `make_shortcut.ps1` creates the shortcut only when run (the user runs it; do not overwrite the stable shortcut "VN3D (Ren'Py in VR)").
- [ ] **Step 2:** README: new "App" section (library, layouts, video), test commands from Task 1, ports list.
- [ ] **Step 3:** Run all tests (Godot runner + Python unittest) → all PASS.
- [ ] **Step 4: Commit** `docs: VN3D app start-up and README`.
