extends Node3D
# VN3D viewer: shows the iw3-desktop full-SBS MJPEG stream as a big 3D screen in OpenXR,
# with a laser pointer that drives the game through input_bridge.py.
#
# Controls:
#   trigger          click where the laser hits the screen (advance text, pick choices)
#   trigger (off)    pointing away from the screen: bring the screen in front of you
#   grip             right click (Ren'Py game menu)
#   left stick       up = rollback, down = roll forward
#   right stick      up/down = closer/farther, left/right = smaller/bigger
#   A / X            recenter screen
#   B / Y            swap eyes (if depth looks inside-out)
# On the PC window: R = recenter, S = swap eyes.
#
# Stream URL defaults to http://127.0.0.1:1303/stream.jpg; override with
#   godot --path . -- --host=127.0.0.1 --port=1303
#
# Layers mode (Ren'Py hook, renpy_hook/vn3d_hook.rpy): instead of the iw3 SBS stream, the
# game sends its background, sprites and UI as separate images on 127.0.0.1:1305, shown on
# separate planes: background far, sprites in the middle, UI on a near panel.
#   godot --path . -- --mode=layers [--layers-port=1305]
# In layers mode the right stick moves the sprite plane (up/down) and scales everything (left/right).

const BOUNDARY := "--frame"
const MAX_BUFFER := 32 * 1024 * 1024
const INPUT_PORT := 1304
const PRESS := 0.6
const RELEASE := 0.4

var host := "127.0.0.1"
var port := 1303
var mode := "sbs"  # "sbs" (iw3 stream) or "layers" (Ren'Py hook)
var layers_port := 1305

# Layers mode geometry. Every plane covers the same view angle, so from the head the
# layers line up like the flat game; only their depth differs.
var ui_dist := 1.2       # meters, UI / textbox panel (the laser hits this plane)
var sprite_dist := 1.8   # meters, character sprites
var bg_dist := 6.0       # meters, backgrounds and CGs
var view_k := 1.2        # plane width per meter of distance (1.2 is about 62 degrees)
const SPRITE_STEP := 0.04  # meters between stacked sprites

var distance := 3.0      # meters from head to screen
var width := 3.6         # meters
var aspect := 16.0 / 9.0 # of one eye's half of the frame

var _xr_active := false
var _origin: XROrigin3D
var _camera: XRCamera3D
var _controllers: Array[XRController3D] = []
var _screen: MeshInstance3D
var _quad: QuadMesh
var _material: ShaderMaterial
var _status: Label3D
var _texture: ImageTexture
var _first_frame := true

var _anchor_pos := Vector3(0, 1.6, 0)
var _anchor_fwd := Vector3(0, 0, -1)

# Pointer state
var _udp := PacketPeerUDP.new()

# Live 3D strength (iw3 divergence), sent to iw3_fast.py's control port.
const IW3_CONTROL_PORT := 1306
const STRENGTH_FILE := "VN3D-stable/strength.json"  # under %APPDATA%; read by the desktop launcher
var divergence := 1.5
var game_key := ""  # launcher's key for this game (its .exe path)
var _iw3_udp := PacketPeerUDP.new()
var _div_dirty := false
var _div_send_cooldown := 0.0
var _toast: Label3D
var _toast_left := 0.0
# What the right stick's left/right does; a short stick click cycles through these.
const STICK_STRENGTH := 0
const STICK_SHAPE := 1
const STICK_SIZE := 2
var _stick_mode := STICK_STRENGTH
var shape := 0.0  # shape boost (iw3_fast.py): rounder local shapes, 0 = off
var _shape_dirty := false
var _b_down_at := -1.0
var _click_down_at := -1.0
var _eye_debug := false
var media := false  # watching a video in VLC: trigger = play/pause, A/grip = jump back/forward

# VLC remote control (launcher starts VLC with its HTTP interface on 127.0.0.1:8190).
const VLC_URL := "http://127.0.0.1:8190/requests/status.json"
var _vlc_pass := ""
var _vlc_http: HTTPRequest
var _vlc_queue: Array[String] = []  # commands waiting for the single HTTPRequest
var _vlc_busy := false
var _vlc_poll_left := 0.0
var _vlc_time := 0.0
var _vlc_length := 0.0
var _vlc_state := ""
# Seek bar under the screen
var _seek_root: Node3D
var _seek_bg: MeshInstance3D
var _seek_fill: MeshInstance3D
var _seek_head: MeshInstance3D  # playhead marker
var _seek_label: Label3D
var _bar_frac := -1.0  # where the laser points on the bar (0..1), -1 = not on it
const BAR_GAP := 0.06  # metres between screen bottom and bar
const BAR_HEIGHT := 0.035
const SEEK_SHOW_SECONDS := 3.0
var _seek_show_left := SEEK_SHOW_SECONDS  # shown at start, then hides
var curved := false  # curved screen (cylinder around the head) instead of a flat one
var _active := 1  # index into _controllers of the pointing hand
var _laser: MeshInstance3D
var _dot: MeshInstance3D
var _hit_uv := Vector2(-1, -1)
var _last_sent_uv := Vector2(-1, -1)
var _trigger_down := [false, false]
var _grip_down := [false, false]
var _wheel_cooldown := 0.0
var _resizing := false
var _stat_time := 0.0
var _stat_frames := 0
var _stat_renders := 0
var _stat_slow := 0  # rendered frames that took over 1.5x the headset's frame time (SteamVR then reprojects)
var _stat_upload_us := 0
var _stat_upload_max_us := 0
var _profiles := ["", ""]

var _thread: Thread
var _mutex := Mutex.new()
var _latest: Image
var _latest_seq := 0
var _pending_jpeg := PackedByteArray()
var _pending_seq := 0
var _decode_sem := Semaphore.new()
var _decode_threads: Array[Thread] = []
const DECODE_THREADS := 6
var _running := true

# Layers mode state
var _layers_latest: Dictionary = {}  # newest frame from the network thread
var _layer_nodes := {}               # key -> MeshInstance3D
var _layer_order: Array = []         # keys, back to front
var _layer_size := Vector2i(1920, 1080)
var _layer_root: Node3D
var _layer_frames := 0
var _layer_logged := 0
var _layer_shader: Shader = preload("res://layer.gdshader")


const SETTINGS_PATH := "user://settings.cfg"


func _load_settings() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(SETTINGS_PATH) != OK:
		return
	distance = cfg.get_value("screen", "distance", distance)
	width = cfg.get_value("screen", "width", width)
	curved = cfg.get_value("screen", "curved", curved)
	sprite_dist = cfg.get_value("layers", "sprite_dist", sprite_dist)
	view_k = cfg.get_value("layers", "view_k", view_k)
	_material.set_shader_parameter("swap_eyes", cfg.get_value("screen", "swap_eyes", false))


func _save_settings() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("screen", "distance", distance)
	cfg.set_value("screen", "width", width)
	cfg.set_value("screen", "curved", curved)
	cfg.set_value("screen", "swap_eyes", _material.get_shader_parameter("swap_eyes") == true)
	cfg.set_value("layers", "sprite_dist", sprite_dist)
	cfg.set_value("layers", "view_k", view_k)
	cfg.save(SETTINGS_PATH)


func _ready() -> void:
	_parse_args()
	_init_xr()
	_build_scene()
	_load_settings()
	_update_screen()
	_udp.set_dest_address("127.0.0.1", INPUT_PORT)
	_iw3_udp.set_dest_address("127.0.0.1", IW3_CONTROL_PORT)
	_build_toast()
	_material.set_shader_parameter("eye_debug", _eye_debug)
	if media:
		_build_seek_bar()
		_layout_seek_bar()
	var xr_iface := XRServer.primary_interface
	print("eye debug: %s, XR views: %d" % [_eye_debug, xr_iface.get_view_count() if xr_iface else 0])
	_thread = Thread.new()
	if mode == "layers":
		_thread.start(_layers_loop)
	else:
		_thread.start(_stream_loop)
		for i in DECODE_THREADS:
			var t := Thread.new()
			t.start(_decode_loop)
			_decode_threads.append(t)
	# Head pose is not valid on the first frames; recenter once tracking settles.
	get_tree().create_timer(1.5).timeout.connect(recenter)


func _exit_tree() -> void:
	_save_settings()
	_running = false
	if _thread and _thread.is_started():
		_thread.wait_to_finish()
	for t in _decode_threads:
		_decode_sem.post()
	for t in _decode_threads:
		t.wait_to_finish()


func _parse_args() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--host="):
			host = arg.get_slice("=", 1)
		elif arg.begins_with("--port="):
			port = int(arg.get_slice("=", 1))
		elif arg.begins_with("--mode="):
			mode = arg.get_slice("=", 1)
		elif arg.begins_with("--layers-port="):
			layers_port = int(arg.get_slice("=", 1))
		elif arg.begins_with("--shape="):
			shape = float(arg.get_slice("=", 1))
		elif arg.begins_with("--divergence="):
			divergence = float(arg.get_slice("=", 1))
		elif arg.begins_with("--game="):
			game_key = arg.substr(arg.find("=") + 1)
		elif arg == "--eye-debug":
			_eye_debug = true
		elif arg == "--media":
			media = true
		elif arg.begins_with("--vlc-pass="):
			_vlc_pass = arg.get_slice("=", 1)
	print("Mode: %s" % mode)


func _init_xr() -> void:
	var xr := XRServer.find_interface("OpenXR")
	if xr and xr.is_initialized():
		get_viewport().use_xr = true
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		_xr_active = true
		print("OpenXR active")
	else:
		print("OpenXR not available; showing flat preview only")


func _unshaded(color: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = color
	m.no_depth_test = true
	m.render_priority = 10
	return m


func _build_scene() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.02, 0.02, 0.025)
	var world_env := WorldEnvironment.new()
	world_env.environment = env
	add_child(world_env)

	_origin = XROrigin3D.new()
	add_child(_origin)
	_camera = XRCamera3D.new()
	_camera.position = Vector3(0, 1.6, 0)
	_origin.add_child(_camera)
	for tracker in ["left_hand", "right_hand"]:
		var c := XRController3D.new()
		c.tracker = tracker
		c.pose = "aim"
		c.button_pressed.connect(_on_button)
		c.button_released.connect(_on_button_released)
		_origin.add_child(c)
		_controllers.append(c)

	_material = ShaderMaterial.new()
	_material.shader = load("res://sbs_screen.gdshader")
	_quad = QuadMesh.new()
	_screen = MeshInstance3D.new()
	_screen.mesh = _quad
	_screen.material_override = _material
	add_child(_screen)

	_status = Label3D.new()
	_status.font_size = 48
	_status.pixel_size = 0.004
	_status.text = "Waiting for iw3 stream on %s:%d ..." % [host, port]
	_screen.add_child(_status)
	if mode == "layers":
		# _screen stays as the invisible UI plane the laser hits; the layers draw the picture.
		_screen.mesh = null
		_status.text = "Waiting for the Ren'Py hook on 127.0.0.1:%d ..." % layers_port
		_layer_root = Node3D.new()
		add_child(_layer_root)

	# Laser: unit-length cylinder along -Z, scaled to the hit distance each frame.
	var cyl := CylinderMesh.new()
	cyl.top_radius = 0.002
	cyl.bottom_radius = 0.002
	cyl.height = 1.0
	cyl.radial_segments = 6
	_laser = MeshInstance3D.new()
	_laser.mesh = cyl
	_laser.material_override = _unshaded(Color(0.4, 0.8, 1.0, 1.0))
	add_child(_laser)

	var sph := SphereMesh.new()
	sph.radius = 0.015
	sph.height = 0.03
	_dot = MeshInstance3D.new()
	_dot.mesh = sph
	_dot.material_override = _unshaded(Color(1, 1, 1))
	add_child(_dot)

	_update_screen()


func _update_screen() -> void:
	if mode == "layers":
		_quad.size = Vector2(view_k * ui_dist, view_k * ui_dist / aspect)
		_screen.global_position = _anchor_pos + _anchor_fwd * ui_dist
	else:
		_quad.size = Vector2(width, width / aspect)
		_screen.global_position = _anchor_pos + _anchor_fwd * distance
		_screen.mesh = _curved_mesh(width, width / aspect, distance) if curved else _quad
	_screen.look_at(_anchor_pos, Vector3.UP, true)
	_status.position = Vector3(0, 0, 0.01)
	_layout_seek_bar()
	if mode == "layers":
		_layout_layers()


func _curved_arc(w: float, r: float) -> float:
	return minf(w / r, 2.6)  # radians; capped at ~150 degrees


func _curved_mesh(w: float, h: float, r: float) -> ArrayMesh:
	# Part of a cylinder centred on the viewer's head (radius = screen distance), so every point
	# of the screen is the same distance away. Local frame matches the flat quad: the screen's
	# centre is at the origin facing +Z, the cylinder's axis is at (0, y, r).
	var arc := _curved_arc(w, r)
	var segments := 64
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for i in segments + 1:
		var u := float(i) / segments
		var a := (u - 0.5) * arc
		var x := r * sin(a)
		var z := r - r * cos(a)
		var n := Vector3(-sin(a), 0, cos(a))
		for row in 2:
			st.set_normal(n)
			st.set_uv(Vector2(u, float(row)))
			st.add_vertex(Vector3(x, h * 0.5 - h * row, z))
	for i in segments:
		var a0 := i * 2  # top of column i; +1 = bottom
		st.add_index(a0)
		st.add_index(a0 + 2)
		st.add_index(a0 + 1)
		st.add_index(a0 + 1)
		st.add_index(a0 + 2)
		st.add_index(a0 + 3)
	return st.commit()


func recenter() -> void:
	var t := _camera.global_transform
	var fwd := -t.basis.z
	fwd.y = 0.0
	if fwd.length() < 0.01:
		fwd = Vector3(0, 0, -1)
	_anchor_fwd = fwd.normalized()
	_anchor_pos = t.origin
	_update_screen()


func _swap_eyes() -> void:
	_material.set_shader_parameter("swap_eyes", not _material.get_shader_parameter("swap_eyes"))
	_save_settings()


func _send(msg: String) -> void:
	_udp.put_packet(msg.to_ascii_buffer())


func _on_button(action: String) -> void:
	# Everything needed in-game works from the right controller alone (the left one may be off).
	match action:
		"ax_button":
			if media:
				if not _vlc_pass.is_empty():
					_vlc_command("seek&val=-10")
				else:
					_send("key left")  # VLC hotkey: jump back (launcher sets 10 s)
				_show_toast("-10 s")
			else:
				_send("wheel 1")  # Ren'Py: mouse wheel up = roll back one line
				_show_toast("Back")
		"by_button":
			_b_down_at = Time.get_ticks_msec() / 1000.0
		"primary_click":
			_click_down_at = Time.get_ticks_msec() / 1000.0


func _on_button_released(action: String) -> void:
	if action == "primary_click" and _click_down_at >= 0.0:
		var held_click := Time.get_ticks_msec() / 1000.0 - _click_down_at
		_click_down_at = -1.0
		if held_click >= 1.0:
			curved = not curved
			_update_screen()
			_save_settings()
			_show_toast("Curved screen" if curved else "Flat screen")
		else:
			_stick_mode = (_stick_mode + 1) % 3
			_show_toast(["Stick: 3D strength", "Stick: shape boost %.1f" % shape, "Stick: screen size"][_stick_mode])
	if action == "by_button" and _b_down_at >= 0.0:
		var held := Time.get_ticks_msec() / 1000.0 - _b_down_at
		_b_down_at = -1.0
		if held >= 1.0:
			_swap_eyes()
			_show_toast("Eyes swapped")
		else:
			recenter()


func _build_toast() -> void:
	# Small message floating below eye level, e.g. "3D strength 1.7".
	_toast = Label3D.new()
	_toast.font_size = 64
	_toast.outline_size = 12
	_toast.pixel_size = 0.0012
	_toast.no_depth_test = true
	_toast.render_priority = 20
	_toast.position = Vector3(0, -0.22, -1.0)
	_toast.visible = false
	_camera.add_child(_toast)


func _show_toast(text: String, seconds := 1.5) -> void:
	_toast.text = text
	_toast.visible = true
	_toast_left = seconds


func _set_divergence(value: float) -> void:
	divergence = clampf(value, 0.2, 5.0)  # iw3's row_flow handles up to 5.0 in one step
	_div_dirty = true
	_show_toast("3D strength %.1f" % divergence)
	_auto_convergence()


# Measured on iw3's output (tests/measure_disparity.py): the near-to-far shift is about 1% of the
# image width per unit of strength, and convergence sets how much of it lies behind the screen.
const DEPTH_RANGE_PER_STRENGTH := 0.00995
const FUSE_MARGIN := 0.85  # keep the farthest point at 85% of what the eyes can fuse
var convergence := 1.0
var _conv_sent := -1.0


func _ipd() -> float:
	# Eye spacing from the headset's two views; 6.3 cm if not available (no XR).
	var xr := XRServer.primary_interface
	if xr and _xr_active and xr.get_view_count() == 2:
		var t := _camera.global_transform
		var d := xr.get_transform_for_view(0, t).origin.distance_to(xr.get_transform_for_view(1, t).origin)
		if d > 0.04 and d < 0.09:
			return d
	return 0.063


func _auto_convergence() -> void:
	# A point behind the screen is shifted between the eyes by (behind-part of range) x screen width.
	# Past the eye spacing the eyes would have to point outward, which they can't: the background
	# then breaks and the picture reads flat. So keep that shift inside the eye spacing and put the
	# rest of the depth in front of the screen.
	if mode == "layers":
		return
	var total := DEPTH_RANGE_PER_STRENGTH * divergence * width  # metres on the screen
	convergence = clampf(FUSE_MARGIN * _ipd() / maxf(total, 1e-4), 0.0, 1.0)
	if absf(convergence - _conv_sent) > 0.01:
		_iw3_udp.put_packet(("convergence %.3f" % convergence).to_ascii_buffer())
		_conv_sent = convergence


func _set_shape(value: float) -> void:
	shape = clampf(value, 0.0, 3.0)
	_shape_dirty = true
	_show_toast("Shape boost %.1f" % shape)


func _save_strength() -> void:
	if game_key.is_empty():
		return
	var path := OS.get_environment("APPDATA").path_join(STRENGTH_FILE)
	var data := {}
	if FileAccess.file_exists(path):
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
		if parsed is Dictionary:
			data = parsed
	data[game_key] = snappedf(divergence, 0.1)
	data["shape:" + game_key] = snappedf(shape, 0.1)  # read by the launcher too
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(data, "  "))


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_R:
			recenter()
		elif event.keycode == KEY_S:
			_swap_eyes()
		elif event.keycode == KEY_C:
			curved = not curved
			_update_screen()
			_save_settings()
		elif event.keycode == KEY_EQUAL or event.keycode == KEY_KP_ADD:
			_set_divergence(divergence + 0.1)
			_save_strength()
		elif event.keycode == KEY_MINUS or event.keycode == KEY_KP_SUBTRACT:
			_set_divergence(divergence - 0.1)
			_save_strength()
		elif event.keycode == KEY_BRACKETRIGHT:
			_set_shape(shape + 0.1)
			_save_strength()
		elif event.keycode == KEY_BRACKETLEFT:
			_set_shape(shape - 0.1)
			_save_strength()


func _process(delta: float) -> void:
	if mode == "layers":
		_poll_layers()
	else:
		_poll_frame()
	_log_profiles()
	_update_pointer()
	_handle_triggers()
	_handle_sticks(delta)
	_vlc_process(delta)
	if _toast_left > 0.0:
		_toast_left -= delta
		_toast.visible = _toast_left > 0.0
	_div_send_cooldown -= delta
	if (_div_dirty or _shape_dirty) and _div_send_cooldown <= 0.0:
		if _div_dirty:
			_iw3_udp.put_packet(("divergence %.2f" % divergence).to_ascii_buffer())
		if _shape_dirty:
			_iw3_udp.put_packet(("shape %.2f" % shape).to_ascii_buffer())
		_div_dirty = false
		_shape_dirty = false
		_div_send_cooldown = 0.1


func _log_profiles() -> void:
	# Logged so we can see which interaction profile SteamVR gives the PSVR2 Sense controllers.
	for i in _controllers.size():
		var tr := XRServer.get_tracker(_controllers[i].tracker) as XRPositionalTracker
		var p := tr.profile if tr else ""
		if p != _profiles[i]:
			_profiles[i] = p
			print("%s profile: %s" % [_controllers[i].tracker, p])


# ---- pointer ----

func _ray_hit(c: XRController3D) -> Dictionary:
	var origin := c.global_position
	var dir := -c.global_basis.z
	var inv := _screen.global_transform.affine_inverse()
	var o := inv * origin
	var d := inv.basis * dir
	if curved and mode != "layers":
		return _curved_hit(o, d)
	if absf(d.z) < 1e-6:
		return {}
	var t := -o.z / d.z
	if t <= 0.0:
		return {}
	var p := o + d * t
	var hw := _quad.size.x * 0.5
	var hh := _quad.size.y * 0.5
	if absf(p.x) > hw or absf(p.y) > hh:
		return {}
	return {"t": t, "uv": Vector2((p.x + hw) / (2.0 * hw), (hh - p.y) / (2.0 * hh)),
		"point": _screen.global_transform * p}


func _curved_hit(o: Vector3, d: Vector3) -> Dictionary:
	# Ray (in the screen's local frame) against the vertical cylinder of _curved_mesh.
	var r := distance
	var h := width / aspect
	var arc := _curved_arc(width, r)
	var oc := o - Vector3(0, 0, r)  # relative to the cylinder axis
	var a := d.x * d.x + d.z * d.z
	if a < 1e-9:
		return {}
	var b := 2.0 * (oc.x * d.x + oc.z * d.z)
	var c := oc.x * oc.x + oc.z * oc.z - r * r
	var disc := b * b - 4.0 * a * c
	if disc < 0.0:
		return {}
	var t := (-b + sqrt(disc)) / (2.0 * a)  # far root: the controller is inside the cylinder
	if t <= 0.0:
		return {}
	var p := oc + d * t
	var ang := atan2(p.x, -p.z)
	if absf(ang) > arc * 0.5 or absf(p.y) > h * 0.5:
		return {}
	var local := p + Vector3(0, 0, r)
	return {"t": t, "uv": Vector2(ang / arc + 0.5, (h * 0.5 - p.y) / h),
		"point": _screen.global_transform * local}


# ---- VLC remote control + seek bar (video mode) ----

func _build_seek_bar() -> void:
	_vlc_http = HTTPRequest.new()
	_vlc_http.timeout = 2.0
	_vlc_http.request_completed.connect(_on_vlc_reply)
	add_child(_vlc_http)
	_seek_root = Node3D.new()
	_seek_root.visible = false  # until VLC reports a length
	_screen.add_child(_seek_root)
	_seek_bg = MeshInstance3D.new()
	_seek_bg.mesh = QuadMesh.new()
	_seek_bg.material_override = _unshaded(Color(0.15, 0.15, 0.17))
	_seek_root.add_child(_seek_bg)
	_seek_fill = MeshInstance3D.new()
	_seek_fill.mesh = QuadMesh.new()
	var fill_mat := _unshaded(Color(0.35, 0.75, 1.0))
	# All bar parts skip the depth test, so draw order must be explicit: background (10) first,
	# then fill (11), then playhead (12). With equal priorities Godot sorted them by distance and
	# the background could cover the fill.
	fill_mat.render_priority = 11
	_seek_fill.material_override = fill_mat
	_seek_root.add_child(_seek_fill)
	_seek_head = MeshInstance3D.new()
	_seek_head.mesh = QuadMesh.new()
	var head_mat := _unshaded(Color(1, 1, 1))
	head_mat.render_priority = 12
	_seek_head.material_override = head_mat
	_seek_root.add_child(_seek_head)
	_seek_label = Label3D.new()
	_seek_label.font_size = 48
	_seek_label.outline_size = 10
	_seek_label.no_depth_test = true
	_seek_label.render_priority = 20
	_seek_root.add_child(_seek_label)


func _bar_width() -> float:
	return width * 0.9


func _layout_seek_bar() -> void:
	# Bar just under the screen's bottom edge, in the screen's own frame (follows recenter/resizes).
	if _seek_root == null:
		return
	var w := _bar_width()
	var y := -(width / aspect) * 0.5 - BAR_GAP - BAR_HEIGHT * 0.5
	_seek_root.position = Vector3(0, y, 0.005)
	(_seek_bg.mesh as QuadMesh).size = Vector2(w, BAR_HEIGHT)
	var frac := clampf(_vlc_time / _vlc_length, 0.0, 1.0) if _vlc_length > 0.0 else 0.0
	(_seek_fill.mesh as QuadMesh).size = Vector2(maxf(w * frac, 0.001), BAR_HEIGHT)
	_seek_fill.position = Vector3(-w * 0.5 + w * frac * 0.5, 0, 0.002)
	(_seek_head.mesh as QuadMesh).size = Vector2(BAR_HEIGHT * 0.5, BAR_HEIGHT * 2.0)
	_seek_head.position = Vector3(-w * 0.5 + w * frac, 0, 0.004)
	_seek_label.pixel_size = width * 0.0006
	_seek_label.position = Vector3(0, -BAR_HEIGHT * 0.5 - 0.04, 0.002)
	_seek_label.text = "%s %s / %s" % ["Paused " if _vlc_state == "paused" else "", _fmt_time(_vlc_time), _fmt_time(_vlc_length)]


func _bar_hit(c: XRController3D) -> Dictionary:
	# Laser against the bar's plane (screen frame, z = 0); generous height so it's easy to hit.
	var inv := _screen.global_transform.affine_inverse()
	var o := inv * c.global_position
	var d := inv.basis * -c.global_basis.z
	if absf(d.z) < 1e-6:
		return {}
	var t := -o.z / d.z
	if t <= 0.0:
		return {}
	var p := o + d * t
	var w := _bar_width()
	if absf(p.x) > w * 0.5 or absf(p.y - _seek_root.position.y) > BAR_HEIGHT * 2.0:
		return {}
	return {"t": t, "frac": (p.x + w * 0.5) / w, "point": _screen.global_transform * Vector3(p.x, _seek_root.position.y, 0.01)}


func _fmt_time(s: float) -> String:
	var t := int(maxf(s, 0.0))
	if t >= 3600:
		return "%d:%02d:%02d" % [t / 3600, (t / 60) % 60, t % 60]
	return "%d:%02d" % [t / 60, t % 60]


func _show_seek_bar() -> void:
	_seek_show_left = SEEK_SHOW_SECONDS
	_update_seek_visibility()


func _update_seek_visibility() -> void:
	# Shown for a few seconds after any interaction, and always while paused.
	if _seek_root:
		_seek_root.visible = _vlc_length > 0.0 and (_seek_show_left > 0.0 or _vlc_state == "paused")


func _vlc_command(cmd: String) -> void:
	if _vlc_pass.is_empty():
		return
	_vlc_queue.append(cmd)
	_vlc_next()
	_show_seek_bar()  # any play/pause/jump/seek shows where you are


func _vlc_next() -> void:
	if _vlc_busy or _vlc_http == null:
		return
	var url := VLC_URL
	if not _vlc_queue.is_empty():
		url += "?command=" + _vlc_queue.pop_front()
	var headers := ["Authorization: Basic " + Marshalls.utf8_to_base64(":" + _vlc_pass)]
	if _vlc_http.request(url, headers) == OK:
		_vlc_busy = true


func _on_vlc_reply(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_vlc_busy = false
	if result == HTTPRequest.RESULT_SUCCESS and code == 200:
		var st = JSON.parse_string(body.get_string_from_utf8())
		if st is Dictionary:
			if _vlc_length <= 0.0 and float(st.get("length", 0)) > 0.0:
				print("VLC connected: length %s, state %s" % [_fmt_time(float(st.get("length", 0))), st.get("state", "")])
			_vlc_time = float(st.get("time", 0))
			_vlc_length = float(st.get("length", 0))
			_vlc_state = str(st.get("state", ""))
			_update_seek_visibility()
			_layout_seek_bar()
	if not _vlc_queue.is_empty():
		_vlc_next()


func _vlc_process(delta: float) -> void:
	if _vlc_pass.is_empty() or _vlc_http == null:
		return
	if _seek_show_left > 0.0:
		_seek_show_left -= delta
		if _seek_show_left <= 0.0:
			_update_seek_visibility()
	_vlc_poll_left -= delta
	if _vlc_poll_left <= 0.0:
		_vlc_poll_left = 0.5  # status twice a second
		_vlc_next()


func _update_pointer() -> void:
	var c := _controllers[_active]
	var tracked := c.get_has_tracking_data()
	_laser.visible = tracked
	_dot.visible = false
	_hit_uv = Vector2(-1, -1)
	if not tracked:
		return
	var hit := _ray_hit(c)
	var length := 2.0
	_bar_frac = -1.0
	if not hit.is_empty():
		length = hit["t"]
		_hit_uv = hit["uv"]
		_dot.global_position = hit["point"]
		_dot.visible = true
		if _hit_uv.distance_to(_last_sent_uv) > 0.0005:
			_send("move %.5f %.5f" % [_hit_uv.x, _hit_uv.y])
			_last_sent_uv = _hit_uv
	elif _seek_root and _vlc_length > 0.0:
		# The bar may be hidden; aiming where it sits still finds it (and shows it).
		var bh := _bar_hit(c)
		if not bh.is_empty():
			length = bh["t"]
			_bar_frac = bh["frac"]
			_dot.global_position = bh["point"]
			_dot.visible = true
			_show_seek_bar()
	if media and _hit_uv.y > 0.85:
		_show_seek_bar()  # aiming at the bottom edge of the picture brings the bar up
	var start := c.global_position
	var dir := -c.global_basis.z
	_laser.global_transform = Transform3D(Basis.looking_at(dir), start + dir * length * 0.5)
	# Cylinder runs along its local Y; tip it onto -Z and stretch to the hit distance.
	_laser.rotate_object_local(Vector3.RIGHT, PI / 2)
	_laser.scale_object_local(Vector3(1, length, 1))


func _handle_triggers() -> void:
	for i in _controllers.size():
		var c := _controllers[i]
		var trig := c.get_float("trigger")
		if not _trigger_down[i] and trig > PRESS:
			_trigger_down[i] = true
			if i != _active:
				_active = i  # pointer follows the hand that pulled the trigger
				_update_pointer()
			if _bar_frac >= 0.0:
				_vlc_command("seek&val=%d%%25" % int(round(_bar_frac * 100.0)))  # %25 = URL-encoded %
				_show_toast("Jump to %s" % _fmt_time(_bar_frac * _vlc_length))
			elif _hit_uv.x >= 0.0:
				if media:
					# VLC: play / pause (a click there would do nothing useful)
					if not _vlc_pass.is_empty():
						_vlc_command("pl_pause")
					else:
						_send("key space")
					_show_toast("Play / pause")
				else:
					_send("move %.5f %.5f" % [_hit_uv.x, _hit_uv.y])
					_send("click")
			else:
				recenter()
		elif _trigger_down[i] and trig < RELEASE:
			_trigger_down[i] = false

		var grip := c.get_float("grip")
		if not _grip_down[i] and grip > PRESS:
			_grip_down[i] = true
			if media:
				if not _vlc_pass.is_empty():
					_vlc_command("seek&val=%2B10")  # +10 s
				else:
					_send("key right")  # VLC hotkey: jump forward (launcher sets 10 s)
				_show_toast("+10 s")
			else:
				_send("rclick")
		elif _grip_down[i] and grip < RELEASE:
			_grip_down[i] = false


func _handle_sticks(delta: float) -> void:
	# Left stick: rollback / roll forward, repeating while held.
	_wheel_cooldown -= delta
	var left := _controllers[0].get_vector2("primary")
	if absf(left.y) > 0.7 and _wheel_cooldown <= 0.0:
		_send("wheel %d" % (1 if left.y > 0.0 else -1))
		_wheel_cooldown = 0.35
	elif absf(left.y) < 0.3:
		_wheel_cooldown = 0.0

	var stick := _controllers[1].get_vector2("primary")
	if stick.length() < 0.2:
		if _resizing:
			_resizing = false
			_save_settings()
			_save_strength()
		return
	_resizing = true
	if mode == "layers":
		sprite_dist = clampf(sprite_dist - stick.y * 1.0 * delta, ui_dist + 0.2, bg_dist - 0.5)
		view_k = clampf(view_k * (1.0 + stick.x * 0.8 * delta), 0.4, 3.0)
	elif _stick_mode == STICK_SIZE:
		width = clampf(width * (1.0 + stick.x * 0.8 * delta), 0.8, 20.0)
		_auto_convergence()  # a bigger screen magnifies the depth too
	elif absf(stick.x) > absf(stick.y):
		# Left/right: 3D strength or shape boost, about 0.6 per second at full tilt.
		if absf(stick.x) > 0.4:
			if _stick_mode == STICK_SHAPE:
				_set_shape(shape + stick.x * 0.6 * delta)
			else:
				_set_divergence(divergence + stick.x * 0.6 * delta)
		return
	else:
		distance = clampf(distance - stick.y * 1.5 * delta, 0.8, 12.0)
	_update_screen()


func _poll_frame() -> void:
	_mutex.lock()
	var img := _latest
	_latest = null
	_mutex.unlock()
	var dt := get_process_delta_time()
	_stat_time += dt
	_stat_renders += 1
	var hz := 0.0
	var xr := XRServer.primary_interface
	if xr is OpenXRInterface:
		hz = (xr as OpenXRInterface).display_refresh_rate
	if hz > 0.0 and dt > 1.5 / hz:
		_stat_slow += 1
	if _stat_time >= 5.0:
		print("Stream: %.1f fps; render %.0f fps, %d slow frames; upload avg %.1f ms, max %.1f ms" % [
			_stat_frames / _stat_time, _stat_renders / _stat_time, _stat_slow,
			_stat_upload_us / 1000.0 / maxi(_stat_frames, 1), _stat_upload_max_us / 1000.0])
		_stat_time = 0.0
		_stat_frames = 0
		_stat_renders = 0
		_stat_slow = 0
		_stat_upload_us = 0
		_stat_upload_max_us = 0
	if img == null:
		return
	_stat_frames += 1
	var t0 := Time.get_ticks_usec()
	var new_aspect := (img.get_width() * 0.5) / float(img.get_height())
	if _texture == null or _texture.get_size() != Vector2(img.get_size()):
		_texture = ImageTexture.create_from_image(img)
		_material.set_shader_parameter("tex", _texture)
		aspect = new_aspect
		_status.visible = false
		_update_screen()
	else:
		_texture.update(img)
	var up := Time.get_ticks_usec() - t0
	_stat_upload_us += up
	_stat_upload_max_us = maxi(_stat_upload_max_us, up)
	if _first_frame:
		_first_frame = false
		print("First frame %dx%d" % [img.get_width(), img.get_height()])
		recenter()
		# iw3 is up (it sent a frame), so its control port listens: set strength and convergence.
		_div_dirty = true
		_conv_sent = -1.0
		_auto_convergence()
		print("auto convergence %.2f (ipd %.3f m, screen %.2f m, strength %.1f)" % [convergence, _ipd(), width, divergence])


# ---- MJPEG client (runs on a worker thread) ----

func _stream_loop() -> void:
	while _running:
		var tcp := StreamPeerTCP.new()
		if tcp.connect_to_host(host, port) != OK:
			OS.delay_msec(1000)
			continue
		while tcp.get_status() == StreamPeerTCP.STATUS_CONNECTING and _running:
			tcp.poll()
			OS.delay_msec(10)
		if tcp.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			OS.delay_msec(1000)
			continue
		# HTTP/1.0 so the server sends a raw (not chunked) multipart body.
		tcp.put_data(("GET /stream.jpg HTTP/1.0\r\nHost: %s\r\n\r\n" % host).to_ascii_buffer())
		print("Connected to iw3 stream")
		_read_stream(tcp)
		tcp.disconnect_from_host()
		print("Stream disconnected; retrying")
		OS.delay_msec(1000)


func _read_stream(tcp: StreamPeerTCP) -> void:
	var boundary := BOUNDARY.to_ascii_buffer()
	var header_end := "\r\n\r\n".to_ascii_buffer()
	var buf := PackedByteArray()
	var scan_from := 0  # where to resume searching for the next boundary
	while _running:
		tcp.poll()
		if tcp.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			return
		var n := tcp.get_available_bytes()
		if n <= 0:
			OS.delay_msec(2)
			continue
		var r := tcp.get_data(n)
		if r[0] != OK:
			return
		buf.append_array(r[1])

		var last_jpeg := PackedByteArray()
		while true:
			var s := _find(buf, boundary, 0)
			if s < 0:
				break
			var h := _find(buf, header_end, s)
			if h < 0:
				break
			var start := h + header_end.size()
			var e := _find(buf, boundary, maxi(start, scan_from))
			if e < 0:
				# Frame not complete yet; drop bytes before this part, remember scan position.
				scan_from = maxi(start, buf.size() - boundary.size()) - s
				buf = buf.slice(s)
				break
			last_jpeg = buf.slice(start, e)
			buf = buf.slice(e)
			scan_from = 0
		if buf.size() > MAX_BUFFER:
			buf = PackedByteArray()
			scan_from = 0
		if last_jpeg.size() > 0:
			# Hand off to the decode pool; an undecoded older frame is simply replaced.
			_mutex.lock()
			_pending_jpeg = last_jpeg
			_pending_seq += 1
			_mutex.unlock()
			_decode_sem.post()


# JPEG decoding runs on several threads: one 3844x1080 frame takes longer than 1/60 s on one core.
func _decode_loop() -> void:
	while true:
		_decode_sem.wait()
		if not _running:
			return
		_mutex.lock()
		var jpeg := _pending_jpeg
		var seq := _pending_seq
		_pending_jpeg = PackedByteArray()
		_mutex.unlock()
		if jpeg.is_empty():
			continue
		var img := Image.new()
		if img.load_jpg_from_buffer(jpeg) != OK:
			continue
		# RGBA here, off the main thread: GPUs have no 3-byte texture format, so the renderer would
		# otherwise convert RGB to RGBA on the main thread in every upload (~13 ms at 3844x1080,
		# longer than a 120 Hz headset frame: SteamVR then reprojects and moving content warps).
		img.convert(Image.FORMAT_RGBA8)
		img.generate_mipmaps()  # sampled with trilinear + anisotropic filtering (sbs_screen.gdshader)
		_mutex.lock()
		if seq > _latest_seq:  # a slower thread must not overwrite a newer frame
			_latest = img
			_latest_seq = seq
		_mutex.unlock()


static func _find(buf: PackedByteArray, seq: PackedByteArray, from: int) -> int:
	var first := seq[0]
	var length := seq.size()
	var second := seq[1]
	var i := buf.find(first, from)
	while i >= 0 and i + length <= buf.size():
		# Cheap second-byte check first: slicing every candidate is the slow part on big JPEGs.
		if buf[i + 1] == second and buf.slice(i, i + length) == seq:
			return i
		i = buf.find(first, i + 1)
	return -1


# ---- layers mode (Ren'Py hook) ----

func _poll_layers() -> void:
	_mutex.lock()
	var frame := _layers_latest
	_layers_latest = {}
	_mutex.unlock()
	_stat_time += get_process_delta_time()
	if _stat_time >= 5.0:
		print("Layers: %.1f captures/s, %d planes" % [_layer_frames / _stat_time, _layer_nodes.size()])
		_stat_time = 0.0
		_layer_frames = 0
	if frame.is_empty():
		return
	_layer_frames += 1
	_layer_size = Vector2i(int(frame["w"]), int(frame["h"]))
	var new_aspect := float(_layer_size.x) / float(_layer_size.y)
	var seen := {}
	_layer_order = []
	for entry in frame["layers"]:
		var meta: Dictionary = entry["meta"]
		var color: Image = entry["color"]
		var mask: Image = entry["mask"]
		var key: String = meta["key"]
		if color == null:
			continue
		seen[key] = true
		_layer_order.append(key)
		var node: MeshInstance3D = _layer_nodes.get(key)
		if node == null:
			node = MeshInstance3D.new()
			node.mesh = QuadMesh.new()
			var mat := ShaderMaterial.new()
			mat.shader = _layer_shader
			node.material_override = mat
			_layer_root.add_child(node)
			_layer_nodes[key] = node
		if node.get_meta("hash", "") != meta["hash"]:
			var mat := node.material_override as ShaderMaterial
			_set_layer_texture(mat, "color_tex", color)
			mat.set_shader_parameter("has_mask", mask != null)
			if mask != null:
				_set_layer_texture(mat, "mask_tex", mask)
			node.set_meta("hash", meta["hash"])
		node.set_meta("layer", meta)
	for key in _layer_nodes.keys():
		if not seen.has(key):
			_layer_nodes[key].queue_free()
			_layer_nodes.erase(key)
	if _first_frame or absf(new_aspect - aspect) > 0.001:
		aspect = new_aspect
		_status.visible = false
		if _first_frame:
			_first_frame = false
			recenter()
	_layout_layers()
	if _layer_logged < 10 or int(frame["seq"]) % 50 == 0:
		_layer_logged += 1
		var parts := PackedStringArray()
		for key in _layer_order:
			var m: Dictionary = _layer_nodes[key].get_meta("layer")
			parts.append("%s[%s] %dx%d@%d,%d d=%.2fm%s" % [key, m["kind"], m["w"], m["h"], m["x"], m["y"],
				_layer_nodes[key].get_meta("dist", 0.0), " +mask" if int(m.get("mask_size", 0)) > 0 else ""])
		print("Layers seq %d (%dx%d): %s" % [int(frame["seq"]), _layer_size.x, _layer_size.y, "; ".join(parts)])


static func _set_layer_texture(mat: ShaderMaterial, param: String, img: Image) -> void:
	var tex := mat.get_shader_parameter(param) as ImageTexture
	if tex != null and Vector2i(tex.get_size()) == img.get_size() and tex.get_format() == img.get_format():
		tex.update(img)
	else:
		mat.set_shader_parameter(param, ImageTexture.create_from_image(img))


func _layout_layers() -> void:
	if _layer_root == null:
		return
	var basis := _screen.global_basis.orthonormalized()
	var sprite_i := 0
	var bg_i := 0
	for key in _layer_order:
		var node: MeshInstance3D = _layer_nodes.get(key)
		if node == null:
			continue
		var m: Dictionary = node.get_meta("layer")
		var d := sprite_dist
		var prio := 0
		match m["kind"]:
			"bg":
				d = bg_dist - bg_i * SPRITE_STEP
				prio = -60 + bg_i
				bg_i += 1
			"ui":
				d = ui_dist
				prio = -2
			_:
				# Later sprites are drawn over earlier ones, so they sit a little closer.
				d = maxf(sprite_dist - sprite_i * SPRITE_STEP, ui_dist + 0.05)
				prio = -40 + sprite_i
				sprite_i += 1
		var mpp := view_k * d / float(_layer_size.x)  # meters per game pixel at this depth
		var w := float(m["w"])
		var h := float(m["h"])
		var xc := (float(m["x"]) + w * 0.5 - _layer_size.x * 0.5) * mpp
		var yc := -(float(m["y"]) + h * 0.5 - _layer_size.y * 0.5) * mpp
		(node.mesh as QuadMesh).size = Vector2(w * mpp, h * mpp)
		node.global_transform = Transform3D(basis, _anchor_pos + _anchor_fwd * d + basis.x * xc + basis.y * yc)
		node.material_override.render_priority = prio
		node.set_meta("dist", d)


# ---- Ren'Py hook client (runs on a worker thread) ----

func _layers_loop() -> void:
	while _running:
		var tcp := StreamPeerTCP.new()
		if tcp.connect_to_host(host, layers_port) != OK:
			OS.delay_msec(1000)
			continue
		while tcp.get_status() == StreamPeerTCP.STATUS_CONNECTING and _running:
			tcp.poll()
			OS.delay_msec(10)
		if tcp.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			OS.delay_msec(1000)
			continue
		print("Connected to Ren'Py hook")
		_read_layers(tcp)
		tcp.disconnect_from_host()
		print("Ren'Py hook disconnected; retrying")
		OS.delay_msec(1000)


static func _decode_png(data: PackedByteArray, what: String) -> Image:
	var img := Image.new()
	if img.load_png_from_buffer(data) != OK:
		print("Layers: could not decode %s" % what)
		return null
	img.generate_mipmaps()
	return img


func _read_layers(tcp: StreamPeerTCP) -> void:
	# Message: "VN3D" + uint32 big-endian JSON length + JSON header + PNG blobs; per layer
	# "size" bytes of color, then "mask_size" bytes of alpha mask (see vn3d_hook.rpy).
	var buf := PackedByteArray()
	var cache := {}  # key -> [hash, color, mask], so unchanged layers are not decoded again
	while _running:
		tcp.poll()
		if tcp.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			return
		var n := tcp.get_available_bytes()
		if n <= 0:
			OS.delay_msec(2)
			continue
		var r := tcp.get_data(n)
		if r[0] != OK:
			return
		buf.append_array(r[1])
		while buf.size() >= 8:
			if buf.slice(0, 4).get_string_from_ascii() != "VN3D":
				print("Layers: bad message from the hook; reconnecting")
				return
			var hlen := (buf[4] << 24) | (buf[5] << 16) | (buf[6] << 8) | buf[7]
			if buf.size() < 8 + hlen:
				break
			var header = JSON.parse_string(buf.slice(8, 8 + hlen).get_string_from_utf8())
			if typeof(header) != TYPE_DICTIONARY:
				print("Layers: bad header; reconnecting")
				return
			var total := 8 + hlen
			for l in header["layers"]:
				total += int(l["size"]) + int(l.get("mask_size", 0))
			if buf.size() < total:
				break
			var off := 8 + hlen
			var out := []
			var new_cache := {}
			for l in header["layers"]:
				var size := int(l["size"])
				var mask_size := int(l.get("mask_size", 0))
				var key: String = l["key"]
				var color: Image = null
				var mask: Image = null
				if cache.has(key) and cache[key][0] == l["hash"]:
					color = cache[key][1]
					mask = cache[key][2]
				else:
					color = _decode_png(buf.slice(off, off + size), key)
					if mask_size > 0:
						mask = _decode_png(buf.slice(off + size, off + size + mask_size), key + " mask")
				off += size + mask_size
				new_cache[key] = [l["hash"], color, mask]
				out.append({"meta": l, "color": color, "mask": mask})
			cache = new_cache
			buf = buf.slice(total)
			_mutex.lock()
			_layers_latest = {"seq": header["seq"], "w": header["w"], "h": header["h"], "layers": out}
			_mutex.unlock()
